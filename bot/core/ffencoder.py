from re import findall
from math import floor
from time import time
from os import path as ospath, makedirs
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, rename as aiorename
from asyncio import sleep as asleep, gather, create_subprocess_shell, create_task
from asyncio.subprocess import PIPE
from urllib.parse import urlparse, unquote
import aiohttp
import pathlib
import json
import subprocess
import glob
import logging

from bot import Var, ffpids_cache, LOGS
from bot.core.database import db
from .func_utils import mediainfo, convertBytes, convertTime, editMessage
from .reporter import rep

# Encoding args (CLEANED: Removed -c:s copy to prevent dirty metadata clashes)
ffargs = {
    '1080': (
        "-c:v libx264 -preset veryfast -crf 24 "
        "-pix_fmt yuv420p -movflags +faststart "
        "-c:a libopus -b:a 96k -vbr on" 
    ),
    '720': (
        "-c:v libx264 -preset veryfast -crf 28 "
        "-pix_fmt yuv420p -movflags +faststart "
        "-c:a libopus -b:a 80k -vbr on"
    ),
    '480': (
        "-c:v libx264 -preset veryfast -crf 32 "
        "-pix_fmt yuv420p -movflags +faststart "
        "-c:a libopus -b:a 64k -vbr on"
    ),
    'HDRi': "-c copy"
}

if not ospath.exists("encode"):
    makedirs("encode", exist_ok=True)


