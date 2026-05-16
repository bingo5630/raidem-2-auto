import re
import httpx
import os
import asyncio

ANALYZER_PROMPT = (
    "You are a Scene Context Analyzer for an anime subtitle translation pipeline.\n"
    "Analyze the current lines of dialogue, using the PREVIOUS CONTEXT to maintain the flow, mood, and continuity.\n\n"
    "You MUST output a short text summary covering:\n"
    "1. Scene Mood, Genre & Action: What is the vibe? (e.g., Romance, Slice-of-life, Adventure, or Serious Action fight).\n"
    "2. Characters, Genders & Age: Who is talking to whom? (Identify if it's a Boy, Girl, Child, or Adult). \n"
    "3. Strict Pronoun & Respect Rules: \n"
    "   - 'Tum': Use for boys & girls talking to each other, friends, romance, or adults talking to kids. (This is the Default).\n"
    "   - 'Aap': Use STRICTLY when a child speaks to an adult, or strict formal respect is needed.\n"
    "   - 'Tu': STRICTLY BAN 'Tu' unless they are bitter enemies in a violent fight. Do not use 'Tu' in normal friendly or romantic chats.\n"
    "4. Terminology Lock: Identify any fantasy/anime terms (e.g., Demon, Ghost, Magic, Skill, Guild). Instruct the translator to keep these words in ENGLISH.\n"
)

TRANSLATOR_PROMPT = (
    "You are a Master Indian Anime Localizer (Netflix/Crunchyroll standard). Your job is to LOCALIZE the dialogue so it sounds exactly like real Indian teenagers/adults speaking natural Hinglish.\n"
    "Read the PREVIOUS CONTEXT and SCENE ANALYSIS to adapt the exact mood (Romance, Action, Fantasy, etc.).\n\n"
    "CRITICAL RULES (FAILURE CRASHES THE SYSTEM):\n"
    "1. REMOVE CHARACTER NAMES: NEVER include character names or colons in the output dialogue. If the source text says 'Ijichi: I am angry', output ONLY 'Mai gusse mein hoon'. Strip out 'Seo:', 'Ijichi:', etc.\n"
    "2. STRICT GENDER VERBS (CRITICAL): Pay close attention to the speaker's name/context. A BOY MUST use masculine verbs ('kar raha hoon', 'intezaar kar raha tha'). A GIRL MUST use feminine verbs ('kar rahi hoon'). Do NOT make a boy speak like a girl!\n"
    "3. USE CASUAL TYPING SLANG: Write how people text. Use 'bhot' instead of 'bahut', 'kya karra hai', 'waakai', 'wageraah'.\n"
    "4. LOCALIZE IDIOMS (MUHAVARE): If the English uses an idiom, use a natural Hindi equivalent. (e.g., 'You gave up' = 'Tumne hathiyaar daal diye').\n"
    "5. DROP UNNECESSARY PRONOUNS: Real Hindi speakers skip 'Main' and 'Tum' constantly. (e.g., Instead of 'Main theek hu', say 'Theek hu').\n"
    "6. BANNED FORMAL WORDS: NEVER use heavy dictionary words. \n"
    "   - BANNED: Dhanyavad, Dhanyawad, Katu, Istithna, Suvidh, Khed, Kshama, Pratiksha, Chintit, Jazbaat.\n"
    "   - ALLOWED: Thanks, Shukriya, Kadwa, Exception, Fayda, Sorry, Maaf karna, Intezaar, Tension, Feelings.\n"
    "7. KEEP FANTASY TERMS ENGLISH: Keep words like 'Magic', 'Guild', 'Demon', 'Monster' in English. Do not write 'Rakshas'.\n\n"
    "--- EXAMPLES OF TOP-TIER LOCALIZATION ---\n"
    "BAD: Ijichi: Ye bachche waakai bhot ajeeb ho rahe hai.\n"
    "GOOD: Ye bachche waakai bhot ajeeb ho rahe hain. (Name removed)\n\n"
    "BAD: Yaar, main aaj ka din kaafi intezar kar rahi thi. (Spoken by a Boy)\n"
    "GOOD: Yaar, main aaj ke din ka bhot intezaar kar raha tha. (Gender corrected & 'bhot' used)\n\n"
    "BAD: Bahut dhanyavad.\n"
    "GOOD: Bhot thanks. (Or 'Bhot bhot shukriya')\n\n"
    "BAD: Tum aakhirkar haar maan gaye, huh?\n"
    "GOOD: Toh aakhirkar tumne hathiyaar daal hi diye, huh?\n\n"
    "BAD: Woh sharminda hoti hai jab log use angel bulate hain.\n"
    "GOOD: Usey bhot sharam aati hai jab log usey Angel wageraah kehte hai.\n\n"
    "FORMATTING RULES:\n"
    "- Output ONLY the translated lines wrapped exactly in <t> and </t> tags.\n"
    "- If a sentence exceeds 8 words, insert the \\N tag to split it for screen readability.\n"
    "- Return the EXACT same number of lines as provided."
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
        # strictly set to 0.2 to prevent AI from becoming overly creative/weird
        temp = 0.2 
        full_cycle_count = 0
        
        # Build Context String from Memory
        context_text = "\n".join(previous_context_lines) if previous_context_lines else "None (Start of Scene)"

        if update_callback:
            await update_callback(f"<blockquote>‣ <b>Status :</b> <b>Analysing Scene {idx+1}/{len(chunk_queue)}...</b></blockquote>")

        while not success:
            api_key_1 = api_pool[0]
            
            # PHASE 1: DEEP ANALYSIS (With memory context)
            analyzer_msg = f"--- PREVIOUS CONTEXT (For Continuity) ---\n{context_text}\n\n--- CURRENT LINES TO ANALYZE ---\n{cleaned_chunk}"
            
            try:
                analysis_res = await call_groq(ANALYZER_PROMPT, analyzer_msg, api_key_1, temperature=0.2)
            except Exception:
                analysis_res = "❌"

            if analysis_res in ["RETRY_REQUIRED", "429", "503"] or analysis_res.startswith("❌"):
                if "429" in analysis_res:
                    await asyncio.sleep(15)
                else:
                    await asyncio.sleep(5)
                try:
                    analysis_res = await call_groq(ANALYZER_PROMPT, analyzer_msg, api_key_1, temperature=0.2)
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
                        temp = min(temp + 0.1, 0.4)
                        await asyncio.sleep(0.5)
                        trans_key_idx = (trans_key_idx + 1) % len(api_pool)
                        keys_tried += 1
                        continue

                    chunk_translated = []
                    for trans_line in res_lines:
                        # Extra layer of security: strip leading bracketed names if any slip through
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
