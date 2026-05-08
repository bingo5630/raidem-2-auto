from ..utils.common import edit_msg
import os
import asyncio
import re
import httpx
import json
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from .. import LOGGER, download_dir
from ..utils.uploads.telegram import upload_doc
from ..utils.database.access_db import db
from ..utils.encoding import extract_subtitle, get_width_height

try:
    from deepseek import DeepSeekClient
except ImportError:
    DeepSeekClient = None

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
    "You are a professional Anime Subtitler. Use the Phase 1 analysis to translate into punchy, Street-Style Hinglish.\n\n"
    "STRICT LINGUISTIC RULES:\n"
    "1. RESPECT & HIERARCHY:\n"
    "   - Elders, Teachers, Parents (elder_master): Strictly use 'Aap' (Respectful). Endings: -iye, -hain.\n"
    "   - Peers/Strangers (formal): Use 'Tum'. Endings: -o, -hai.\n"
    "   - Close Friends/Angry context (friends/enemies): Only then use 'Tu'.\n"
    "   - NEVER use 'Tu' for someone older.\n\n"
    "2. FAMILY & VOCABULARY:\n"
    "   - Use 'Dad', 'Papa', 'Bhai', 'Sis/Behen' naturally.\n"
    "   - BAN: Do not use the word 'Baap'. Use 'Dad' or 'Father'.\n\n"
    "3. CONVERSATIONAL FILLERS & SLANG:\n"
    "   - Use 'Hn', 'Achha', 'Oye', 'Yaar' where it fits naturally.\n"
    "   - Use situational slang like 'Kya scene hai?', 'Chill kar', 'Dimag mat kharab kar' to make it sound like real Hinglish conversation.\n\n"
    "4. EMOTION & PUNCTUATION:\n"
    "   - Maintain punctuations like '...', '!', and '?' as they are in the original line.\n"
    "   - Do not translate exclamations like 'Ah!', 'Oh!', 'Eh?'—keep them as is.\n\n"
    "5. LINE LENGTH & FLOW:\n"
    "   - Keep it short and crisp. Subtitles must be easy to read fast.\n"
    "   - Use 'Urban Hinglish' flow. Line original meaning se perfect mel khani chahiye.\n\n"
    "6. GENDER ACCURACY (MANDATORY):\n"
    "   - Verbs MUST be 100% accurate based on Phase 1 analysis.\n"
    "   - MALE: 'Raha hoon', 'Karta hoon', 'Gaya tha', 'Samajh gaya'.\n"
    "   - FEMALE: 'Rahi hoon', 'Karti hoon', 'Gayi thi', 'Samajh gayi'.\n\n"
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

DEEPSEEK_PROMPT = (
    "You are a professional Anime Subtitler. Use the Phase 1 analysis to translate into punchy, Street-Style Hinglish.\n\n"
    "STRICT LINGUISTIC RULES:\n"
    "1. RESPECT & HIERARCHY:\n"
    "   - Elders, Teachers, Parents (elder_master): Strictly use 'Aap' (Respectful). Endings: -iye, -hain.\n"
    "   - Peers/Strangers (formal): Use 'Tum'. Endings: -o, -hai.\n"
    "   - Close Friends/Angry context (friends/enemies): Only then use 'Tu'.\n"
    "   - NEVER use 'Tu' for someone older.\n\n"
    "2. FAMILY & VOCABULARY:\n"
    "   - Use 'Dad', 'Papa', 'Bhai', 'Sis/Behen' naturally.\n"
    "   - BAN: Do not use the word 'Baap'. Use 'Dad' or 'Father'.\n\n"
    "3. CONVERSATIONAL FILLERS & SLANG:\n"
    "   - Use 'Hn', 'Achha', 'Oye', 'Yaar' where it fits naturally.\n"
    "   - Use situational slang like 'Kya scene hai?', 'Chill kar', 'Dimag mat kharab kar' to make it sound like real Hinglish conversation.\n\n"
    "4. EMOTION & PUNCTUATION:\n"
    "   - Maintain punctuations like '...', '!', and '?' as they are in the original line.\n"
    "   - Do not translate exclamations like 'Ah!', 'Oh!', 'Eh?'—keep them as is.\n\n"
    "5. LINE LENGTH & FLOW:\n"
    "   - Keep it short and crisp. Subtitles must be easy to read fast.\n"
    "   - Use 'Urban Hinglish' flow. Line original meaning se perfect mel khani chahiye.\n\n"
    "6. GENDER ACCURACY (MANDATORY):\n"
    "   - Verbs MUST be 100% accurate based on Phase 1 analysis.\n"
    "   - MALE: 'Raha hoon', 'Karta hoon', 'Gaya tha', 'Samajh gaya'.\n"
    "   - FEMALE: 'Rahi hoon', 'Karti hoon', 'Gayi thi', 'Samajh gayi'.\n\n"
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
    "- Translate this batch into Hinglish. Keep ' || ' separators exactly where they are.\n"
    "- No explanations.\n"
    "- No <think> tags.\n"
    "- No skipping.\n"
    "- 1:1 segment matching is mandatory.\n"
    "- If it fails, retry indefinitely (No 3-cycle limit)."
)