class FFEncoder:
    def __init__(self, message, path, name, qual, is_master=False, sub_path=None, poster_url=None):
        self.__proc = None
        self.is_cancelled = False
        self.message = message
        self.__name = name
        self.__qual = qual
        self.dl_path = path
        self.__total_time = None
        self.out_path = ospath.join("encode", name)
        self.__prog_file = 'prog.txt'
        self.__start_time = time()
        self.is_master = is_master
        self.sub_path = sub_path
        self.poster_url = poster_url

    async def progress(self):
        self.__total_time = await mediainfo(self.dl_path, get_duration=True)
        if isinstance(self.__total_time, str):
            try:
                self.__total_time = float(self.__total_time)
            except Exception:
                self.__total_time = 1.0
        if not self.__total_time or self.__total_time <= 0:
            self.__total_time = 1.0

        while not (self.__proc is None or self.is_cancelled):
            try:
                async with aiopen(self.__prog_file, 'r') as p:
                    text = await p.read()
            except FileNotFoundError:
                text = ""
            except Exception:
                text = ""

            if text:
                t = findall(r"out_time_ms=(\d+)", text)
                time_done = floor(int(t[-1]) / 1000000) if t else 1

                s = findall(r"total_size=(\d+)", text)
                ensize = int(s[-1]) if s else 0

                diff = time() - self.__start_time
                speed = ensize / max(diff, 0.01)
                percent = round((time_done / max(self.__total_time, 1.0)) * 100, 2)
                tsize = ensize / (max(percent, 0.01) / 100)
                eta = (tsize - ensize) / max(speed, 0.01)

                bar = floor(percent / 8) * "■" + (12 - floor(percent / 8)) * "□"

                from .auto_animes import stylize_quote
                formatted_name = f"“{self.__name.strip()}”"

                progress_str = f"""> ᴀɴɪᴍᴇ ɴᴀᴍᴇ : {stylize_quote(formatted_name)}

<blockquote>‣ <b>Status :</b> <b>Encoding</b>
    <code>[{bar}]</code> {percent}%
   ‣ <b>Size :</b> {convertBytes(ensize)} out of ~ {convertBytes(tsize)}
    ‣ <b>Speed :</b> {convertBytes(speed)}/s
    ‣ <b>Time Took :</b> {convertTime(diff)}
    ‣ <b>Time Left :</b> {convertTime(eta)}
‣ <b>File(s) Encoded:</b> <code>{Var.QUALS.index(self.__qual)} / {len(Var.QUALS)}</code></blockquote>"""
                try:
                    await editMessage(self.message, progress_str)
                except Exception:
                    pass

                prog = findall(r"progress=(\w+)", text)
                if prog and prog[-1] == 'end':
                    break

            await asleep(8)

    async def download_watermark(self, url: str) -> str | None:
        try:
            if not url:
                return None

            parsed = urlparse(url)
            filename = unquote(pathlib.Path(parsed.path).name) or "watermark_raw"
            filename = filename.replace("/", "_").replace("\\", "_")
            local_path = ospath.join("encode", filename)
            valid_wm_path = ospath.join("encode", "valid_watermark.png")

            # 🚀 SMART DOWNLOADER: Web Link ya Telegram File ID
            if url.startswith("http://") or url.startswith("https://"):
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            LOGS.warning(f"Failed to download watermark {url} status {resp.status}")
                            return None
                        async with aiopen(local_path, 'wb') as f:
                            async for chunk in resp.content.iter_chunked(1024 * 32):
                                if not chunk:
                                    break
                                await f.write(chunk)
            else:
                from bot import bot
                await bot.download_media(url, file_name=local_path)

            # 🔥 VERIFY IMAGE & REMOVE SOLID BACKGROUND (White/Black)
            if ospath.exists(local_path) and ospath.getsize(local_path) > 0:
                from PIL import Image
                try:
                    img = Image.open(local_path).convert("RGBA")
                    data = img.getdata()

                    newData = []
                    for item in data:
                        if item[0] > 240 and item[1] > 240 and item[2] > 240:
                            newData.append((255, 255, 255, 0)) # Transparent
                        elif item[0] < 15 and item[1] < 15 and item[2] < 15:
                            newData.append((0, 0, 0, 0)) # Transparent
                        else:
                            newData.append(item)

                    img.putdata(newData)
                    img.save(valid_wm_path, format="PNG")
                    await aioremove(local_path)
                    return valid_wm_path
                except Exception as e:
                    LOGS.error(f"Invalid watermark image downloaded: {e}")
                    await aioremove(local_path)
                    return None
            return None
        except Exception:
            LOGS.exception("Error downloading watermark")
            return None

    async def start_encode(self):
        try:
            if ospath.exists(self.__prog_file):
                await aioremove(self.__prog_file)
            async with aiopen(self.__prog_file, 'w') as _:
                pass
        except Exception:
            pass

        dl_npath = ospath.join("encode", "ffanimeadvin.mkv")
        out_npath = ospath.join("encode", "ffanimeadvout.mp4") 

        if ospath.isdir(self.dl_path):
            files = glob.glob(ospath.join(self.dl_path, "*.mkv")) + glob.glob(ospath.join(self.dl_path, "*.mp4"))
            if not files:
                raise FileNotFoundError(f"No video file found inside directory: {self.dl_path}")
            video_file = files[0]
        else:
            video_file = self.dl_path

        try:
            if not self.is_master:
                import shutil
                shutil.copy2(video_file, dl_npath)
            else:
                await aiorename(video_file, dl_npath)
        except Exception:
            try:
                import shutil
                shutil.copy2(video_file, dl_npath)
            except Exception:
                raise

        watermark = None
        try:
            wm = await db.get_watermark()
            if wm:
                local_wm = await self.download_watermark(wm)
                watermark = local_wm if local_wm else None
            
            if not watermark:
                local_fallback = ospath.join("bot", "utils", "watermark.png")
                if ospath.exists(local_fallback):
                    watermark = local_fallback
        except Exception:
            watermark = None

        ffcode = f"ffmpeg -hide_banner -loglevel error -progress '{self.__prog_file}' -y -i '{dl_npath}'"

        if self.is_master:
            subtitle_filter = ""
            if self.sub_path and ospath.exists(self.sub_path):
                fontsdir = ospath.abspath(ospath.join("bot", "utils"))
                import time as t
                import re
                
                temp_sub_path = ospath.join("encode", f"temp_sub_{t.time()}.ass")
                
                # 🔥 FOOLPROOF RESOLUTION OVERRIDE LOGIC
                # Ye original subtitle file ki script info ko force karke 1080p scale par fix kar dega.
                with open(self.sub_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    ass_content = f.read()
                
                if 'PlayResY:' in ass_content:
                    ass_content = re.sub(r'PlayResX:\s*\d+', 'PlayResX: 1920', ass_content)
                    ass_content = re.sub(r'PlayResY:\s*\d+', 'PlayResY: 1080', ass_content)
                else:
                    ass_content = ass_content.replace('[Script Info]', '[Script Info]\nPlayResX: 1920\nPlayResY: 1080')
                
                with open(temp_sub_path, 'w', encoding='utf-8') as f:
                    f.write(ass_content)

                # Ab humara base resolution 1080p lock ho gaya hai, toh hum Size ko 58 pe set kar sakte hain
                # Bold=1 se text thick hoga, MarginV=45 se text border se thoda upar readable position par aayega
                force_style = "FontName=AHS BestFont,FontSize=58,PrimaryColour=&H00FFFFFF,OutlineColour=&H4D000000,ShadowColour=&H4D000000,BackColour=&H80000000,Bold=1,Italic=0,Outline=2,Shadow=1,BorderStyle=1,MarginV=45,Alignment=2,WrapStyle=1"
                
                subtitle_filter = f"subtitles='{temp_sub_path}':fontsdir='{fontsdir}':force_style='{force_style}'"

            if watermark and ospath.exists(watermark):
                ffcode += f" -i '{watermark}'"
                if subtitle_filter:
                    filter_str = f"[1:v]scale=150:-1[wm];[0:v][wm]overlay=20:20[ovr];[ovr]{subtitle_filter}[out_v]"
                else:
                    filter_str = f"[1:v]scale=150:-1[wm];[0:v][wm]overlay=20:20[out_v]"
                
                ffcode += f" -filter_complex \"{filter_str}\" -map \"[out_v]\" -map 0:a -sn -map_metadata -1"
            else:
                if subtitle_filter:
                    ffcode += f" -vf \"{subtitle_filter}\" -map 0:v -map 0:a -sn -map_metadata -1"
                else:
                    ffcode += " -map 0:v -map 0:a -sn -map_metadata -1"
            
            ffcode += f" {ffargs[self.__qual]} "
        else:
            target_height = "720" if self.__qual == "720" else "480" if self.__qual == "480" else None
            if target_height:
                ffcode += f" -vf 'scale=-2:{target_height}:flags=fast_bilinear' -map 0:v -map 0:a -sn -map_metadata -1"
                ffcode += f" {ffargs[self.__qual]} "
            else:
                ffcode += " -map 0:v -map 0:a -sn -map_metadata -1"
                ffcode += f" {ffargs[self.__qual]} "

        ffcode += (
            " -metadata title='By HellFire_Academy' "
            "-metadata author='By HellFire_Academy' "
            "-metadata:s:a title='By HellFire_Academy' "
            "-metadata:s:v title='By HellFire_Academy' "
        )

        ffcode += f" '{out_npath}'"

        LOGS.info(f'FFCode: {ffcode}')

        try:
            self.__proc = await create_subprocess_shell(ffcode)
        except Exception:
            try:
                await aiorename(dl_npath, self.dl_path)
            except Exception:
                pass
            raise

        proc_pid = self.__proc.pid
        try:
            ffpids_cache.append(proc_pid)
        except Exception:
            pass

        try:
            _, return_code = await gather(create_task(self.progress()), self.__proc.wait())
        finally:
            try:
                if proc_pid in ffpids_cache:
                    ffpids_cache.remove(proc_pid)
            except Exception:
                pass

        try:
            if not self.is_master:
                await aioremove(dl_npath)
            else:
                await aiorename(dl_npath, self.dl_path)
        except Exception:
            pass

        if self.is_cancelled:
            return

        if return_code == 0 and ospath.exists(out_npath):
            try:
                await aiorename(out_npath, self.out_path)
            except Exception:
                try:
                    import shutil
                    shutil.copy2(out_npath, self.out_path)
                except Exception:
                    return None
            return self.out_path
        else:
            return None

    async def cancel_encode(self):
        self.is_cancelled = True
        if self.__proc is not None:
            try:
                self.__proc.kill()
            except Exception:
                pass
