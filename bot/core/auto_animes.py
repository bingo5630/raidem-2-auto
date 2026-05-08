import re, os
import asyncio
from asyncio import gather, create_task, sleep as asleep, Event
from asyncio.subprocess import PIPE
from os import path as ospath, system
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove
from traceback import format_exc
from base64 import urlsafe_b64encode
from time import time
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait
from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from .tordownload import TorDownloader
from .database import db
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep
from .text_utils import stylize_quote
from monitor import live_status_updater


async def log_unmapped_anime(anime_name: str):
    anime_name = anime_name.strip()
    try:
        if not ospath.exists("unmapped.log"):
            async with aiopen("unmapped.log", "w") as f:
                await f.write(anime_name + "\n")
            return

        async with aiopen("unmapped.log", "r+") as f:
            lines = await f.readlines()
            if anime_name + "\n" in lines:
                return  # Already logged

            lines.append(anime_name + "\n")
            if len(lines) > 50:
                lines = lines[-50:]

            await f.seek(0)
            await f.truncate()
            await f.writelines(lines)

    except Exception as e:
        await rep.report(f"Unmapped log error: {e}", "error")


btn_formatter = {
    '480': '𝟰𝟴𝟬𝗽',
    '720': '𝟳𝟮𝟬𝗽',
    '1080': '𝟭𝟬𝟴𝟬𝗽',
    'HDRi': '𝗛𝗗𝗿𝗶𝗽',
}

ani_cache.setdefault('reported_ids', set())

# --- add near your imports / globals ---
BOT_USERNAME: str | None = None

async def get_bot_username() -> str:
    global BOT_USERNAME
    if BOT_USERNAME:
        return BOT_USERNAME
    me = await safe_telegram_call(bot.get_me)
    BOT_USERNAME = me.username
    return BOT_USERNAME

async def fetch_animes():
    await rep.report("Fetch Animes Started !!", "info")
    while True:
        await asleep(60)
        if ani_cache['fetch_animes']:
            for idx, rss_list in enumerate([Var.RSS_ITEMS_1, Var.RSS_ITEMS_2], start=1):
                for link in rss_list:
                    info = await getfeed(link, 0)
                    if info:
                        bot_loop.create_task(get_animes(info.title, info.link))
                    else:
                        await rep.report(f"No info from link: {link}", "warning")