TRANSLATE_PIC = "https://graph.org/file/600586a9a49029c2e98f1-90c27ea7986142ea7a.jpg"
TRANSLATE_TEXT = """<blockquote>✨ ᴅᴜᴀʟ-ᴇɴɢɪɴᴇ ᴛʀᴀɴsʟᴀᴛɪᴏɴ sʏsᴛᴇᴍ ✨
ᴘʟᴇᴀsᴇ sᴇʟᴇᴄᴛ ᴀ ᴍᴏᴅᴇʟ ᴛᴏ sᴛᴀʀᴛ ʜɪɴɢʟɪsʜ ᴛʀᴀɴsʟᴀᴛɪᴏɴ.</blockquote>
<blockquote expandable>ʜᴏᴡ ᴛᴏ ᴛʀᴀɴsʟᴀᴛᴇ - sᴛᴇᴘ ʙʏ sᴛᴇᴘ ɢᴜɪᴅᴇ:
➼ sᴛᴇᴘ 1: ɢᴇᴛ ᴋᴇʏs | ɢʀᴏǫ ᴏʀ ᴅᴇᴇᴘsᴇᴇᴋ ᴛᴏᴋᴇɴs.
➼ sᴛᴇᴘ 2: ᴜᴘʟᴏᴀᴅ ʏᴏᴜʀ ғɪʟᴇ
sᴇɴᴅ ʏᴏᴜʀ .ᴀss ᴏʀ sᴜʙᴛɪᴛʟᴇ ғɪʟᴇ ᴅɪʀᴇᴄᴛʟʏ ᴛᴏ ᴛʜᴇ ʙᴏᴛ.
➼ sᴛᴇᴘ 3: sᴇʟᴇᴄᴛ ᴛʜᴇ ᴇɴɢɪɴᴇ
ᴄʜᴏᴏsᴇ ʙᴇᴛᴡᴇᴇɴ ɢʀᴏǫ 🚀 ᴏʀ ᴅᴇᴇᴘsᴇᴇᴋ 🐋 ғᴏʀ ᴘʀᴇᴍɪᴜᴍ sᴜʙs.
➼ sᴛᴇᴘ 4: ᴡᴀɪᴛ ғᴏʀ ᴘʀᴏᴄᴇssɪɴɢ
ᴛʜᴇ ʙᴏᴛ ᴡɪʟʟ sᴘʟɪᴛ ʏᴏᴜʀ ғɪʟᴇ ɪɴᴛᴏ ᴍɪᴄʀᴏ-ᴄʜᴜɴᴋs ғᴏʀ ǫᴜᴀʟɪᴛʏ.</blockquote>
ɴᴏᴛᴇ: ᴛʜᴇ ʙᴏᴛ ɴᴏᴡ sᴜᴘᴘᴏʀᴛs ᴅᴜᴀʟ-ᴇɴɢɪɴᴇ ᴀʀᴄʜɪᴛᴇᴄᴛᴜʀᴇ (ɢʀᴏǫ + ᴅᴇᴇᴘsᴇᴇᴋ)!"""

# Temporary storage for file metadata linked to message ID
translation_data = {}

