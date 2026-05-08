import libtorrent as lt
import aiohttp
import asyncio
import os

async def get_torrent_info(torrent_url):
    ses = lt.session()
    ses.listen_on(6881, 6891)

    if torrent_url.startswith("magnet:"):
        params = {
            'save_path': ".",
            'storage_mode': lt.storage_mode_t.storage_mode_sparse,
        }
        handle = lt.add_magnet_uri(ses, torrent_url, params)

        print("Fetching metadata from magnet...")
        while not handle.has_metadata():
            await asyncio.sleep(1)

        info = handle.get_torrent_info()

    else:
        # Download the .torrent file temporarily
        async with aiohttp.ClientSession() as session:
            async with session.get(torrent_url) as resp:
                if resp.status != 200:
                    raise ValueError(f"Failed to fetch torrent file: {resp.status}")
                data = await resp.read()

        # Save temp file
        temp_path = "temp.torrent"
        with open(temp_path, "wb") as f:
            f.write(data)

        info = lt.torrent_info(temp_path)
        os.remove(temp_path)

    name = info.name()
    size_bytes = sum([f.size for f in info.files()])
    size_gb = f"{size_bytes / (1024**3):.2f} GB"

    return {
        "name": name,
        "size": size_gb
    }
