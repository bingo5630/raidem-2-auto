import aiohttp
import aiofiles
from time import time, sleep
from traceback import format_exc
from math import floor
from os import path as ospath, remove as osremove
from aiofiles.os import remove as aioremove
from pyrogram.errors import FloodWait
from pyrogram import Client
from pyrogram.types import Message
from bot.core.database import db
from bot import bot, Var
from .func_utils import editMessage, sendMessage, convertBytes, convertTime
from .reporter import rep
import os
import re
from monitor import get_vps_usage


# ⚙️ Persistent large-file client for >2GB uploads
LARGE_FILE_SESSION = "AQFmZK0AkQv_"
large_client = Client(
    name="large_upload",
    api_id=Var.API_ID,
    api_hash=Var.API_HASH,
    session_string=LARGE_FILE_SESSION,
    no_updates=True,
    sleep_threshold=60,
    workers=4
)


class TgUploader:
    def __init__(self, message: Message, poster_url: str = None):
        self.cancelled = False
        self.message = message
        self.__name = ""
        self.__qual = ""
        self.__client = bot
        self.__start = time()
        self.__updater = time()
        self.retry_count = 0
        self.max_retries = 3
        self.poster_url = poster_url

    async def download_thumbnail(self, url: str):
        """Download thumbnail if it's a URL and return local path."""
        temp_path = "temp_thumb.jpg"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(temp_path, "wb") as f:
                            await f.write(await resp.read())
                        if os.path.getsize(temp_path) > 0:
                            return temp_path
        except Exception as e:
            await rep.report(f"[download_thumbnail] Error: {e}", "warning", log=False)
        return None

    async def upload(self, path: str, qual: str, delete_after: bool = True):
        """Main upload function with dual-session handling for 2GB+ files."""
        if not os.path.exists(path):
            await rep.report(f"File not found: {path}", "error")
            return None

        file_size = os.path.getsize(path)
        self.__name = os.path.basename(path)
        self.__qual = qual

        # Choose correct client based on file size
        use_alt_client = file_size > 2 * 1024 * 1024 * 1024  # >2GB
        self.__client = large_client if use_alt_client else bot

        # Ensure large client is started and connected for 2GB+ files
        if use_alt_client:
            try:
                if not large_client.is_initialized:
                    await large_client.start()
                    await rep.report(f"Large client started for {convertBytes(file_size)} upload", "info", log=False)
            except Exception as e:
                await rep.report(f"Failed to initialize large client: {e}", "error")
                return None

        try:
            upload_mode = await db.get_upload_mode()
            await rep.report(f"Starting upload ({upload_mode}): {self.__name} ({convertBytes(file_size)})", "info", log=False)
            
            if upload_mode == "document":
                # For document mode: strictly use `/sthumb` document thumbnail
                thumb_path = os.path.join("bot", "utils", "thumb.jpg")
                if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                    thumbnail = thumb_path
                else:
                    thumbnail = None

                sent = await self.__client.send_document(
                    chat_id=Var.FILE_STORE,
                    document=path,
                    thumb=thumbnail,
                    caption=f"<b><a href='https://t.me/HellFire_Academy_Official'>[𝐀ɴɪᴍᴇ 𝐇ᴇʟʟғɪʀᴇ]</a></b> {self.__name.replace('[𝐀ɴɪᴍᴇ 𝐇ᴇʟʟғɪʀᴇ] ', '')}",
                    force_document=True,
                    progress=self.progress_status
                )
            else:
                # For video mode: strictly use poster URL via download or Anilist fallback
                thumbnail = None
                if self.poster_url:
                    thumbnail = await self.download_thumbnail(self.poster_url)

                if thumbnail and not os.path.exists(thumbnail):
                    thumbnail = None

                sent = await self.__client.send_video(
                    chat_id=Var.FILE_STORE,
                    video=path,
                    thumb=thumbnail,
                    caption=f"<b><a href='https://t.me/HellFire_Academy_Official'>[𝐀ɴɪᴍᴇ 𝐇ᴇʟʟғɪʀᴇ]</a></b> {self.__name.replace('[𝐀ɴɪᴍᴇ 𝐇ᴇʟʟғɪʀᴇ] ', '')}",
                    progress=self.progress_status,
                    supports_streaming=True
                )
            self.retry_count = 0
            return sent

        except FloodWait as e:
            await rep.report(f"FloodWait: sleeping {e.value}s", "warning", log=False)
            await sleep(e.value + 2)
            return await self.upload(path, qual)

        except Exception as e:
            self.retry_count += 1
            if self.retry_count < self.max_retries:
                await rep.report(f"Upload attempt {self.retry_count} failed, retrying: {str(e)}", "warning", log=False)
                await sleep(5)
                return await self.upload(path, qual)
            else:
                await rep.report(f"Upload failed after {self.max_retries} retries: {format_exc()}", "error")
                raise e

        finally:
            # Clean up
            if delete_after:
                try:
                    await aioremove(path)
                except Exception:
                    pass

            if thumbnail == "temp_thumb.jpg" and os.path.exists(thumbnail):
                try:
                    os.remove(thumbnail)
                except Exception:
                    pass

    async def progress_status(self, current, total):
        """Progress bar updater for upload."""
        if self.cancelled:
            try:
                self.__client.stop_transmission()
            except Exception:
                pass
            return

        now = time()
        diff = now - self.__start

        if (now - self.__updater) >= 7 or current == total:
            self.__updater = now
            
            try:
                percent = round(current / total * 100, 2)
                speed = current / diff if diff > 0 else 0
                eta = round((total - current) / speed) if speed > 0 else 0
                bar = floor(percent / 8) * "■" + (12 - floor(percent / 8)) * "□"
                sys_status = get_vps_usage()

                from .auto_animes import stylize_quote
                formatted_name = f"“{self.__name.strip()}”"

                progress_str = f"""> ᴀɴɪᴍᴇ ɴᴀᴍᴇ : {stylize_quote(formatted_name)}

<blockquote>‣ <b>Status :</b> <b>Uploading</b>
<code>[{bar}]</code> {percent}%
‣ <b>Uploaded :</b> {convertBytes(current)} / {convertBytes(total)}
‣ <b>Speed :</b> {convertBytes(speed)}/s
‣ <b>Elapsed :</b> {convertTime(diff)}
‣ <b>Remaining :</b> {convertTime(eta)}
‣ <b>Encoded File(s):</b> <code>{Var.QUALS.index(self.__qual) if self.__qual in Var.QUALS else 0} / {len(Var.QUALS)}</code>
‣ <b>System Load :</b> <code>{sys_status}</code></blockquote>

<b>Powered By</b> <a href='https://t.me/HellFire_Academy_Official'>𝐀ɴɪᴍᴇ 𝐇ᴇʟʟғɪʀᴇ</a>
"""
                await editMessage(self.message, progress_str)
            except Exception:
                pass