async def get_translate_buttons(user_id):
    engine = await db.get_translation_engine(user_id)
    engine_display = "Grok 𝕏" if engine == "groq" else "DeepSeek 🐋"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🤖 Model: {engine_display}", callback_data="toggle_trans_engine")
        ],
        [
            InlineKeyboardButton("🚀 Start Translation", callback_data="start_trans_process"),
            InlineKeyboardButton("❌ Close Menu", callback_data="close_btn")
        ]
    ])

def parse_srt(content):
    content = content.replace('\r\n', '\n')
    blocks = re.split(r'\n\s*\n', content.strip())
    parsed = []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3 and (lines[0].isdigit() or '-->' in lines[1]):
            parsed.append({
                'index': lines[0],
                'timestamp': lines[1],
                'text': '\n'.join(lines[2:])
            })
        else:
            parsed.append({'raw': block})
    return parsed

def protect_tags(text, is_ass=True):
    """Protects override tags from being translated by the AI."""
    placeholders = []
    if is_ass:
        # Protect {\...} tags
        tags = re.findall(r'\{[^\}]+\}', text)
        for i, tag in enumerate(tags):
            placeholder = f"__TAG_{i}__"
            text = text.replace(tag, placeholder, 1)
            placeholders.append(tag)
    else:
        # Protect <i>...</i> tags etc for SRT
        tags = re.findall(r'<[^>]+>', text)
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
    # Remove any stray HTML tags (legitimate ones are already protected as __TAG_i__)
    text = re.sub(r'<[^>]+>', '', text)
    # Keep only printable characters and common whitespace
    text = "".join(c for c in text if c.isprintable() or c in ['\n', '\r', '\t'])
    # Strip excessive special characters at start/end but keep placeholders
    return text.strip()

def parse_ass(content):
    lines = content.replace('\r\n', '\n').split('\n')
    header = []
    events = []
    in_events = False
    playresx, playresy = 640, 360 # Locked resolution

    for line in lines:
        if line.strip().startswith('PlayResX:'):
            header.append(f"PlayResX: {playresx}")
            continue
        if line.strip().startswith('PlayResY:'):
            header.append(f"PlayResY: {playresy}")
            continue

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
    return header, events, playresx, playresy


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
                data = response.json(); translated_text = data['choices'][0]['message']['content'].strip()
                print(f"DEBUG Groq Response: {translated_text}")
                translated_text = translated_text.replace('```json', '').replace('```', '').strip()
                if translated_text.strip() == user_content.strip():
                    return "RETRY_REQUIRED"
                return translated_text
            elif response.status_code in [429, 503]:
                return str(response.status_code)
            else: return f"❌ Groq Error: {response.status_code} - {response.text}"
        except Exception as e:
            return f"❌ Groq Error: {str(e)}"

async def call_deepseek(system_prompt, user_content, api_key, temperature=0.2):
    if not DeepSeekClient:
        return "❌ DeepSeekClient not installed"
    if not user_content.strip(): return user_content

    try:
        client = DeepSeekClient(api_key=api_key)
        # Inject all rules into prompt as requested
        full_prompt = f"{system_prompt}\n\nTranslate this:\n{user_content}"

        # Wrapping in run_in_executor if it's not async-friendly,
        # but the request implies direct usage.
        # DeepSeek 0.1.9 logic provided (Run in thread to avoid blocking)
        result = await asyncio.to_thread(
            client.chat,
            prompt=full_prompt,
            model="default",
            thinking=True
        )
        translation = result.response
        # Strip DeepSeek thinking tags
        translation = re.sub(r'<think>.*?</think>', '', translation, flags=re.DOTALL).strip()

        if translation.strip() == user_content.strip():
            return "RETRY_REQUIRED"
        return translation
    except Exception as e:
        # Check for rate limit specifically if possible, otherwise generic 120s handling in loop
        error_msg = str(e)
        if "rate" in error_msg.lower() or "limit" in error_msg.lower():
             return "429"
        return f"❌ DeepSeek Error: {error_msg}"