def clean_torrent_title(raw_name: str) -> str:
    """
    Cleans up messy torrent names for better AniList matching.
    """
    name = re.sub(r'.S\d+E\d+.', '', raw_name, flags=re.IGNORECASE)
    name = re.sub(r'.E\d+.', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\b(480p|720p|1080p|2160p|4K|WEB-DL|WEBRip|BluRay|BRRip|HDRip|x264|x265|H.264|H.265|HEVC)\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[._]+', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

async def safe_telegram_call(func, *args, **kwargs):
    """Wrapper to handle FloodWait errors on Telegram API calls."""
    while True:
        try:
            return await func(*args, **kwargs)
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
        except Exception as e:
            raise e

async def get_animes(name, torrent, force=False):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist()
        ani_id, ep_no = aniInfo.adata.get('id'), aniInfo.pdata.get("episode_number")

        titles = aniInfo.adata.get("title") or {}
        anime_title = (
            titles.get("english")
            or titles.get("romaji")
            or titles.get("native")
            or clean_torrent_title(name)
        ).lower().strip()

        channel_id = await db.get_anime_channel(anime_title)
        poster = await db.get_anime_poster(anime_title)
        if not channel_id:
            ani_cache.setdefault("unmapped", set())
            if anime_title not in ani_cache["unmapped"]:
                await log_unmapped_anime(anime_title)
                ani_cache["unmapped"].add(anime_title)
            # Ignore the torrent if no mapped channel_id is found
            return

        if ani_id not in ani_cache['ongoing']:
            ani_cache['ongoing'].add(ani_id)
        elif not force:
            return
        if not force and ani_id in ani_cache['completed']:
            return

        ani_data = await db.getAnime(ani_id)
        qual_data = ani_data.get(ep_no) if ani_data else None

        if force or not ani_data or not qual_data or not all(qual for qual in qual_data.values()):
            if "[BATCH]" in name:
                await rep.report(f"Torrent Skipped!\n\n{name}", "warning")
                return

            if ani_id not in ani_cache["reported_ids"]:
                await rep.report(f"New Anime Torrent Found!\n\n{name}", "info")
                ani_cache["reported_ids"].add(ani_id)

            post_msg = await safe_telegram_call(
                bot.send_photo,
                channel_id,
                photo=poster or await aniInfo.get_poster(),
                caption=await aniInfo.get_caption()
            )

            season_no = aniInfo.pdata.get("season_number", 1)
            ep_no = aniInfo.pdata.get("episode_number", 1)
            bot_loop.create_task(
    post_channel_info_delayed(anime_title, post_msg.id, season_no, ep_no, source=name)
)

            await safe_telegram_call(
                bot.send_sticker,
                channel_id,
                "CAACAgUAAxkBAAIdGWnG3U-IBDhpJ6fohwwniusJznreAAJCDgACgRPJV4urjemz8MAbOgQ"
            )

            await asyncio.sleep(1.5)
            stat_msg = await safe_telegram_call(
                sendMessage,
                channel_id,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Downloading...</i>"
            )

            stop_event = asyncio.Event()
            monitor_task = asyncio.create_task(live_status_updater(stat_msg, name, "📥 Downloading", stop_event))
            dl = await TorDownloader("./downloads").download(torrent, name)
            stop_event.set()
            await monitor_task

            if not dl or not ospath.exists(dl):
                await rep.report("File Download Incomplete, Try Again", "error")
                await safe_telegram_call(stat_msg.delete)
                return

            post_id = post_msg.id
            ffEvent = Event()
            ff_queued[post_id] = ffEvent

            if ffLock.locked():
                await safe_telegram_call(
                    editMessage,
                    stat_msg,
                    f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Queued to Encode...</i>\n\nPowered by @Anime_Raven"
                )
                await rep.report("Added Task to Queue...", "info")

            await ffQueue.put(post_id)
            await ffEvent.wait()
            await ffLock.acquire()

            # Phase 1: Subtitle Extraction & Translation
            await safe_telegram_call(
                editMessage,
                stat_msg,
                f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Extracting & Translating Subtitles...</i>"
            )
            await rep.report("Starting Subtitle Extraction...", "info")

            # Temporary subtitle paths
            from os import path as ospath
            import subprocess
            from bot.utils.translator import translate_subtitle_file

            sub_path = ospath.join("encode", "temp_sub_extract.ass")
            translated_sub_path = None

            # Extract .ass subtitles
            dl_file = dl
            if ospath.isdir(dl):
                import glob
                files = glob.glob(ospath.join(dl, "*.mkv")) + glob.glob(ospath.join(dl, "*.mp4"))
                if files: dl_file = files[0]

            proc = await asyncio.create_subprocess_exec("ffmpeg", "-y", "-i", dl_file, "-map", "0:s:0?", sub_path)
            await proc.wait()

            # Get Groq API Keys for translation
            bot_user_id = (await get_bot_username()) # Assuming owner set it up, ideally we pass a valid user ID or system default
            api_pool = await db.get_groq_api_pool("global_groq_pool") # Using the fixed pool ID

            if ospath.exists(sub_path):
                translated_sub_path = await translate_subtitle_file(sub_path, api_pool)
            else:
                await rep.report("No Subtitles Found or Extraction Failed.", "warning")

            uploaded_links = {}

            # Phase 2: Sequential Master Encode (1080p), Compress (720p, 480p) & Upload
            encoding_flow = [
                {'qual': '1080', 'is_master': True},
                {'qual': '720', 'is_master': False},
                {'qual': '480', 'is_master': False}
            ]

            master_dl_path = dl_file
            out_paths = {}

            for step in encoding_flow:
                qual = step['qual']
                is_master = step['is_master']

                filename = await aniInfo.get_upname(qual)
                await safe_telegram_call(
                    editMessage,
                    stat_msg,
                    f"‣ <b>Anime Name :</b> <b><i>{name}</i></b>\n\n<i>Encoding {qual}p...</i>"
                )
                await asyncio.sleep(1.5)
                await rep.report(f"Starting Encode for {qual}p...", "info")

                try:
                    # If it's a compressed version, we encode from the newly created 1080p master file
                    input_file = out_paths.get('1080') if not is_master else dl

                    encoder = FFEncoder(stat_msg, input_file, filename, qual, is_master=is_master, sub_path=translated_sub_path)
                    out_path = await encoder.start_encode()
                    out_paths[qual] = out_path
                except Exception as e:
                    await rep.report(f"Encoding Error ({qual}p): {e}", "error")
                    await safe_telegram_call(stat_msg.delete)
                    if ffLock.locked(): ffLock.release()
                    return

                await rep.report(f"Successfully Compressed {qual}p. Now Uploading...", "info")
                await safe_telegram_call(
                    editMessage,
                    stat_msg,
                    f"‣ <b>Anime Name :</b> <b><i>{filename}</i></b>\n\n<i>Uploading {qual}p...</i>"
                )
                await asyncio.sleep(1.5)

                try:
                    msg = await TgUploader(stat_msg).upload(out_path, qual)
                except Exception as e:
                    await rep.report(f"Upload Error ({qual}p): {e}", "error")
                    await safe_telegram_call(stat_msg.delete)
                    if ffLock.locked(): ffLock.release()
                    return

                await rep.report(f"Successfully Uploaded {qual}p to Telegram.", "info")
                msg_id = msg.id
                bot_user = await get_bot_username()
                token = await encode('get-' + str(msg_id * abs(Var.FILE_STORE)))
                link = f"https://t.me/{bot_user}?start={token}"
                uploaded_links[qual] = link

                await db.saveAnime(ani_id, ep_no, qual, post_id)
                bot_loop.create_task(extra_utils(msg_id, out_path))

            # Phase 3: Update Original Post Buttons
            if post_msg and uploaded_links:
                btns = [
                    [
                        InlineKeyboardButton("480p", url=uploaded_links.get('480', '')),
                        InlineKeyboardButton("720p", url=uploaded_links.get('720', ''))
                    ],
                    [
                        InlineKeyboardButton("✨1080p✨", url=uploaded_links.get('1080', ''))
                    ]
                ]

                await safe_telegram_call(
                    editMessage,
                    post_msg,
                    post_msg.caption.html if post_msg.caption else "",
                    InlineKeyboardMarkup(btns)
                )

            if ffLock.locked():
                ffLock.release()
            await safe_telegram_call(stat_msg.delete)
            await aioremove(dl)
            if ospath.exists(sub_path): await aioremove(sub_path)
            if translated_sub_path and ospath.exists(translated_sub_path): await aioremove(translated_sub_path)

        ani_cache['completed'].add(ani_id)

    except Exception:
        await rep.report(format_exc(), "error")
        if ffLock.locked():
            ffLock.release()

async def post_channel_info_delayed(
    anime_name: str,
    post_id: int,
    season: int = 1,
    episode: int = 1,
    *,
    source: str | None = None
):

    await asyncio.sleep(1100)

    anime_name = (anime_name or "").lower().strip()
    anime_title = anime_name

    # --- Resolve posting channels ---
    channel_id_main = await db.get_main_channel() or Var.MAIN_CHANNEL
    channel_id = await db.get_anime_channel(anime_name)
    if channel_id == Var.MAIN_CHANNEL:
        return
    if not channel_id:
        print(f"[INFO] No specific channel found for anime: {anime_name}")
        return

    # --- Get chat & invite link for "Watch" button ---
    try:
        chat = await bot.get_chat(channel_id)
    except Exception as e:
        print(f"[ERROR] Get Chat Error: {e}")
        return

    try:
        if getattr(chat, "username", None):
            invite_link = f"https://t.me/{chat.username}/{post_id}"
        else:
            invite_obj = await bot.create_chat_invite_link(channel_id)
            invite_link = invite_obj.invite_link
    except Exception as e:
        print(f"[ERROR] Failed to create invite link: {e}")
        invite_link = await db.get_anime_invite(anime_name)

    # --- AniList metadata loader ---
    ani = TextEditor(anime_name)
    await ani.load_anilist()

    # Use the torrent/file name for parsing so we catch [Dual]/Eng+Jap etc.
    # (This also sets episode/quality/audio/season onto ani.pdata)
    parse_source = source or anime_name
    await ani.extract_metadata(parse_source)

    # ---------- Inbuilt audio inference (robust) ----------
    # Prefer TextEditor.get_audio (normalizes), but add a hardened fallback.
    async def infer_audio_label_from_filename(filename: str) -> tuple[str, str]:
        
        fn = (filename or "").lower()

        # "dual audio", "dual", "2 audio", "two audio", eng+jap, jp+eng
        is_dual = any([
            re.search(r"\bdual(?:[-_\s]?audio)?\b", fn),
            re.search(r"\b(?:2\s*audio|two\s*audio)\b", fn),
            re.search(r"\b(?:eng(?:lish)?)[^a-z0-9]{0,6}(?:jap(?:anese)?|jp)\b", fn),
            re.search(r"\b(?:jap(?:anese)?|jp)[^a-z0-9]{0,6}(?:eng(?:lish)?)\b", fn),
        ])

        # "multi audio", "multi", "3 audio", "tri-audio"
        is_multi = any([
            re.search(r"\bmulti(?:[-_\s]?audio)?\b", fn),
            re.search(r"\b(?:3\s*audio|tri[-_\s]*audio)\b", fn),
        ])

        if is_multi:
            return "multi", "Multi Audio"
        if is_dual:
            return "dual", "Dual Audio"

        # "esub/esubs/sub/subbed/jap/japanese" -> sub
        if any(k in fn for k in ["esub", "esubs", "subbed", "sub", "jap", "japanese"]):
            return "sub", "Japanese (Esubs)"

        # Safe default
        return "sub", "Japanese (Esubs)"

    # Try your built-in normalizer first:
    try:
        audio_label = await ani.get_audio(filename=parse_source, return_label=True)
        # Also capture machine code for potential logic, though you only need the label for display
        audio_code = (await ani.get_audio(filename=parse_source, return_label=False)) or "sub"
    except Exception:
        audio_code, audio_label = await infer_audio_label_from_filename(parse_source)

    # Quality from parsed metadata (default if missing)
    quality = (ani.pdata.get("quality") or "720p")

    # --- Title & season tags ---
    title_data = ani.adata.get("title", {})
    title = title_data.get("english") or title_data.get("romaji") or title_data.get("native") or "Unknown Title"
    season_tag = (ani.adata.get("season") or "Season").title()
    year_tag = str(ani.adata.get("seasonYear") or "2025")
    # seasonal_hashtag kept if you want to append it elsewhere
    seasonal_hashtag = f"#{season_tag}Ongoing{year_tag}"

    # --- Build header (uses corrected audio label) ---
    header = (
        f"<blockquote><b>{title}</b></blockquote>\n"
        f"──────────────────────\n"
        f"<b>➥ Audio: {audio_label}</b>\n"
        f"<b>➤ Quality: 480p, 720p, 1080p & HDrip</b>\n"
        f"<b>➥ Episode: {str(episode).zfill(2)}</b>\n"
        f"──────────────────────\n"
        f"<blockquote>"
    )

    # --- Description shaping (trim to Telegram limits) ---
    desc = (ani.adata.get("description") or "").replace("<br>", "").replace("\n", " ").strip()
    desc = re.sub(r"Source:.*?", "", desc).strip()
    parts = re.split(r'[.!?]\s+', desc, maxsplit=1)
    if len(parts) >= 2:
        quote = stylize_quote(parts[0])
        summary = stylize_quote(parts[1])
    else:
        quote = stylize_quote(desc)
        summary = ""
    quote_text = f"“{quote}.”"
    summary_words = summary.split()

    max_caption_len = 1024
    success = False

    for i in range(len(summary_words), -1, -1):
        trimmed_summary = " ".join(summary_words[:i]) + ("..." if i < len(summary_words) else "")
        full_desc = f"<blockquote expandable><b>➥{trimmed_summary}</b></blockquote>"
        temp_caption = header + full_desc
        if len(temp_caption) <= max_caption_len:
            try:
                poster = await db.get_anime_poster(anime_title) or await ani.get_poster()
                if not poster:
                    poster = "https://i.ibb.co/WvV8cmGc/photo-2025-05-06-02-54-16-7520721484596117512.jpg"

                await bot.send_photo(
                    channel_id_main,
                    photo=poster,
                    caption=temp_caption,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ ᴛᴏ ᴡᴀᴛᴄʜ •", url=invite_link)
                    ]])
                )
                print(f"[INFO] Successfully posted anime info for {anime_name} (audio={audio_code})")
                success = True
                break
            except Exception as e:
                if "MEDIA_CAPTION_TOO_LONG" not in str(e):
                    print(f"[ERROR] Post Failed: {e}")
                    return

    # --- Fallback with minimal caption if trimming loop failed ---
    if not success:
        print("[WARN] Using minimal fallback caption")
        minimal_caption = header + quote_text
        try:
            poster = await db.get_anime_poster(anime_title) or await ani.get_poster()
            if not poster:
                poster = "https://i.ibb.co/WvV8cmGc/photo-2025-05-06-02-54-16-7520721484596117512.jpg"
            await bot.send_photo(
                channel_id_main,
                photo=poster,
                caption=minimal_caption,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ ᴛᴏ ᴡᴀᴛᴄʜ •", url=invite_link)
                ]])
            )
            print(f"[INFO] Successfully posted fallback info for {anime_name} (audio={audio_code})")
        except Exception as e:
            print(f"[ERROR] Final Post Failed: {e}")

async def extra_utils(msg_id, out_path):
    msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)
    if Var.BACKUP_CHANNEL:
        for chat_id in Var.BACKUP_CHANNEL.split():
            await msg.copy(int(chat_id))


def stylize_quote(text: str) -> str:
    """Stylize text into Unicode small caps + digits for dramatic effect."""
    fancy_map = str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-",
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"
        "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿−"
    )
    return text.translate(fancy_map)
