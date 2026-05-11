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
    "You are a professional Anime Subtitler. Use the Phase 1 analysis to translate into standard, conversational Hindi.\n\n"
    "STRICT LINGUISTIC RULES (ZERO TOLERANCE FOR DEVIATION):\n"
    "1. NO SHUDDH (PURE) HINDI / FORMALITY:\n"
    "   - Do NOT use overly formal or literary Hindi (e.g., avoid 'Dhund', 'Kshama', 'Atah'). Use everyday spoken conversational language.\n"
    "   - Keep the tone colloquial and natural, but not overly slangy. It should sound like standard spoken Hindi, not an epic poem.\n\n"
    "2. BREVITY IS KEY:\n"
    "   - Keep translation segments SHORT and CONCISE.\n"
    "   - Avoid lengthy, complicated sentences. The text must not clutter the screen.\n\n"
    "3. GENDER ACCURACY (MANDATORY):\n"
    "   - There is ZERO room for error on who is male and who is female.\n"
    "   - Ensure speaker gender from Phase 1 is correctly detected and used in the sentence structure (verbs/adjectives) EVERY SINGLE TIME.\n"
    "   - MALE: 'Raha hoon', 'Karta hoon', 'Gaya tha', 'Samajh gaya'.\n"
    "   - FEMALE: 'Rahi hoon', 'Karti hoon', 'Gayi thi', 'Samajh gayi'.\n\n"
    "4. ADDRESS (TU/TUM/AAP) RULES (Strict Conditional Logic):\n"
    "   - Boy addressing Girl (or vice-versa): ALWAYS use 'Tum'.\n"
    "   - Boy addressing Boy (or Girl addressing Girl - Same Sex, Equals/Friends): Use 'Tu'.\n"
    "   - Elder addressing Child (or vice-versa): ALWAYS use 'Tum' for the child. Respect protocols must be maintained, use 'Aap' for elders if strictly necessary, but prefer conversational tone.\n\n"
    "5. FAMILY & VOCABULARY:\n"
    "   - Use 'Dad', 'Papa', 'Bhai', 'Behen' naturally.\n"
    "   - BAN: Do not use the word 'Baap'. Use 'Dad' or 'Father'.\n\n"
    "6. EMOTION & PUNCTUATION:\n"
    "   - Maintain punctuations like '...', '!', and '?' as they are in the original line.\n"
    "   - Do not translate exclamations like 'Ah!', 'Oh!', 'Eh?'—keep them as is.\n\n"
    "MASTER WORD-LIST:\n"
    "1. This/It ➔ Isey | 2. That/Him/Her ➔ Usey | 3. They/Them ➔ Wo log / Unhe | 4. Who ➔ Kaun | 5. My/Mine ➔ Mera / Mere\n"
    "6. You (Respect) ➔ Aap | 7. You (Casual) ➔ Tum | 8. You (Aggressive) ➔ Tu / Abey | 9. Your/Yours ➔ Tera / Tumhara | 10. Everyone ➔ Sab / Sab log\n"
    "11. Actually ➔ Asal mein | 12. Anyway ➔ Khair / Chodo usey | 13. But ➔ Par / Lekin | 14. Wait ➔ Ruk / Wait kar | 15. Sorry ➔ Maaf karna\n"
    "16. Help ➔ Madad / Help | 17. Please ➔ Please / Zara | 18. Excuse me ➔ Suno / Suniye | 19. Hey ➔ Abey / Oye | 20. Listen ➔ Sun / Meri baat sun\n"
    "21. Right? ➔ Hai na? | 22. Seriously? ➔ Serious ho? / Mazak kar rahe ho? | 23. Damn/Shit ➔ Lanaat hai / Satyanash / Teri toh | 24. Brother ➔ Bhai / Bhaiyya | 25. Sir/Master ➔ Sir / Malik / Master\n"
    "26. Look/See ➔ Dekh / Dekho | 27. Understand ➔ Samajh gaya / Samajh raha hai | 28. Go/Gone ➔ Niklo / Chala gaya | 29. Come ➔ Aa / Aao | 30. Stop ➔ Ruko / Bas kar\n"
    "31. Start ➔ Shuru kar / Shuru ho jao | 32. Kill ➔ Khatam kar dunga / Maar dunga | 33. Die ➔ Mar jaa / Maut | 34. Live ➔ Zinda / Jeena | 35. Win ➔ Jeet / Jeetna\n"
    "36. Lose ➔ Haar / Haar gaya | 37. Strong ➔ Taqatwar / Mazboot | 38. Weak ➔ Kamzor | 39. Protect ➔ Bachana / Hifazat karna | 40. Attack ➔ Hamla / Attack\n"
    "41. Why ➔ Kyun | 42. How ➔ Kaise | 43. What ➔ Kya | 44. Where ➔ Kahan | 45. When ➔ Kab | 46. Maybe ➔ Shayad | 47. Sure/Of course ➔ Bilkul / Haan kyun nahi\n"
    "48. Problem ➔ Dikkat / Problem / Lafda | 49. Everything ➔ Sab kuch | 50. Nothing ➔ Kuch nahi | 51. Someone ➔ Koi | 52. Shut up ➔ Chup kar / Mooh band rakh\n"
    "53. Don't worry ➔ Fikar mat kar / Tension mat le | 54. I see ➔ Achha toh ye baat hai / Samajh gaya | 55. Amazing/Cool ➔ Gazab / Zabardast | 56. Scared ➔ Dar gaya / Khauf | 57. Angry ➔ Gussa\n"
    "58. Happy ➔ Khush | 59. Sad ➔ Dukhi / Pareshan | 60. Beautiful/Pretty ➔ Khoobsurat / Pyari | 61. Magic ➔ Magic / Jadoo | 62. Level ➔ Level\n"
    "63. System ➔ System | 64. Status ➔ Status | 65. Skill ➔ Skill / Hunar | 66. Power ➔ Power / Taqat | 67. Quest/Task ➔ Kam / Mission\n"
    "68. Points ➔ Points | 69. Monster ➔ Monster / Rakshas | 70. Dungeon ➔ Dungeon / Gufa | 71. Already ➔ Pehle hi | 72. Still ➔ Abhi bhi | 73. Again ➔ Phir se\n"
    "74. Never ➔ Kabhi nahi | 75. Forever ➔ Hamesha ke liye | 76. Enough ➔ Kaafi hai | 77. Too much ➔ Bohot zyada | 78. Little bit ➔ Thoda sa | 79. Actually ➔ Sach bolu toh\n"
    "80. Believe ➔ Yakeen / Bharosa | 81. I am sorry ➔ Mujhe maaf kar do / I'm sorry | 82. I will do it (M) ➔ Main ye kar dunga | 83. I will do it (F) ➔ Main ye kar dungi | 84. Where are you going? (Elder) ➔ Aap kahan ja rahe hain?\n"
    "85. Where are you going? (Friend) ➔ Tu kahan ja raha hai? | 86. Don't touch me! ➔ Mujhe haat mat lagana! | 87. Look at this ➔ Isey dekho | 88. Get out ➔ Niklo yahan se / Bahar nikal\n\n"
    "CORE DIRECTIVES:\n"
    "- Output ONLY translated lines wrapped in <t> and </t> tags.\n"
    "- Match gender and hierarchy from Analysis.\n"
    "- Keep sentences short, accurate, and punchy.\n"
    "- Ensure natural flow, avoid robotic literal translation.\n"
    "- Strict Rule: You must translate every single line into Hinglish. Do not summarize, do not skip any line, and do not provide any extra text or explanations. The output MUST have the exact same number of lines as the input. DO NOT remove or modify previous rules. DO NOT modify or re-translate previous lines. If there is a delay, wait, but NEVER skip."
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
            await update_callback("> ᴘʜᴀꜱᴇ 1: ᴀɴᴀʟʏᴢɪɴɢ...")

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
                await update_callback(f"> ᴘʜᴀꜱᴇ 2: ᴛʀᴀɴꜱʟᴀᴛɪɴɢ ᴄʜᴜɴᴋ {idx+1}/{len(chunk_queue)}...")

            keys_tried = 0
            while keys_tried < min(4, len(api_pool)):
                api_key_trans = api_pool[trans_key_idx]
                try:
                    res = await call_groq(TRANSLATOR_PROMPT, f"Analysis:\n{global_analysis_res}\n\nLines to Translate:\n{xml_chunk}", api_key_trans, temperature=temp)
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