async def translate_subtitle_chunks(chunk_queue, to_translate, api_pool, status_msg, engine="groq", deepseek_token=None):
    translated_texts = []
    idx = 0
    trans_key_idx = 1 # Start rotation from Key 2 (index 1)

    while idx < len(chunk_queue):
        # original_lines are protected lines without [name] prefix
        original_lines = to_translate[idx*10 : (idx+1)*10]
        # chunk is the one with [name] prefixes
        raw_lines_with_names = chunk_queue[idx].split('\n')
        # Apply cleaning to raw lines before XML tagging
        cleaned_lines = [clean_text_for_ai(line) for line in raw_lines_with_names]
        xml_chunk = "\n".join([f"<t>{line}</t>" for line in cleaned_lines])
        cleaned_chunk = "\n".join(cleaned_lines)

        success = False
        temp = 0.2
        full_cycle_count = 0
        while not success:
            # Phase 1: The Analyst (Key 1 ONLY)
            api_key_1 = api_pool[0]
            await edit_msg(status_msg, f"⏳ [𝐀𝐧𝐚𝐥𝐲𝐬𝐭] : Analyzing chunk {idx+1}/{len(chunk_queue)}...")
            analysis_res = await call_groq(ANALYZER_PROMPT, cleaned_chunk, api_key_1)

            if analysis_res in ["RETRY_REQUIRED", "429", "503"] or analysis_res.startswith("❌"):
                await asyncio.sleep(5)
                analysis_res = await call_groq(ANALYZER_PROMPT, cleaned_chunk, api_key_1)
                if analysis_res in ["RETRY_REQUIRED", "429", "503"] or analysis_res.startswith("❌"):
                    analysis_res = '{"gender": "neutral", "hierarchy": "friends", "tone": "casual", "context": "general anime scene"}'

            # Phase 2: The Translator
            if engine == "deepseek":
                await edit_msg(status_msg, f"⏳ [𝐃𝐞𝐞𝐩𝐒𝐞𝐞𝐤] : Translating chunk {idx+1}/{len(chunk_queue)}...")
                batch_chunk = " || ".join(cleaned_lines)
                res = await call_deepseek(DEEPSEEK_PROMPT, f"Analysis:\n{analysis_res}\n\nLines to Translate:\n{batch_chunk}", deepseek_token, temperature=temp)

                if res == "429":
                    await edit_msg(status_msg, f"⚠️ DeepSeek Rate Limited. Waiting 180s...")
                    await asyncio.sleep(180)
                    continue # Retry same chunk
                elif res in ["RETRY_REQUIRED", "503"] or res.startswith("❌"):
                    await edit_msg(status_msg, f"⚠️ DeepSeek Error. Waiting 180s...")
                    await asyncio.sleep(180)
                    continue
                else:
                    # Strip DeepSeek thinking tags explicitly as safety precaution
                    res = re.sub(r'<think>.*?</think>', '', res, flags=re.DOTALL).strip()
                    # Extraction and Verification
                    res_lines = [l.strip() for l in res.split("||")]
                    if len(res_lines) != len(original_lines):
                        LOGGER.warning(f"Line count mismatch in chunk {idx+1}: Expected {len(original_lines)}, got {len(res_lines)}. Retrying...")
                        temp = min(temp + 0.1, 0.5)
                        await edit_msg(status_msg, f"⚠️ Line count mismatch. Waiting 180s...")
                        await asyncio.sleep(180)
                        continue

                    for trans_line in res_lines:
                        clean_line = re.sub(r'^\[.*?\]:\s*', '', trans_line.strip()).strip()
                        translated_texts.append(clean_line)
                    success = True
            else:
                # Groq Logic (Existing)
                keys_tried = 0
                while keys_tried < 4:
                    api_key_trans = api_pool[trans_key_idx]
                    await edit_msg(status_msg, f"⏳ [𝐓𝐫𝐚𝐧𝐬𝐥𝐚𝐭𝐨𝐫] : Translating chunk {idx+1}/{len(chunk_queue)} (Temp: {temp:.1f})...")
                    res = await call_groq(TRANSLATOR_PROMPT, f"Analysis:\n{analysis_res}\n\nLines to Translate:\n{xml_chunk}", api_key_trans, temperature=temp)

                    if res in ["RETRY_REQUIRED", "429", "503"] or res.startswith("❌"):
                        await asyncio.sleep(0.5) # Immediate Rotation
                        trans_key_idx = trans_key_idx + 1 if trans_key_idx < 4 else 1
                        keys_tried += 1
                    else:
                        # Extraction and Verification
                        res_lines = re.findall(r'<t>(.*?)</t>', res, re.DOTALL)
                        if len(res_lines) != len(original_lines):
                            LOGGER.warning(f"Line count mismatch in chunk {idx+1}: Expected {len(original_lines)}, got {len(res_lines)}. Retrying...")
                            temp = min(temp + 0.1, 0.5)
                            await asyncio.sleep(0.5) # Immediate Rotation
                            trans_key_idx = trans_key_idx + 1 if trans_key_idx < 4 else 1
                            keys_tried += 1
                            continue

                        # Success
                        if trans_key_idx == 4: # Key 5
                            await edit_msg(status_msg, f"✅ Chunk {idx+1} translated. Taking 10s pause...")
                            await asyncio.sleep(10)
                        else:
                            await asyncio.sleep(2)

                        for trans_line in res_lines:
                            # Clean up any remaining speaker prefix that AI might have included inside <t>
                            clean_line = re.sub(r'^\[.*?\]:\s*', '', trans_line.strip()).strip()
                            translated_texts.append(clean_line)

                        trans_key_idx = trans_key_idx + 1 if trans_key_idx < 4 else 1
                        success = True
                        break

            if not success:
                full_cycle_count += 1
                if full_cycle_count >= 999 and engine != "deepseek":
                    LOGGER.error(f"CHUNK STALL DETECTED: Chunk {idx+1} failed 999 full cycles. Content:\n{xml_chunk}")
                    await edit_msg(status_msg, f"⚠️ Chunk {idx+1} failed 999 times. Skipping as last resort...")
                    # Fallback to original lines (protected but untranslated)
                    for orig in original_lines:
                        translated_texts.append(orig)
                    success = True
                    break

                await edit_msg(status_msg, f"⚠️ All keys failed for chunk {idx+1}. Cycle {full_cycle_count}/999. Emergency pause 180s...")
                await asyncio.sleep(180)
                temp = 0.2 # Reset temp for fresh start

        idx += 1
    return None, translated_texts

