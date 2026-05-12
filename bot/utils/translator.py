import re
import httpx
import os
import asyncio

ANALYZER_PROMPT = (
    "Analyze the raw English subtitle lines and context. "
    "Identify the speaker's gender and the social relationship/hierarchy between characters.\n"
    "Hierarchy categories:\n"
    "- elder_master: To Elders/Masters/Strangers\n"
    "- formal: Between Two Elders/Formal\n"
    "- friends: Friends/Siblings (Conversational)\n"
    "- enemies: Enemies/Fights (Harsh)\n\n"
    "Output ONLY a JSON object with these keys: "
    "{\"gender\": \"male/female\", \"hierarchy\": \"elder_master/formal/friends/enemies\", \"tone\": \"casual/serious\", \"context\": \"summary\"}."
)

TRANSLATOR_PROMPT = (
    "You are a top-tier Indian Anime Fansub Translator. Your goal is to make the subtitles sound like a natural, everyday conversation between Indian teenagers or young adults.\n\n"
    "STEP 1: DEEP CONTEXT ANALYSIS (THINK BEFORE TRANSLATING)\n"
    "Before translating a single word, deeply analyze the dialogue context:\n"
    "- Who is speaking to whom? Are they friends, enemies, lovers, or strangers?\n"
    "- What is the emotion? Is it anger, sadness, comedy, or casual talk?\n"
    "- Dedicate your processing to understanding the vibe. DO NOT translate word-for-word. Translate the FEELING and the INTENT.\n\n"
    "STEP 2: NATURAL, DAY-TO-DAY CONVERSATIONAL TONE\n"
    "- Speak like a normal Indian person in 2026. Use casual, everyday Hinglish.\n"
    "- CRITICAL AVOIDANCE: NEVER use old-fashioned, formal, or dictionary Hindi words (e.g., Avoid 'Khed', 'Kshama', 'Pratiksha', 'Chintit', 'Dhanyavad').\n"
    "- PREFERRED WORDS: Use 'Afsos', 'Sorry/Maaf karna', 'Intezaar', 'Tension', 'Shukriya/Thanks'.\n"
    "- Use natural fillers where appropriate (e.g., 'yaar', 'bhai', 'arey', 'pagal', 'kya bakwas hai').\n"
    "- Example of Bad Translation: 'Mujhe pehli baar dekha hai.' (Too literal/robotic).\n"
    "- Example of Good Translation: 'Kya tum mujhe pehli baar dekh rahe ho?' or 'Isne mujhe pehli baar dekha hai yaar.'\n\n"
    "STEP 3: STRICT GENDER & GRAMMAR RULES\n"
    "- Hindi verbs change based on gender. You MUST identify the gender of the speaker and the listener.\n"
    "- If addressing or speaking as a female: Use feminine verbs (Example: 'Do you want to go back, Ladybug?' -> 'Kya tum apne forest wapas jaana chahti ho, Ladybug?' NOT chahta).\n"
    "- If addressing or speaking as a male: Use masculine verbs ('Main nahi jaunga').\n\n"
    "STEP 4: HARD TECHNICAL CONSTRAINTS (FAILURE CRASHES THE SYSTEM)\n"
    "1. ROMAN ALPHABET ONLY: Output strictly in Hinglish (Roman English letters). NO Devanagari script ever.\n"
    "2. FORCED LINE SPLITTING: If a translated sentence exceeds 8 words, you MUST use the \\N tag to break it into two lines for screen readability. (Example: 'Main nahi chahta tha ki \\N yeh sab mere sath ho.')\n"
    "3. STRICT SPELLING: Always write 'isey', 'usey', 'ye', 'wo', 'mujhe', 'tujhe'.\n\n"
    "Follow all steps meticulously for every single line.\n"
    "CORE DIRECTIVES:\n"
    "- Output ONLY translated lines wrapped in <t> and </t> tags.\n"
    "- Match gender and hierarchy from Analysis.\n"
    "- Strict Rule: You must translate every single line into conversational Hindi. Do not summarize, do not skip any line, and do not provide any extra text or explanations. The output MUST have the exact same number of lines as the input."
)

