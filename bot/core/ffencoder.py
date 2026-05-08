# file: encode/ffencoder.py
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

# Encoding args
ffargs = {
    '1080': (
        "-c:v libx264 -preset veryfast -crf 24 "
        "-pix_fmt yuv420p -movflags +faststart "
        "-c:a libopus -b:a 96k -vbr on -c:s copy"
    ),
    '720': (
        "-c:v libx264 -preset veryfast -crf 28 "
        "-pix_fmt yuv420p -movflags +faststart "
        "-c:a libopus -b:a 80k -vbr on -c:s copy"
    ),
    '480': (
        "-c:v libx264 -preset veryfast -crf 32 "
        "-pix_fmt yuv420p -movflags +faststart "
        "-c:a libopus -b:a 64k -vbr on -c:s copy"
    ),
    'HDRi': "-c copy"
}

# Scaling values (used only when no watermark is applied)
scale_values = {
    '1080': "scale=1920:1080",
    '720': "scale=1280:720",
    '480': "scale=854:480",
    'HDRi': None
}

if not ospath.exists("encode"):
    makedirs("encode", exist_ok=True)


class FFEncoder:
    def __init__(self, message, path, name, qual):
        # why: keep state
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

    async def progress(self):
        # why: report progress using ffmpeg -progress output
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
                LOGS.exception("Error reading progress file")
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

                progress_str = f"""<blockquote>‣ <b>Anime Name :</b> <b><i>{self.__name}</i></b></blockquote>

<blockquote>‣ <b>Status :</b> <i>Encoding</i>
    <code>[{bar}]</code> {percent}%</blockquote>
<blockquote>   ‣ <b>Size :</b> {convertBytes(ensize)} out of ~ {convertBytes(tsize)}
    ‣ <b>Speed :</b> {convertBytes(speed)}/s
    ‣ <b>Time Took :</b> {convertTime(diff)}
    ‣ <b>Time Left :</b> {convertTime(eta)}</blockquote>
<blockquote>‣ <b>File(s) Encoded:</b> <code>{Var.QUALS.index(self.__qual)} / {len(Var.QUALS)}</code></blockquote>"""
                try:
                    await editMessage(self.message, progress_str)
                except Exception:
                    LOGS.exception("Failed to update progress message")

                prog = findall(r"progress=(\w+)", text)
                if prog and prog[-1] == 'end':
                    break

            await asleep(8)

    async def download_watermark(self, url: str) -> str | None:
        try:
            if not url:
                return None

            parsed = urlparse(url)
            filename = unquote(pathlib.Path(parsed.path).name) or "watermark"
            filename = filename.replace("/", "_").replace("\\", "_")
            local_path = ospath.join("encode", filename)

            if ospath.exists(local_path):
                LOGS.info(f"Using cached watermark: {local_path}")
                return local_path

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
            LOGS.info(f"Watermark downloaded to: {local_path}")
            return local_path
        except Exception:
            LOGS.exception("Error downloading watermark")
            return None

    async def start_encode(self):
        # prepare progress file
        try:
            if ospath.exists(self.__prog_file):
                await aioremove(self.__prog_file)
            async with aiopen(self.__prog_file, 'w') as _:
                LOGS.info("Progress Temp Generated!")
        except Exception:
            LOGS.exception("Could not create progress file")

        dl_npath = ospath.join("encode", "ffanimeadvin.mkv")
        out_npath = ospath.join("encode", "ffanimeadvout.mkv")

        # handle directory input
        if ospath.isdir(self.dl_path):
            files = glob.glob(ospath.join(self.dl_path, "*.mkv")) + glob.glob(ospath.join(self.dl_path, "*.mp4"))
            if not files:
                raise FileNotFoundError(f"No video file found inside directory: {self.dl_path}")
            video_file = files[0]
        else:
            video_file = self.dl_path

        # move original to temp path for safe processing
        try:
            await aiorename(video_file, dl_npath)
        except Exception:
            # if rename failed (maybe same path), try copy fallback via shell
            try:
                subprocess.run(["cp", video_file, dl_npath], check=True)
            except Exception:
                LOGS.exception("Failed to move/copy input file")
                raise

        # HDRip/HDRi detection
        is_hdrip = any(term.lower() in (self.__name or "").lower() for term in ("hdrip", "hdri"))

        watermark = None
        if not is_hdrip:
            wm = await db.get_watermark()
            if wm and (wm.startswith("http://") or wm.startswith("https://")):
                local_wm = await self.download_watermark(wm)
                watermark = local_wm if local_wm else None

        # Build base ffmpeg command
        ffcode = f"ffmpeg -hide_banner -loglevel error -progress '{self.__prog_file}' -y -i '{dl_npath}'"

        if is_hdrip:
            # Map ALL streams from input 0 and copy to output so audio & subtitles are preserved.
            # Keep metadata additions; place map & codec before metadata/options to ensure mapping preserved.
            ffcode = (
                f"ffmpeg -hide_banner -loglevel error -progress '{self.__prog_file}' -y -i '{dl_npath}' "
                "-map 0 -c copy "
                "-metadata title='By Anime Raven' "
                "-metadata author='By Anime Raven' "
                "-metadata:s:s title='By Anime Raven' "
                "-metadata:s:a title='By Anime Raven' "
                "-metadata:s:v title='By Anime Raven' "
                f"'{out_npath}'"
            )
        else:
            # non-HDRi encoding path
            if watermark and ospath.exists(watermark):
                # second input for watermark
                ffcode += f" -i '{watermark}'"
                # scale watermark to base size then overlay full screen
                # note: [1:v] is watermark, [0:v] is base
                ffcode += (
                    " -filter_complex \"[1:v][0:v]scale2ref=w=iw:h=ih[wm][base];[base][wm]overlay=0:0\" "
                    "-map 0:a -map 0:s? -map 0:v"
                )
                # Use codec flags from ffargs (we expect ffargs to include video encoding)
                ffcode += f" {ffargs[self.__qual]} "
            elif scale_values.get(self.__qual):
                ffcode += f" -vf '{scale_values[self.__qual]}:flags=fast_bilinear' -map 0:v -map 0:a -map 0:s?"
                ffcode += f" {ffargs[self.__qual]} "
            else:
                ffcode += " -map 0:v -map 0:a -map 0:s? "
                ffcode += f" {ffargs[self.__qual]} "

            # global metadata
            ffcode += (
                "-metadata title='By Anime Raven' "
                "-metadata author='By Anime Raven' "
                "-metadata:s:s title='By Anime Raven' "
                "-metadata:s:a title='By Anime Raven' "
                "-metadata:s:v title='By Anime Raven' "
            )

            ffcode += f" '{out_npath}'"

        LOGS.info(f'FFCode: {ffcode}')

        # start process
        try:
            self.__proc = await create_subprocess_shell(ffcode, stdout=PIPE, stderr=PIPE)
        except Exception:
            LOGS.exception("Failed to start ffmpeg")
            # restore original file to its original name if possible
            try:
                await aiorename(dl_npath, self.dl_path)
            except Exception:
                LOGS.exception("Failed to restore input file after ffmpeg start failure")
            raise

        proc_pid = self.__proc.pid
        try:
            ffpids_cache.append(proc_pid)
        except Exception:
            LOGS.exception("Failed to append pid to cache")

        # run progress and wait for ffmpeg concurrently
        try:
            _, return_code = await gather(create_task(self.progress()), self.__proc.wait())
        finally:
            # ensure pid removed if present
            try:
                if proc_pid in ffpids_cache:
                    ffpids_cache.remove(proc_pid)
            except Exception:
                LOGS.exception("Failed to remove pid from cache")

        # restore original input file
        try:
            await aiorename(dl_npath, self.dl_path)
        except Exception:
            LOGS.exception("Failed to restore input file to original location")

        if self.is_cancelled:
            LOGS.info("Encoding was cancelled by user")
            return

        if return_code == 0 and ospath.exists(out_npath):
            try:
                await aiorename(out_npath, self.out_path)
            except Exception:
                LOGS.exception("Failed to move output to final path")
                # attempt copy fallback
                try:
                    subprocess.run(["cp", out_npath, self.out_path], check=True)
                except Exception:
                    LOGS.exception("Failed fallback copy of output")
                    return None
            return self.out_path
        else:
            try:
                stderr_output = (await self.__proc.stderr.read()).decode().strip()
            except Exception:
                stderr_output = "ffmpeg failed but could not read stderr"
            await rep.report(stderr_output, "error")
            LOGS.error(f"FFmpeg failed with code {return_code}: {stderr_output}")
            return None

    async def cancel_encode(self):
        self.is_cancelled = True
        if self.__proc is not None:
            try:
                self.__proc.kill()
            except Exception:
                LOGS.exception("Failed to kill ffmpeg process")