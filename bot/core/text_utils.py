from calendar import month_name
from datetime import datetime, timedelta
from random import choice
from asyncio import sleep as asleep
from aiohttp import ClientSession
from anitopy import parse
import re
from bot import Var, bot
from .ffencoder import ffargs
from .func_utils import handle_logs
from .reporter import rep
from .database import db

def stylize_quote(text: str) -> str:
    """Stylize text into Unicode small caps + digits for dramatic effect."""
    fancy_map = str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-",
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"
        "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿−"
    )
    return text.translate(fancy_map)


CAPTION_FORMAT = """
<blockquote><b>» {title}</b></blockquote>
<b>━━━━━━━━━━━━━━━━━━━</b>
<b>➥ 𝐒ᴇᴀsᴏɴ: {season_number}
<b>➤ 𝐄ᴘɪsᴏᴅᴇ {ep_no}</b>
<b>➤ 𝐐ᴜᴀʟɪᴛʏ: 480ᴘ | 720ᴘ | 1080ᴘ</b>
<b>➥ 𝐀ᴜᴅɪᴏ: {lang_info}</b>
<b>━━━━━━━━━━━━━━━━━━━</b>
<blockquote><b>» ᴘᴏᴡᴇʀᴇᴅ ʙʏ <a href='https://t.me/HellFire_Academy_Official'>𝐀ɴɪᴍᴇ 𝐇ᴇʟʟғɪʀᴇ</a></b></blockquote>
"""


GENRES_EMOJI = {
    "Action": "👊",
    "Adventure": choice(['🪂', '🧗‍♀']),
    "Comedy": "🤣",
    "Drama": " 🎭",
    "Ecchi": choice(['💋', '🥵']),
    "Fantasy": choice(['🧞', '🧞‍♂', '🧞‍♀','🌗']),
    "Hentai": "🔞",
    "Horror": "☠",
    "Mahou Shoujo": "☯",
    "Mecha": "🤖",
    "Music": "🎸",
    "Mystery": "🔮",
    "Psychological": "♟",
    "Romance": "💞",
    "Sci-Fi": "🛸",
    "Slice of Life": choice(['☘','🍁']),
    "Sports": "⚽️",
    "Supernatural": "🫧",
    "Thriller": choice(['🥶', '🔪','🤯'])
}

SEASON_EMOJI = {
    "WINTER": "❄️",
    "SPRING": "🌸",
    "SUMMER": "☀️",
    "FALL": "🍂",
    "AUTUMN": "🍁"  # Sometimes AniList uses this
}


ANIME_GRAPHQL_QUERY = """
query ($id: Int, $search: String, $seasonYear: Int) {
  Media(id: $id, type: ANIME, format_not_in: [MOVIE, MUSIC, MANGA, NOVEL, ONE_SHOT], search: $search, seasonYear: $seasonYear) {
    id
    idMal
    title {
      romaji
      english
      native
    }
    type
    format
    status(version: 2)
    description(asHtml: false)
    startDate {
      year
      month
      day
    }
    endDate {
      year
      month
      day
    }
    season
    seasonYear
    episodes
    duration
    chapters
    volumes
    countryOfOrigin
    source
    hashtag
    trailer {
      id
      site
      thumbnail
    }
    updatedAt
    coverImage {
      large
    }
    bannerImage
    genres
    synonyms
    averageScore
    meanScore
    popularity
    trending
    favourites
    studios {
      nodes {
         name
         siteUrl
      }
    }
    isAdult
    nextAiringEpisode {
      airingAt
      timeUntilAiring
      episode
    }
    airingSchedule {
      edges {
        node {
          airingAt
          timeUntilAiring
          episode
        }
      }
    }
    externalLinks {
      url
      site
    }
    siteUrl
  }
}
"""