def protect_tags(text):
    """Protects override tags from being translated by the AI."""
    placeholders = []
    # Protect {\...} tags commonly found in ASS files
    tags = re.findall(r'\{[^\}]+\}', text)
    for i, tag in enumerate(tags):
        placeholder = f"__TAG_{i}__"
        text = text.replace(tag, placeholder, 1)
        placeholders.append(tag)
    return text, placeholders

def restore_tags(text, placeholders):
    """Restores protected tags back into the translated text."""
    for i, tag in enumerate(placeholders):
        placeholder = f"__TAG_{i}__"
        text = text.replace(placeholder, tag, 1)
    return text

def clean_text_for_ai(text):
    """Strips unusual symbols, stray HTML tags, and non-printable characters."""
    text = re.sub(r'<[^>]+>', '', text)
    text = "".join(c for c in text if c.isprintable() or c in ['\n', '\r', '\t'])
    return text.strip()

def parse_ass(content):
    lines = content.replace('\r\n', '\n').split('\n')
    header = []
    events = []
    in_events = False

    for line in lines:
        if line.strip().lower().startswith('[events]'):
            in_events = True
            header.append(line)
            continue
        if not in_events:
            header.append(line)
        else:
            if line.strip().startswith('Dialogue:'):
                parts = line.split(',', 9)
                if len(parts) == 10:
                    events.append({'prefix': ",".join(parts[0:9]) + ",", 'text': parts[9], 'name': parts[4].strip()})
                else:
                    events.append({'raw': line})
            else:
                events.append({'raw': line})
    return header, events

async def call_groq(system_prompt, user_content, api_key, temperature=0.2):
    if not user_content.strip(): return user_content
    model_name = "llama-3.3-70b-versatile"
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_name, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}], "temperature": temperature}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            if response.status_code == 200:
                data = response.json()
                translated_text = data['choices'][0]['message']['content'].strip()
                translated_text = translated_text.replace('```json', '').replace('```', '').strip()
                if translated_text.strip() == user_content.strip():
                    return "RETRY_REQUIRED"
                return translated_text
            elif response.status_code in [429, 503]:
                return str(response.status_code)
            else: return f"❌ Groq Error: {response.status_code} - {response.text}"
        except Exception as e:
            return f"❌ Groq Error: {str(e)}"

