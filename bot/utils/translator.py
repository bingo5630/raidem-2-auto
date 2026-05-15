import re
import httpx
import os
import asyncio

ANALYZER_PROMPT = (
    "You are a Scene Context Analyzer for an anime subtitle translation pipeline.\n"
    "Analyze the current lines of dialogue, using the PREVIOUS CONTEXT to maintain continuity.\n\n"
    "You MUST output a short text summary covering:\n"
    "1. Scene Context: What is actually happening? (e.g., Are they looking at rain? Fighting? Understand the true meaning, avoid literal misinterpretations).\n"
    "2. Characters & Genders: Who is talking? (Maintain gender continuity from previous lines).\n"
    "3. Pronoun Rules: Specify EXACTLY how they should address each other (Tu/Tum/Aap).\n"
    "4. Terminology Lock: Identify any fantasy/anime terms (e.g., Demon, Ghost, Magic, Skill, Guild, Monster). Instruct the translator to keep these words in ENGLISH.\n"
)

TRANSLATOR_PROMPT = (
    "You are a top-tier expert Anime Subtitle Translator for Indian audiences (like Netflix/Crunchyroll).\n"
    "Translate the provided lines into conversational, punchy Hinglish (Roman alphabet).\n\n"
    "CRITICAL RULES (FAILURE CRASHES THE SYSTEM):\n"
    "1. CONTEXT IS KING: Read the 'PREVIOUS CONTEXT' to understand the scene. Do NOT translate word-for-word. (e.g., If looking at rain, 'I see it for the first time' = 'Maine aisi baarish pehli baar dekhi hai', NOT 'Mujhe pehli baar dekha hai').\n"
    "2. SHORT & PUNCHY: Anime dialogues are fast. Keep translations concise. Remove unnecessary filler words and do not over-explain.\n"
    "3. NATURAL HINGLISH: Speak like real Indian teens in 2026. Use words like 'isey', 'usey', 'arey', 'yaar', 'tension'. \n"
    "4. BANNED DICTIONARY WORDS: NEVER use formal dictionary Hindi or heavy Urdu (e.g., DO NOT use 'Khed', 'Kshama', 'Istithna', 'Chintit'). Use natural words like 'Maaf karna', 'Sab ke sab', 'Tension'.\n"
    "5. GENDER ACCURACY: Verbs MUST perfectly match the speaker's gender (e.g., a girl MUST say 'main aati hoon', a boy says 'main aata hoon'). Look at the context to determine gender.\n"
    "6. NO HINDI FANTASY TERMS: Keep anime/action terms in English! Write 'Demon', 'Monster', 'Magic', 'Skill'. NEVER translate them to 'Bhoot', 'Rakshas', or 'Jaadu'.\n\n"
    "FORMATTING RULES:\n"
    "- Output ONLY the translated lines wrapped exactly in <t> and </t> tags.\n"
    "- If a translated sentence exceeds 8 words, you MUST insert the \\N tag to split it into two lines for screen readability.\n"
    "- You must return the EXACT same number of lines as provided. Do not merge or skip any lines."
)

def protect_tags(text):
    """Protects override tags from being translated by the AI."""
    placeholders = []
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
    trans_key_idx = min(1, len(api_pool) - 1)
    
    # SLIDING WINDOW MEMORY: To keep track of the last 5 translated lines
    previous_context_lines = []

    while idx < len(chunk_queue):
        original_lines = to_translate[idx*10 : (idx+1)*10]
        raw_lines_with_names = chunk_queue[idx].split('\n')
        cleaned_lines = [clean_text_for_ai(line) for line in raw_lines_with_names]
        xml_chunk = "\n".join([f"<t>{line}</t>" for line in cleaned_lines])
        cleaned_chunk = "\n".join(cleaned_lines)

        success = False
        temp = 0.35 # Slightly higher temp for better conversational flow
        full_cycle_count = 0
        
        # Build Context String from Memory
        context_text = "\n".join(previous_context_lines) if previous_context_lines else "None (Start of Scene)"

        if update_callback:
            await update_callback(f"<blockquote>‣ <b>Status :</b> <b>Analysing Scene {idx+1}/{len(chunk_queue)}...</b></blockquote>")

        while not success:
            api_key_1 = api_pool[0]
            
            # PHASE 1: DEEP ANALYSIS (Now with memory context)
            analyzer_msg = f"--- PREVIOUS CONTEXT (For Continuity) ---\n{context_text}\n\n--- CURRENT LINES TO ANALYZE ---\n{cleaned_chunk}"
            
            try:
                analysis_res = await call_groq(ANALYZER_PROMPT, analyzer_msg, api_key_1)
            except Exception:
                analysis_res = "❌"

            if analysis_res in ["RETRY_REQUIRED", "429", "503"] or analysis_res.startswith("❌"):
                if "429" in analysis_res:
                    await asyncio.sleep(15)
                else:
                    await asyncio.sleep(5)
                try:
                    analysis_res = await call_groq(ANALYZER_PROMPT, analyzer_msg, api_key_1)
                except Exception:
                    analysis_res = "❌"
                if analysis_res in ["RETRY_REQUIRED", "429", "503"] or analysis_res.startswith("❌"):
                    analysis_res = "Context: Unknown. Maintain casual tone. Check previous lines for gender."

            current_chunk_analysis = analysis_res
            await asyncio.sleep(2) 

            if update_callback:
                await update_callback(f"<blockquote>‣ <b>Status :</b> <b>Translating</b> chunk {idx+1}/{len(chunk_queue)}...</blockquote>")

            keys_tried = 0
            while keys_tried < min(4, len(api_pool)):
                api_key_trans = api_pool[trans_key_idx]
                try:
                    user_msg = (
                        f"--- PREVIOUS CONTEXT (Do NOT translate this, use for continuity only) ---\n{context_text}\n\n"
                        f"--- SCENE ANALYSIS ---\n{current_chunk_analysis}\n\n"
                        f"--- CURRENT LINES TO TRANSLATE ---\n{xml_chunk}"
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

                    chunk_translated = []
                    for trans_line in res_lines:
                        clean_line = re.sub(r'^\[.*?\]:\s*', '', trans_line.strip()).strip()
                        translated_texts.append(clean_line)
                        chunk_translated.append(clean_line)
                    
                    # Update Memory Window: Save last 5 lines of this chunk for the next chunk
                    previous_context_lines = chunk_translated[-5:]

                    trans_key_idx = (trans_key_idx + 1) % len(api_pool)
                    success = True
                    break

            if not success:
                full_cycle_count += 1
                if full_cycle_count >= 5: 
                    print(f"⚠️ Chunk {idx+1} failed. Falling back to original lines.")
                    for orig in original_lines:
                        translated_texts.append(orig)
                    
                    # Reset memory if we hit a failure to prevent polluting context
                    previous_context_lines = [] 
                    success = True
                    break

                await asyncio.sleep(5)
                temp = 0.35

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
