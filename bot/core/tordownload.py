import asyncio
from os import path as ospath
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, mkdir
from aiohttp import ClientSession
from torrentp import TorrentDownloader
from bot.core.func_utils import handle_logs
from bot import LOGS


class TorDownloader:
    def __init__(self, path=".", max_retries=3, retry_delay=10):
        self.__downdir = path
        self.__torpath = "torrents/"
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    @handle_logs
    async def download(self, torrent, name=None):
        """
        Download torrent (magnet or .torrent link).
        Retries automatically on failure.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                LOGS.info(f"[TorDownloader] Attempt {attempt}/{self.max_retries} → {torrent}")

                if torrent.startswith("magnet:"):
                    torp = TorrentDownloader(torrent, self.__downdir)
                    await torp.start_download()
                    dl_path = ospath.join(self.__downdir, name)
                else:
                    torfile = await self.get_torfile(torrent)
                    if not torfile:
                        raise Exception("Failed to fetch .torrent file")

                    torp = TorrentDownloader(torfile, self.__downdir)
                    await torp.start_download()
                    dl_path = ospath.join(self.__downdir, torp._torrent_info._info.name())
                    await aioremove(torfile)

                # ✅ Validate download
                if not await self._validate_download(dl_path):
                    raise Exception("Downloaded file/folder invalid or empty")

                LOGS.info(f"[TorDownloader] Download complete → {dl_path}")
                return dl_path

            except Exception as e:
                LOGS.error(f"[TorDownloader] Error on attempt {attempt}: {e}")
                if attempt < self.max_retries:
                    LOGS.info(f"[TorDownloader] Retrying in {self.retry_delay}s...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    LOGS.error("[TorDownloader] Max retries reached, download failed.")
                    return None

    @handle_logs
    async def get_torfile(self, url):
        """
        Fetch a .torrent file from a URL.
        """
        if not ospath.isdir(self.__torpath):
            await mkdir(self.__torpath)

        tor_name = url.split("/")[-1]
        des_dir = ospath.join(self.__torpath, tor_name)

        try:
            async with ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        async with aiopen(des_dir, "wb") as file:
                            async for chunk in response.content.iter_any():
                                await file.write(chunk)
                        return des_dir
        except Exception as e:
            LOGS.error(f"[TorDownloader] Failed to fetch torrent file: {e}")
        return None

    async def _validate_download(self, path):
        """
        Ensure download exists and is not empty.
        """
        if not ospath.exists(path):
            return False

        # Folder (multi-file torrent)
        if ospath.isdir(path):
            async def _has_files(p):
                for root, _, files in os.walk(p):
                    if files:
                        return True
                return False
            return await asyncio.to_thread(_has_files, path)

        # File (single torrent)
        return ospath.getsize(path) > 0