class AniLister:
    def __init__(self, anime_name: str, year: int) -> None:
        self.__api = "https://graphql.anilist.co"
        self.__ani_name = anime_name
        self.__ani_year = year
        self.__vars = { "search": self.__ani_name }  # No year filter
        #self.__vars = {'search': self.__ani_name, 'seasonYear': self.__ani_year}

    def get_episode(self):
        return self.pdata.get("episode_number")

    def get_season(self):
        return self.pdata.get("anime_season")

    def get_audio(self):
        return self.pdata.get("audio")

    def __update_vars(self, year: bool = True) -> None:
        """Update GraphQL variables either by reducing year or removing year constraint."""
        if year:
            self.__ani_year -= 1
            self.__vars['seasonYear'] = self.__ani_year
        else:
            self.__vars = {'search': self.__ani_name}

    async def post_data(self):
        """Post GraphQL query to AniList API and return response details."""
        async with ClientSession() as sess:
            async with sess.post(self.__api, json={'query': ANIME_GRAPHQL_QUERY, 'variables': self.__vars}) as resp:
                return (resp.status, await resp.json(), resp.headers)

    async def get_anidata(self):
        """Fetch anime data with retries on 404, 429, and server errors."""
        try:
            res_code, resp_json, res_heads = await self.post_data()

            # Retry by reducing year until 2020
            while res_code == 404 and self.__ani_year > 2020:
                self.__update_vars()
                await rep.report(f"AniList Query Name: {self.__ani_name}, Retrying with {self.__ani_year}", "warning", log=False)
                res_code, resp_json, res_heads = await self.post_data()

            # If still 404, try without the year filter
            if res_code == 404:
                self.__update_vars(year=False)
                res_code, resp_json, res_heads = await self.post_data()

            if res_code == 200:
                return resp_json.get('data', {}).get('Media', {}) or {}

            elif res_code == 429:
                # Too many requests — trigger Jikan fallback directly
                await rep.report(f"AniList API Rate Limit (429). Falling back to Jikan API.", "warning", log=False)
                return await self.fetch_jikan_fallback()

            elif res_code in [500, 501, 502]:
                # Server-side error — wait and retry once
                await rep.report(f"AniList Server Error: {res_code}. Falling back to Jikan API.", "warning", log=False)
                return await self.fetch_jikan_fallback()

            # Other errors — log and try Jikan API fallback
            await rep.report(f"AniList API Error: {res_code}. Falling back to Jikan API.", "warning", log=False)
            return await self.fetch_jikan_fallback()
        except Exception as e:
            await rep.report(f"AniList Exception: {e}. Falling back to Jikan API.", "error", log=False)
            return await self.fetch_jikan_fallback()

    async def fetch_jikan_fallback(self):
        """Fetch fallback data from Jikan API when AniList fails."""
        try:
            import urllib.parse
            url_name = urllib.parse.quote(self.__ani_name)
            url = f"https://api.jikan.moe/v4/anime?q={url_name}&limit=1"
            async with ClientSession() as sess:
                async with sess.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("data") and len(data["data"]) > 0:
                            anime = data["data"][0]
                            # Map Jikan data to AniList format structure
                            genres_mapped = [g.get("name") for g in anime.get("genres", [])] if anime.get("genres") else []

                            return {
                                "id": anime.get("mal_id"),
                                "title": {
                                    "english": anime.get("title_english"),
                                    "romaji": anime.get("title"),
                                    "native": anime.get("title_japanese")
                                },
                                "description": anime.get("synopsis"),
                                "status": anime.get("status"),
                                "episodes": anime.get("episodes"),
                                "averageScore": int(anime.get("score") * 10) if anime.get("score") else None,
                                "genres": genres_mapped,
                                "season": anime.get("season"),
                                "seasonYear": anime.get("year"),
                                "format": anime.get("type"),
                                "is_jikan_fallback": True, # Marker to use custom image logic
                                "coverImage": {
                                    "large": anime.get("images", {}).get("jpg", {}).get("large_image_url")
                                }
                            }
        except Exception as e:
            await rep.report(f"Jikan Fallback Error: {e}", "error", log=False)

        # Absolute fallback to prevent crash
        return {}