@Client.on_message(filters.command("translate") & filters.private)
async def translate_cmd_handler(bot: Client, message: Message):
    user_id = message.from_user.id
    if not message.reply_to_message:
        await message.reply_text("❌ Please reply to a video, .ass, or .srt file with /translate")
        return

    replied = message.reply_to_message
    is_video = (replied.video or (replied.document and replied.document.mime_type and replied.document.mime_type.startswith("video/")))
    is_subtitle = (replied.document and replied.document.file_name and replied.document.file_name.lower().endswith((".ass", ".srt")))

    if not (is_video or is_subtitle):
        await message.reply_text("❌ Please reply to a valid video, .ass, or .srt file.")
        return

    reply_markup = await get_translate_buttons(user_id)
    sent_msg = await message.reply_photo(
        photo=TRANSLATE_PIC,
        caption=TRANSLATE_TEXT,
        reply_markup=reply_markup,
        has_spoiler=True
    )

    unique_key = f"{replied.chat.id}_{sent_msg.id}"
    translation_data[unique_key] = {
        'file_id': replied.document.file_id if replied.document else replied.video.file_id,
        'file_name': replied.document.file_name if replied.document else (replied.video.file_name or "video.mp4"),
        'chat_id': replied.chat.id,
        'message_id': replied.id,
        'user_id': user_id,
        'is_video': is_video
    }

