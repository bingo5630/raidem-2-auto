from json import loads as jloads
from bot.core.database import db
from aiohttp import ClientSession
from bot import Var, bot, ffQueue
from bot.core.text_utils import TextEditor
from bot.core.reporter import rep

TD_SCHR = None  # Global reference to schedule message

# Your provided schedule image link
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
            
            # List to store chunks of text
            chunks = []
            current_chunk = header

            whitelist_map = await db.list_all_anime_channels()
            whitelist = list(whitelist_map.keys()) if whitelist_map else []
            mapped_animes = []

            for i in aniContent:
                # Compare title to whitelist
                is_mapped = False
                for w in whitelist:
                    if w.lower() in i["title"].lower():
                        is_mapped = True
                        break

                if not is_mapped:
                    continue

                aname = TextEditor(i["title"])
                await aname.load_anilist()
                title = aname.adata.get("title", {}).get("english") or i["title"]

                time_12 = to_12hr(i["time"])

                entry = (
                    f"<blockquote><b>››  <a href='https://t.me/HellFire_Academy_Official'>{title}</a></b></blockquote>\n"
                    f"<b>›› ᴛɪᴍᴇ : {time_12}</b>\n"
                    f"<b>›› sᴛᴀᴛᴜs : ⏳ Upcoming</b>\n"
                    "────────────────────\n"
                )

                mapped_animes.append(entry)

            if not mapped_animes:
                return

            for entry in mapped_animes:
                # Telegram Caption limit is 1024. Using 1000 for safety buffer.
                if len(current_chunk) + len(entry) > 1000:
                    chunks.append(current_chunk)
                    current_chunk = entry # Start new chunk without header
                else:
                    current_chunk += entry
            
            chunks.append(current_chunk)

            # Prioritize your custom image, then DB banner
            banner = SCHEDULE_IMAGE or await db.get_banner()

            # Send the first chunk with the Photo
            if banner:
                try:
                    TD_SCHR = await bot.send_photo(channel_id, banner, caption=chunks[0])
                except Exception:
                    TD_SCHR = await bot.send_message(channel_id, chunks[0])
            else:
                TD_SCHR = await bot.send_message(channel_id, chunks[0])

            # Send remaining chunks as follow-up messages
            if len(chunks) > 1:
                for i in range(1, len(chunks)):
                    await bot.send_message(channel_id, chunks[i])

            # Pin the main message (Photo message)
            try:
                pinned_msg = await TD_SCHR.pin()
                await pinned_msg.delete()
            except:
                pass

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
            # Check if already updated to prevent duplicate links
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