async def translate_subtitle_chunks(chunk_queue, to_translate, api_pool, update_callback=None):
    if not api_pool:
        print("❌ No API keys available for translation.")
        return "❌ No API keys available for translation.", []

    translated_texts = []
    idx = 0
    trans_key_idx = min(1, len(api_pool) - 1)  # Use 2nd key for translation if available, else 1st

    # Store initial analysis result
    global_analysis_res = None

    while idx < len(chunk_queue):
        original_lines = to_translate[idx*10 : (idx+1)*10]
        raw_lines_with_names = chunk_queue[idx].split('\n')
        cleaned_lines = [clean_text_for_ai(line) for line in raw_lines_with_names]
        xml_chunk = "\n".join([f"<t>{line}</t>" for line in cleaned_lines])
        cleaned_chunk = "\n".join(cleaned_lines)

        success = False
        temp = 0.2
        full_cycle_count = 0

        if update_callback and global_analysis_res is None:
            await update_callback("<blockquote>‣ <b>Status :</b> <b>Analysing...</b></blockquote>")

        while not success:
            api_key_1 = api_pool[0]
            if global_analysis_res is None:
                try:
                    analysis_res = await call_groq(ANALYZER_PROMPT, cleaned_chunk, api_key_1)
                except Exception:
                    analysis_res = "❌"

                if analysis_res in ["RETRY_REQUIRED", "429", "503"] or analysis_res.startswith("❌"):
                    if "429" in analysis_res:
                        await asyncio.sleep(15)
                    else:
                        await asyncio.sleep(5)
                    try:
                        analysis_res = await call_groq(ANALYZER_PROMPT, cleaned_chunk, api_key_1)
                    except Exception:
                        analysis_res = "❌"
                    if analysis_res in ["RETRY_REQUIRED", "429", "503"] or analysis_res.startswith("❌"):
                        analysis_res = '{"gender": "neutral", "hierarchy": "friends", "tone": "casual", "context": "general anime scene"}'

                global_analysis_res = analysis_res
                # Phase 1 delay done ONLY ONCE
                await asyncio.sleep(15)

            if update_callback:
                await update_callback(f"<blockquote>‣ <b>Status :</b> <b>Translating</b> chunk {idx+1}/{len(chunk_queue)}...</blockquote>")

            keys_tried = 0
            while keys_tried < min(4, len(api_pool)):
                api_key_trans = api_pool[trans_key_idx]
                try:
                    user_msg = (
                        f"Analysis:\n{global_analysis_res}\n\n"
                        f"CRITICAL: Do not overuse casual fillers. Only use 'yaar' if it makes explicit sense based on extreme closeness; otherwise keep it natural Hinglish. DO NOT add formal honorifics like 'bhai' unless absolutely natural (e.g., 'Will bhai' makes no sense). address characters naturally. Sound like normal people, not a parody of slang.\n\n"
                        f"Lines to Translate:\n{xml_chunk}"
                    )
                    res = await call_groq(TRANSLATOR_PROMPT, user_msg, api_key_trans, temperature=temp)
                except Exception:
                    res = "❌"

                if res in ["RETRY_REQUIRED", "429", "503"] or res.startswith("❌"):
                    if "429" in res:
                        await asyncio.sleep(15)
                    else:
                        await asyncio.sleep(0.5)
                    trans_key_idx = (trans_key_idx + 1) % len(api_pool)
                    keys_tried += 1
                else:
                    res_lines = re.findall(r'<t>(.*?)</t>', res, re.DOTALL)
                    if len(res_lines) != len(original_lines):
                        temp = min(temp + 0.1, 0.5)
                        await asyncio.sleep(0.5)
                        trans_key_idx = (trans_key_idx + 1) % len(api_pool)
                        keys_tried += 1
                        continue

                    for trans_line in res_lines:
                        clean_line = re.sub(r'^\[.*?\]:\s*', '', trans_line.strip()).strip()
                        translated_texts.append(clean_line)

                    trans_key_idx = (trans_key_idx + 1) % len(api_pool)
                    success = True
                    break

            if not success:
                full_cycle_count += 1
                if full_cycle_count >= 10:
                    print(f"⚠️ Chunk {idx+1} failed 10 times. Falling back to original lines.")
                    for orig in original_lines:
                        translated_texts.append(orig)
                    success = True
                    break

                await asyncio.sleep(5)
                temp = 0.2

        await asyncio.sleep(2)
        idx += 1
    return None, translated_texts


async def translate_subtitle_file(file_path, api_pool, update_callback=None):
    print(f"Starting translation of {file_path}")
    try:
        import aiofiles
        async with aiofiles.open(file_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            content = await f.read()

        header, events = parse_ass(content)

        to_translate = []
        tags_map = []
        names = []
        for item in events:
            if 'text' in item:
                protected, placeholders = protect_tags(item['text'])
                to_translate.append(protected)
                tags_map.append(placeholders)
                names.append(item.get('name', ''))

        chunk_queue = []
        for i in range(0, len(to_translate), 10):
            lines_with_names = []
            for j in range(i, min(i+10, len(to_translate))):
                name_prefix = f"[{names[j]}]: " if names[j] else ""
                lines_with_names.append(f"{name_prefix}{to_translate[j]}")
            chunk_queue.append("\n".join(lines_with_names))

        err, translated_texts = await translate_subtitle_chunks(chunk_queue, to_translate, api_pool, update_callback)
        if err:
            return None

        final_events = []
        trans_idx = 0
        for i, item in enumerate(events):
            if 'text' in item:
                if trans_idx < len(translated_texts):
                    restored = restore_tags(translated_texts[trans_idx], tags_map[trans_idx])
                    final_events.append(item['prefix'] + restored)
                    trans_idx += 1
                else:
                    final_events.append(item['prefix'] + item['text'])
            else:
                final_events.append(item['raw'])

        translated_content = "\n".join(header) + "\n" + "\n".join(final_events)

        output_filename = os.path.splitext(file_path)[0] + "_translated.ass"
        async with aiofiles.open(output_filename, "w", encoding="utf-8") as f:
            await f.write(translated_content)

        return output_filename
    except Exception as e:
        print(f"Translation Error: {e}")
        return None
