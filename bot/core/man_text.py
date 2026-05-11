from calendar import month_name
from datetime import datetime
from random import choice
from asyncio import sleep as asleep
from aiohttp import ClientSession
from anitopy import parse
from os import path as ospath

from bot import Var, bot
from .func_utils import handle_logs
from .reporter import rep

CAPTION_FORMAT = """
<b><i><blockquote>➥ {anime_title} </blockquote></i></b>

<b>   ➢ Episode: {ep_no}</b>
<b>   ➢ Quality: 480p | 720p | 1080p | HDRip</b>  
<b>   ➥ Audio : {lang} </b> 
"""

GENRES_EMOJI = {"Action": "👊", "Adventure": choice(['🪂', '🧗‍♀']), "Comedy": "🤣", "Drama": " 🎭", "Ecchi": choice(['💋', '🥵']), "Fantasy": choice(['🧞', '🧞‍♂', '🧞‍♀','🌗']), "Hentai": "🔞", "Horror": "☠", "Mahou Shoujo": "☯", "Mecha": "🤖", "Music": "🎸", "Mystery": "🔮", "Psychological": "♟", "Romance": "💞", "Sci-Fi": "🛸", "Slice of Life": choice(['☘','🍁']), "Sports": "⚽️", "Supernatural": "🫧", "Thriller": choice(['🥶', '🔪','🤯'])}

ANIME_GRAPHQL_QUERY = """
query ($id: Int, $search: String, $seasonYear: Int) {
  Media(id: $id, type: ANIME, format_not_in: [MOVIE, MUSIC, MANGA, NOVEL, ONE_SHOT], search: $search, seasonYear: $seasonYear) {
    id
    title { romaji english native }
    status
    startDate { year month day }
    endDate { year month day }
    seasonYear
    episodes
    genres
    averageScore
    coverImage { large }
  }
}
"""

class AniLuster:
    def __init__(self, anime_name: str, year: int) -> None:
        self.__api = "https://graphql.anilist.co"
        self.__vars = {'search': anime_name, 'seasonYear': year}

    async def post_data(self):
        async with ClientSession() as sess:
            async with sess.post(self.__api, json={'query': ANIME_GRAPHQL_QUERY, 'variables': self.__vars}) as resp:
                return resp.status, await resp.json()

    async def get_anidata(self):
        res_code, resp_json = await self.post_data()
        if res_code == 200:
            return resp_json.get('data', {}).get('Media', {})
        return {}

class TestEditor:
    def __init__(self, name):
        self.__name = name
        self.adata = {}
        self.pdata = parse(name)

    async def load_anilist(self):
        ani_name = await self.parse_name()
        self.adata = await AniLister(ani_name, datetime.now().year).get_anidata()

    async def parse_name(self):
        anime_name = self.pdata.get("anime_title")
        return anime_name or self.__name

    async def get_postere(self):
        return self.adata.get('coverImage', {}).get('large') or     "https://graph.org/file/a2d9108db5a307e569125-b4564a4d5e8875f52b.jpg"

    async def get_captione(self):
        startdate = self.adata.get('startDate', {})
        formatted_start = f"{month_name[startdate.get('month', 1)]} {startdate.get('day', 1)}, {startdate.get('year', 'N/A')}"
        genres = ", ".join(f"{GENRES_EMOJI.get(x, '#')} #{x.replace(' ', '_')}" for x in (self.adata.get('genres') or []))

        return CAPTION_FORMAT.format(
            title=self.adata.get('title', {}).get('english') or self.adata.get('title', {}).get('romaji'),
            genres=genres,
            status=self.adata.get("status", "N/A"),
            ep_no=self.pdata.get("episode_number"),
            cred=Var.BRAND_UNAME,
        )

    async def get_upname(self, qual=""):
        anime_name = self.pdata.get("anime_title")
        codec = 'HEVC' if 'libx265' in ffargs.get(qual, '') else 'AV1' if 'libaom-av1' in ffargs.get(qual, '') else ''
        original_filename = self.pdata.get("original_filename", "").lower()
        lang = next((x for x in ["DUAL", "MULTI"] if f"{x.lower()}-audio" in original_filename), "SUB")
        episode_number = self.pdata.get("episode_number")
        season = self.pdata.get('anime_season', '01')

        if anime_name and episode_number:
            return f"[{anime_name} - {episode_number}] ({qual}p) [{codec}] [{lang}] @HellFire_Academy_Official.mkv"

# Encoding & Upload Process
async def encode_and_upload(dl_path, quality, message):
    # Fetch optional watermark
    watermark = await db.get_watermark()
    
    # Fetch thumbnail
    thumbnail = await db.get_thumbnail()
    if thumbnail and thumbnail.startswith(("http://", "https://")):
        thumbnail = await download_thumbnail(thumbnail)
    if not thumbnail:
        thumbnail = "thumb.jpg" if ospath.exists("thumb.jpg") else None

    # Set up text editor for anime metadata
    text = TextEditor(dl_path)
    await text.load_anilist()

    # Encoding Process
    await message.edit_text("Encoding in progress...")
    encoded_file = f"{dl_path}.encoded.mkv"
    encode_cmd = ["ffmpeg", "-i", dl_path, "-c:v", "libx265", "-crf", "24"]
    if watermark:
        encode_cmd.extend(["-vf", f"drawtext=text='{watermark}':x=10:y=10:fontsize=24:fontcolor=white"])
    encode_cmd.append(encoded_file)

    process = await asyncio.create_subprocess_exec(*encode_cmd)
    await process.communicate()

    # Uploading
    # ✅ Get main channel from DB
    main_channel = await db.get_main_channel() or Var.MAIN_CHANNEL
    caption = await text.get_caption()
    upname = await text.get_upname(quality)
    await bot.send_document(
        chat_id=main_channel,
        document=encoded_file,
        caption=caption,
        thumb=thumbnail,
    )

    await message.edit_text("Upload complete!")
