from json import loads as jloads
from bot.core.database import db
from aiohttp import ClientSession
from bot import Var, bot, ffQueue
from bot.core.text_utils import TextEditor
from bot.core.reporter import rep

TD_SCHR = None  # Global reference to schedule message

# ✅ 1. Tumhari nayi schedule image ka link yahan set ho gaya hai
SCHEDULE_IMAGE = "https://graph.org/file/bc962c32f2ec4ed76c59c-8379d0ae93756c4185.jpg"

def to_12hr(time_str: str):
    """
    Converts 24hr time to 12hr format
    """
    try:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = parts[1] if len(parts) > 1 else "00"

        if hour == 0:
            return f"12:{minute} AM"
        elif hour < 12:
            return f"{hour}:{minute} AM"
        elif hour == 12:
            return f"12:{minute} PM"
        else:
            return f"{hour - 12}:{minute} PM"
    except Exception:
        return time_str


async def upcoming_animes():
    global TD_SCHR
    channel_id = await db.get_main_channel() or Var.MAIN_CHANNEL

    if Var.SEND_SCHEDULE:
        try:
            async with ClientSession() as ses:
                res = await ses.get(
                    "https://subsplease.org/api/?f=schedule&h=true&tz=Asia/Kolkata"
                )
                res_text = await res.text()
                aniContent = jloads(res_text)["schedule"]

            header = "<b>✦ 𝗧𝗢𝗗𝗔𝗬 | 𝗔𝗡𝗜𝗠𝗘 𝗦𝗖𝗛𝗘𝗗𝗨𝗟𝗘</b>\n────────────────────\n"
            chunks = []
            current_chunk = header

            # Get mapped channels from DB
            whitelist_map = await db.list_all_anime_channels()
            whitelist = list(whitelist_map.keys()) if whitelist_map else []
            whitelist_lower = [w.lower().strip() for w in whitelist]

            mapped_animes = []

            for i in aniContent:
                aname = TextEditor(i["title"])
                await aname.load_anilist()
                
                titles = aname.adata.get("title", {})
                eng_title = titles.get("english", "")
                romaji_title = titles.get("romaji", "")
                
                display_title = eng_title or romaji_title or i["title"]

                is_mapped = False
                matched_keyword = None
                for w in whitelist_lower:
                    if (eng_title and w in eng_title.lower()) or \
                       (romaji_title and w in romaji_title.lower()) or \
                       (w in i["title"].lower()):
                        is_mapped = True
                        matched_keyword = w
                        break

                if not is_mapped:
                    continue

                # ✅ 2. DYNAMIC INVITE LINK LOGIC
                # Default fallback agar DB mein link na mile
                invite_link = "https://t.me/HellFire_Academy_Official"
                if matched_keyword:
                    # Database se us anime ka mapped invite link nikalega
                    db_invite = await db.get_anime_invite(matched_keyword)
                    if db_invite:
                        invite_link = db_invite

                time_12 = to_12hr(i["time"])

                # Hyperlink mein ab main channel ke badle '{invite_link}' pass ho raha hai
                entry = (
                    f"<blockquote><b>››  <a href='{invite_link}'>{display_title}</a></b></blockquote>\n"
                    f"<b>›› ᴛɪᴍᴇ : {time_12}</b>\n"
                    f"<b>›› sᴛᴀᴛᴜs : ⏳ Upcoming</b>\n"
                    "────────────────────\n"
                )

                mapped_animes.append(entry)

            if not mapped_animes:
                await rep.report("No mapped animes airing today. Skipping schedule post.", "info")
                return

            for entry in mapped_animes:
                if len(current_chunk) + len(entry) > 1000:
                    chunks.append(current_chunk)
                    current_chunk = entry 
                else:
                    current_chunk += entry
            
            chunks.append(current_chunk)

            banner = SCHEDULE_IMAGE or await db.get_banner()

            if banner:
                try:
                    TD_SCHR = await bot.send_photo(channel_id, banner, caption=chunks[0])
                except Exception:
                    TD_SCHR = await bot.send_message(channel_id, chunks[0])
            else:
                TD_SCHR = await bot.send_message(channel_id, chunks[0])

            if len(chunks) > 1:
                for i in range(1, len(chunks)):
                    await bot.send_message(channel_id, chunks[i])

            try:
                if TD_SCHR:
                    pinned_msg = await TD_SCHR.pin()
                    try:
                        if pinned_msg: await pinned_msg.delete()
                    except: pass
            except: pass

        except Exception as err:
            await rep.report(f"Schedule Error: {str(err)}", "error")

    if not ffQueue.empty():
        await ffQueue.join()

async def update_shdr(name, link):
    global TD_SCHR
    if not TD_SCHR:
        return

    content = TD_SCHR.caption if TD_SCHR.photo else TD_SCHR.text
    if not content:
        return

    lines = content.split("\n")
    found = False

    for i, line in enumerate(lines):
        if name.lower() in line.lower():
            if i + 2 < len(lines) and "⏳ Upcoming" in lines[i + 2]:
                lines[i + 2] = "<b>›› sᴛᴀᴛᴜs : ✅ Uploaded</b>"
                lines.insert(i + 3, f"<i>›› ʟɪɴᴋ : {link}</i>")
                found = True
            break

    if found:
        updated_text = "\n".join(lines)
        try:
            if TD_SCHR.photo:
                await TD_SCHR.edit_caption(updated_text)
            else:
                await TD_SCHR.edit_text(updated_text)
        except Exception as err:
            await rep.report(f"Update Schedule Error: {str(err)}", "error")