@Client.on_message(filters.command("set_groq_api") & filters.private)
async def set_groq_handler(bot: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Usage: /set_groq_api YOUR_KEY_HERE")
        return
    api_key = message.command[1]
    await db.add_groq_api_key(message.from_user.id, api_key)
    await message.reply_text("✅ Groq API Key added to pool successfully!")

@Client.on_message(filters.command("set_deepseek_api") & filters.private)
async def set_deepseek_handler(bot: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ Usage: /set_deepseek_api YOUR_TOKEN_HERE")
        return
    token = message.command[1]

    # Save to /data/config.json as requested
    try:
        os.makedirs("/data", exist_ok=True)
        config_path = "/data/config.json"
        config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
            except:
                pass
        config["deepseek_token"] = token
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        LOGGER.error(f"Error saving to /data/config.json: {e}")

    # Also save to DB for per-user access
    await db.set_deepseek_token(message.from_user.id, token)
    await message.reply_text("✅ DeepSeek API Token saved successfully!")

@Client.on_message(filters.command("view_api") & filters.private)
async def view_api_handler(bot: Client, message: Message):
    api_pool = await db.get_groq_api_pool(message.from_user.id)
    if not api_pool:
        await message.reply_text("❌ Your API Pool is empty.")
        return

    text = "📂 **Your Groq API Pool:**\n\n"
    for i, key in enumerate(api_pool, 1):
        masked_key = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "****"
        text += f"{i}. <code>{masked_key}</code>\n"

    await message.reply_text(text)

@Client.on_message(filters.command("clear_api") & filters.private)
async def clear_api_handler(bot: Client, message: Message):
    await db.clear_groq_api_pool(message.from_user.id)
    await message.reply_text("✅ All Groq API Keys cleared from pool!")


async def process_translation(bot, cb, model_type=None, model_name=None):
    # This will be called from callbacks_.py
    user_id = cb.from_user.id

    engine = await db.get_translation_engine(user_id)
    deepseek_token = None
    api_pool = None

    if engine == "groq":
        api_pool = await db.get_groq_api_pool(user_id)
        if not api_pool:
            await cb.answer("❌ Groq API Pool is Empty!", show_alert=True)
            return
        if len(api_pool) < 5:
            await cb.answer("❌ You need at least 5 Groq API Keys for Studio Flow!", show_alert=True)
            return
    else:
        deepseek_token = await db.get_deepseek_token(user_id)
        if not deepseek_token:
            await cb.answer("❌ DeepSeek API Token not set! Use /set_deepseek_api", show_alert=True)
            return
        # DeepSeek still needs Analyst (Groq Key 1)
        api_pool = await db.get_groq_api_pool(user_id)
        if not api_pool:
            await cb.answer("❌ DeepSeek Engine needs at least 1 Groq Key for Analysis!", show_alert=True)
            return

    unique_key = f"{cb.message.chat.id}_{cb.message.id}"
    file_data = translation_data.get(unique_key)
    replied = None

    if file_data:
        file_id = file_data['file_id']
        file_name = file_data['file_name']
        try:
            replied = await bot.get_messages(file_data['chat_id'], file_data['message_id'])
        except Exception as e:
            LOGGER.error(f"Error fetching message from translation_data: {e}")
            replied = None
    else:
        # 2. Fallback to reply-chain logic
        cmd_msg = cb.message.reply_to_message
        if cmd_msg and cmd_msg.reply_to_message:
            replied = cmd_msg.reply_to_message
            if replied.document and replied.document.file_name and replied.document.file_name.lower().endswith((".ass", ".srt")):
                file_id = replied.document.file_id
                file_name = replied.document.file_name
            else:
                await cb.answer("❌ Please reply to a valid .ass or .srt file.", show_alert=True)
                return
        else:
            await cb.answer("❌ Original file not found. Please try /translate again.", show_alert=True)
            return

    await cb.message.delete()
    status_msg = await bot.send_message(user_id, "⏳ [𝐒𝐭𝐮𝐝𝐢𝐨 𝐅𝐥𝐨𝐰] : 𝐈𝐧𝐢𝐭𝐢𝐚𝐥𝐢𝐳𝐢𝐧𝐠 𝐀𝐫𝐜𝐡𝐢𝐭𝐞𝐜𝐭𝐮𝐫𝐞...")

    file_path = await bot.download_media(
        message=file_id,
        file_name=os.path.join(download_dir, file_name)
    )

    if file_data and file_data.get('is_video'):
        await edit_msg(status_msg, "⏳ [𝐒𝐭𝐮𝐝𝐢𝐨 𝐅𝐥𝐨𝐰] : Extracting subtitles from video...")
        extracted = await extract_subtitle(file_path)
        if not os.path.exists(extracted):
            await edit_msg(status_msg, f"❌ Subtitle extraction failed: {extracted}")
            if os.path.exists(file_path): os.remove(file_path)
            return
        video_path = file_path # Keep track of video to get resolution later
        file_path = extracted
        file_name = os.path.basename(file_path)
    else:
        video_path = None

    # Clean up storage
    if unique_key in translation_data:
        del translation_data[unique_key]

    try:
        with open(file_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            content = f.read()

        is_srt = file_path.lower().endswith(".srt")
        translated_content = ""

        if is_srt:
            parsed_blocks = parse_srt(content)
            to_translate = []
            tags_map = []
            names = []
            for b in parsed_blocks:
                if 'text' in b:
                    protected, placeholders = protect_tags(b['text'].replace('\n', '\\N'), is_ass=False)
                    to_translate.append(protected)
                    tags_map.append(placeholders)
                    names.append("") # SRT doesn't have speaker info in header

            # Send 10 lines at once for context
            chunk_queue = []
            for i in range(0, len(to_translate), 10):
                lines_with_names = []
                for j in range(i, min(i+10, len(to_translate))):
                    name_prefix = f"[{names[j]}]: " if names[j] else ""
                    lines_with_names.append(f"{name_prefix}{to_translate[j]}")
                chunk_queue.append("\n".join(lines_with_names))

            err, translated_texts = await translate_subtitle_chunks(chunk_queue, to_translate, api_pool, status_msg, engine=engine, deepseek_token=deepseek_token)
            if err:
                await edit_msg(status_msg, err)
                return

            final_srt = []
            trans_idx = 0
            for i, b in enumerate(parsed_blocks):
                if 'text' in b:
                    if trans_idx < len(translated_texts):
                        translated_text = restore_tags(translated_texts[trans_idx], tags_map[trans_idx])
                        translated_text = translated_text.replace('\\N', '\n').replace('\\n', '\n')
                        final_srt.append(f"{b['index']}\n{b['timestamp']}\n{translated_text}")
                        trans_idx += 1
                    else: final_srt.append(f"{b['index']}\n{b['timestamp']}\n{b['text']}")
                else: final_srt.append(b['raw'])
            translated_content = "\n\n".join(final_srt)
        else:
            header, events, playresx, playresy = parse_ass(content)

            to_translate = []
            tags_map = []
            names = []
            for item in events:
                if 'text' in item:
                    protected, placeholders = protect_tags(item['text'], is_ass=True)
                    to_translate.append(protected)
                    tags_map.append(placeholders)
                    names.append(item.get('name', ''))

            # Send 10 lines at once for context
            chunk_queue = []
            for i in range(0, len(to_translate), 10):
                lines_with_names = []
                for j in range(i, min(i+10, len(to_translate))):
                    name_prefix = f"[{names[j]}]: " if names[j] else ""
                    lines_with_names.append(f"{name_prefix}{to_translate[j]}")
                chunk_queue.append("\n".join(lines_with_names))

            err, translated_texts = await translate_subtitle_chunks(chunk_queue, to_translate, api_pool, status_msg, engine=engine, deepseek_token=deepseek_token)
            if err:
                await edit_msg(status_msg, err)
                return

            final_events = []
            trans_idx = 0
            for i, item in enumerate(events):
                if 'text' in item:
                    if trans_idx < len(translated_texts):
                        # Restore tags in the translated text
                        restored = restore_tags(translated_texts[trans_idx], tags_map[trans_idx])
                        # Recombine with original prefix
                        final_events.append(item['prefix'] + restored)
                        trans_idx += 1
                    else: final_events.append(item['prefix'] + item['text'])
                else: final_events.append(item['raw'])
            translated_content = "\n".join(header) + "\n" + "\n".join(final_events)
        output_filename = os.path.splitext(file_name)[0] + "_Hinglish" + os.path.splitext(file_name)[1]
        output_path = os.path.join(download_dir, output_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(translated_content)

        caption = f"✅ Translated by AI (Hinglish)\nFile: <code>{output_filename}</code>"
        # If replied is still None (fallback failed), use cb.message as a last resort to send the file
        target_msg = replied if replied else cb.message

        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back to Home", callback_data="back_start"),
            InlineKeyboardButton("❌ Close", callback_data="close_btn")
        ]])

        await upload_doc(target_msg, status_msg, 0, output_filename, output_path, caption=caption, reply_markup=reply_markup)
    except Exception as e:
        LOGGER.error(f"Translation Error: {e}")
        await edit_msg(status_msg, f"❌ Error: {e}")
    finally:
        if os.path.exists(file_path): os.remove(file_path)
        if video_path and os.path.exists(video_path): os.remove(video_path)
        if 'output_path' in locals() and os.path.exists(output_path): os.remove(output_path)