class TextEditor:
    def __init__(self, name):
        self.__name = name
        self.adata = {}
        self.pdata = parse(name)

    async def load_anilist(self):
        cache_names = []
        for option in [(False, False), (False, True), (True, False), (True, True)]:
            ani_name = await self.parse_name(*option)
            if ani_name in cache_names:
                continue
            cache_names.append(ani_name)
            self.adata = await AniLister(ani_name, datetime.now().year).get_anidata()
            if self.adata:
                break

    async def extract_metadata(self, filename: str):
        filename = filename.lower()

        # Extract episode number
        ep_match = re.search(r'(?:ep?|episode)[\s._-]*?(\d{1,3})', filename)
        episode = ep_match.group(1) if ep_match else "01"

        # Extract quality
        quality_match = re.search(r'(360p|480p|720p|1080p|2160p)', filename)
        quality = quality_match.group(1) if quality_match else "720p"

        # Extract audio type
        if "dual" in filename:
            audio = "DUAL"
        elif "multi" in filename:
            audio = "MULTI"
        elif "eng" in filename and "jap" in filename:
            audio = "DUAL"
        elif "japanese" in filename or "sub" in filename:
            audio = "SUB"
        else:
            audio = "SUB"

        # Extract season
        season_match = re.search(r'(?:s|season)[\s._-]*(\d{1,2})', filename)
        season = season_match.group(1).zfill(2) if season_match else "01"

        # Save to self.pdata
        self.pdata = {
            "episode": episode,
            "quality": quality,
            "audio": audio,
            "season": season
        }

    @handle_logs
    async def parse_name(self, no_s=False, no_y=False):
        anime_name = self.pdata.get("anime_title")
        anime_season = self.pdata.get("anime_season")
        anime_year = self.pdata.get("anime_year")
        if anime_name:
            pname = anime_name
            if not no_s and self.pdata.get("episode_number") and anime_season:
                pname += f" {anime_season}"
            if not no_y and anime_year:
                pname += f" {anime_year}"
            return pname
        return anime_name

    @handle_logs
    async def get_id(self):
        if (ani_id := self.adata.get('id')) and str(ani_id).isdigit():
            return ani_id

    @handle_logs
    async def get_poster(self):
        # Prefer Jikan cover if it fell back to Jikan
        if self.adata.get("is_jikan_fallback"):
            jikan_cover = self.adata.get("coverImage", {}).get("large")
            if jikan_cover:
                return jikan_cover

        if anime_id := await self.get_id():
            return f"https://img.anili.st/media/{anime_id}"
        return "https://i.ibb.co/WvV8cmGc/photo-2025-05-06-02-54-16-7520721484596117512.jpg"


    
    @handle_logs
    async def get_upname(self, qual=""):
        anime_name = self.pdata.get("anime_title")
        codec = (
            'HEVC' if 'libx266' in ffargs.get(qual, '')
            else 'AV1' if 'libaom-av1' in ffargs.get(qual, '')
            else ''
        )

        # ✅ Try custom rename first
        custom_name = await db.get_custom_rename(anime_name)
        if custom_name:
            await db.remove_custom_rename(anime_name)
            return custom_name.replace("{QUAL}", qual).strip()

        filename = self.__name
        filename_lower = filename.lower()
        tags = " ".join(re.findall(r'\((.*?)\)', filename)).lower()

        # Detect language tags
        lang = (
            "DUAL" if "dual" in filename_lower or "dual" in tags
            else "MULTI" if "multi" in filename_lower or "multi" in tags
            else "SUB"
        )

        print("Original filename:", filename)
        print("Extracted tags:", tags)
        print("Detected language:", lang)

        ep_number = self.pdata.get("episode_number")
        anime_season = self.pdata.get('anime_season', '01')

        if isinstance(anime_season, list):
            anime_season = anime_season[-1] if anime_season else '01'
        anime_season = str(anime_season).zfill(2)

        # If AniList didn’t provide ep_number
        if not ep_number:
            m = re.search(r"[Ss](\d+)[Ee](\d+)", filename)
            if m:
                anime_season, ep_number = m.group(1).zfill(2), m.group(2).zfill(2)
            else:
                ep_number = "01"

        if anime_name and ep_number:
            titles = self.adata.get('title', {})
            raw_title = (
                titles.get('english')
                or titles.get('romaji')
                or titles.get('native')
                or anime_name
            )
        else:
            # fallback
            raw_title = re.sub(r"\.(?=[^.]*$)", " ", ospath.splitext(ospath.basename(filename))[0])  # remove last dot before ext
            raw_title = raw_title.replace(".", " ")
            raw_title = re.sub(r"S\d+E\d+", "", raw_title, flags=re.IGNORECASE)  # strip SxxEyy
            raw_title = re.sub(r"\s+", " ", raw_title).strip()

       
        phrases_to_remove = ["season", "part", "arc", "movie", "series", "edition", "chapter"]
        for phrase in phrases_to_remove:
            raw_title = re.sub(fr"\s*{phrase}\s*\d*\s*", " ", raw_title, flags=re.IGNORECASE)

        # Abbreviation mapping
        abbr_map = {
            "chronicles": "Chrons",
            "adventure": "Adv",
            "unlimited": "Unlim",
            "the": "",
            "and": "&"
        }
        for word, abbr in abbr_map.items():
            raw_title = re.sub(fr"\b{word}\b", abbr, raw_title, flags=re.IGNORECASE)

        processed_title = raw_title.strip()
        if len(processed_title) > 40:
            cut = processed_title[:40]
            last_space = cut.rfind(' ')
            processed_title = cut[:last_space] if last_space != -1 else cut

        return (
            f"[𝐀ɴɪᴍᴇ 𝐇ᴇʟʟғɪʀᴇ] [S-{anime_season}] [EP-{str(ep_number).zfill(2)}] {processed_title} [{qual}p] Hindi Subbed.mp4"
        )

    @handle_logs
    async def get_caption(self):

        # existing caption logic, but use name_to_use for episode/audio parsing
        sd = self.adata.get('startDate', {})
        season_number = self.pdata.get("anime_season") or "1"
        if isinstance(season_number, list):
            season_number = season_number[-1] if season_number else "1"
        season_number = str(season_number).zfill(2)

        filename = self.__name
        filename_lower = filename.lower()
        tags = " ".join(re.findall(r'\((.*?)\)', filename)).lower()

        lang = (
            "DUAL" if "dual" in filename_lower or "dual" in tags
            else "MULTI" if "multi" in filename_lower or "multi" in tags
            else "SUB"
        )

        print("Original filename:", filename)
        print("Extracted tags:", tags)
        print("Detected language:", lang)

        lang_info = {
            "DUAL": "DUAL[ENG+JAP]",
            "MULTI": "Japanese [E-Sub]",
            "SUB": "Japanese [E-Sub]"
        }.get(lang, "Japanese [E-Sub]")

        next_ep = self.adata.get("nextAiringEpisode")
        season_raw = self.adata.get("season")
        season_year = self.adata.get("seasonYear")

        if season_raw and season_year:
            season_name = season_raw.upper()
            season_emoji = SEASON_EMOJI.get(season_name, "📅")
            seasonal_line = f"{season_emoji} {season_name.title()} {season_year}"
        else:
            seasonal_line = "📅 Not Listed"

        if next_ep:
            airing_unix = next_ep.get("airingAt")
            ep_no_next = next_ep.get("episode")
            airing_date = datetime.utcfromtimestamp(airing_unix).strftime("%d %B %Y")
            next_airing_info = (
                f"ᴇᴘɪꜱᴏᴅᴇ {str(ep_no_next).zfill(2)} Wɪʟʟ ʀᴇʟᴇᴀꜱᴇ ᴏɴ {airing_date} "
                f"ᴀʀᴏᴜɴᴅ ᴛʜᴇ ꜱᴀᴍᴇ ᴛɪᴍᴇ ᴀꜱ ᴛᴏᴅᴀʏ'ꜱ ᴇᴘɪꜱᴏᴅᴇ ᴀɴᴅ ᴡɪʟʟ ʙᴇ ᴜᴘʟᴏᴀᴅᴇᴅ ꜰɪʀꜱᴛ ᴏɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ"
            )
        else:
            fake_next_date = (datetime.utcnow() + timedelta(days=7)).strftime("%d %B %Y")
            fake_ep_no = str(int(self.pdata.get("episode_number", 0)) + 1).zfill(2)
            next_airing_info = (
        f"ᴇᴘɪꜱᴏᴅᴇ {fake_ep_no} Wɪʟʟ ʀᴇʟᴇᴀꜱᴇ ᴏɴ {fake_next_date} "
        f"ᴀʀᴏᴜɴᴅ ᴛʜᴇ ꜱᴀᴍᴇ ᴛɪᴍᴇ ᴀꜱ ᴛᴏᴅᴀʏ'ꜱ ᴇᴘɪꜱᴏᴅᴇ ᴀɴᴅ ᴡɪʟʟ ʙᴇ ᴜᴘʟᴏᴀᴅᴇᴅ ꜰɪʀꜱᴛ ᴏɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ"
    )

        startdate = f"{month_name[sd['month']]} {sd['day']}, {sd['year']}" if sd.get('day') and sd.get('year') else ""
        ed = self.adata.get('endDate', {})
        enddate = f"{month_name[ed['month']]} {ed['day']}, {ed['year']}" if ed.get('day') and ed.get('year') else ""

        titles = self.adata.get("title", {})

        return CAPTION_FORMAT.format(
            title=titles.get('english') or titles.get('romaji') or titles.get('native'),
            form=self.adata.get("format") or "N/A",
            genres=", ".join(x for x in (self.adata.get('genres') or [])),
            avg_score=f"{sc}%" if (sc := self.adata.get('averageScore')) else "N/A",
            status=self.adata.get("status") or "N/A",
            start_date=startdate or "N/A",
            end_date=enddate or "N/A",
            season_number=season_number,
            t_eps=self.adata.get("episodes") or "N/A",
            lang_info=lang_info,
            seasonal_line=seasonal_line,
            next_airing_info=next_airing_info,
            plot=(desc if (desc := self.adata.get("description") or "N/A") and len(desc) < 200 else desc[:200] + "..."),
            ep_no=self.pdata.get("episode_number"),
            cred=Var.BRAND_UNAME,
        )
