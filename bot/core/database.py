from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var
import time
import pymongo, os
import motor
import logging 
import re
from datetime import datetime

def normalize_title(title: str) -> str:
    # Lowercase
    title = title.lower()
    # Remove common suffixes (season 2, part 1, etc.)
    title = re.sub(r'\b(season|part|chapter|s|p|vol|volume)\s*\d+', '', title)
    title = re.sub(r'\b(s\d+|p\d+)\b', '', title)
    # Remove non-alphanumeric characters
    title = re.sub(r'[^a-z0-9]', '', title)
    return title.strip()



#dbclient = pymongo.MongoClient(Var.MONGO_URI)
#database = dbclient["Rohit"]


class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]
        self.channel_data = self.__db['channels']
        self.user_data = self.__db['users']

        self.auto_delete_data = self.__db['auto_delete']
        self.hide_caption_data = self.__db['hide_caption']
        self.protect_content_data = self.__db['protect_content']
        self.channel_button_data = self.__db['channel_button']

        self.del_timer_data = self.__db['del_timer']
        self.channel_button_link_data = self.__db['channelButton_link']

        self.rqst_fsub_data = self.__db['request_forcesub']
        self.rqst_fsub_Channel_data = self.__db['request_forcesub_channel']
        self.store_reqLink_data = self.__db['store_reqLink']
        self.watermark_data = self.__db['watermark']
        self.thumb_data = self.__db['thumb']
        self.banner_data = self.__db['banner']
        self.method_data = self.__db['method']
        self.main_channel_data = self.__db['main_channel']
        self.rename = self.__db['rename']
        self.tasks = self.__db['tasks']
        self.anime_channel_map = self.__db['anime_channel_map']
        self.anime_invites = self.__db['anime_invites']
        self.anime_poster_map = self.__db['anime_poster_map']
        self.shortner_data = self.__db['shortner_settings']
        self.verify_data = self.__db['user_verification']



    async def set_anime_poster(self, anime_name: str, poster_url: str):
        anime_key = normalize_title(anime_name)
        await self.anime_poster_map.update_one(
            {"_id": anime_key},
            {"$set": {"original": anime_name, "poster_url": poster_url}},
            upsert=True
        )

    async def get_anime_poster(self, anime_name: str):
        anime_key = normalize_title(anime_name)
        data = await self.anime_poster_map.find_one({"_id": anime_key})
        return data["poster_url"] if data else None

    async def del_anime_poster(self, anime_name: str):
        anime_key = normalize_title(anime_name)
        await self.anime_poster_map.delete_one({"_id": anime_key})

    async def list_all_anime_posters(self):
        docs = await self.anime_poster_map.find().to_list(length=None)
        print("📄 Raw docs in anime_poster_map:", docs)
        return {doc["original"]: doc["poster_url"] for doc in docs if "original" in doc}


    async def get_thumbnail(self):
        """Fetch the stored thumbnail URL or return None if not set."""
        data = await self.thumb_data.find_one({"_id": "thumbnail"})
        return data["url"] if data else None

    async def set_thumbnail(self, url: str):
        """Set or update the stored thumbnail URL."""
        await self.thumb_data.update_one({"_id": "thumbnail"}, {"$set": {"url": url}}, upsert=True)


    async def get_banner(self):
        """Fetch the stored banner URL or return None if not set."""
        data = await self.banner_data.find_one({"_id": "banner"})
        return data["url"] if data else None

    async def set_banner(self, url: str):
        """Set or update the stored banner URL."""
        await self.banner_data.update_one({"_id": "banner"}, {"$set": {"url": url}}, upsert=True)
        
        
    async def getAnime(self, ani_id):
        return await self.__animes.find_one({'_id': ani_id}) or {}



    async def get_animes(title: str, rss_link: str, upload=True):
        try:
        # Check for custom rename
            custom_template = await db.get_custom_rename(title)
            if custom_template:
                await db.remove_custom_rename(title)
                LOGS.info(f"[Custom Rename] Using template for {title}: {custom_template}")
            else:
                custom_template = None

        # Get torrent and download
            torrent_info = await getfeed(rss_link)
            if not torrent_info:
                return LOGS.warning(f"No feed found for {title}")

        # Continue normal logic
            downloaded_file = await download_torrent(torrent_info.link)
            encoded_files = await encode_video(downloaded_file)

            for qual, encoded in encoded_files.items():
                if custom_template:
                    filename = custom_template.replace("{qual}", qual).strip()
                else:
                    filename = await default_naming_logic(title, qual, encoded)

                await upload_to_telegram(encoded, filename)

            LOGS.info(f"✅  Anime {title} processing complete")

        except Exception as e:
            await rep.report(format_exc(), "error")

    async def saveAnime(self, ani_id, ep, qual, post_id=None):
        quals = (await self.getAnime(ani_id)).get(ep, {qual: False for qual in Var.QUALS})
        quals[qual] = True
        await self.__animes.update_one({'_id': ani_id}, {'$set': {ep: quals}}, upsert=True)
        if post_id:
            await self.__animes.update_one({'_id': ani_id}, {'$set': {"msg_id": post_id}}, upsert=True)

    async def reboot(self):
        await self.__animes.drop()

# WATERMARK SETTINGS
    async def set_watermark(self, value: str | bool):        
        existing = await self.watermark_data.find_one({})
        if existing:
            await self.watermark_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.watermark_data.insert_one({'value': value})

    async def get_watermark(self):
        data = await self.watermark_data.find_one({})
        if data:
            return data.get('value', False)  # Default to False if no watermark is set
        return False



# USER MANAGEMENT
    async def present_user(self, user_id: int):
        found = await self.user_data.find_one({'_id': user_id})
        return bool(found)

    async def add_user(self, user_id: int):
        await self.user_data.insert_one({'_id': user_id})
        return

    async def full_userbase(self):
        user_docs = await self.user_data.find().to_list(length=None)
        user_ids = [doc['_id'] for doc in user_docs]
        return user_ids

    async def del_user(self, user_id: int):
        await self.user_data.delete_one({'_id': user_id})
        return

# CHANNEL BUTTON SETTINGS
    async def set_channel_button_link(self, button_name: str, button_link: str):
        await self.channel_button_link_data.delete_many({})  # Remove all existing documents
        await self.channel_button_link_data.insert_one({'button_name': button_name, 'button_link': button_link}) # Insert the new document

    async def get_channel_button_link(self):
        data = await self.channel_button_link_data.find_one({})
        if data:
            return data.get('button_name'), data.get('button_link')
        return ' Channel', 'https://t.me/HellFire_Academy_Official'


    # DELETE TIMER SETTINGS
    async def set_del_timer(self, value: int):        
        existing = await self.del_timer_data.find_one({})
        if existing:
            await self.del_timer_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.del_timer_data.insert_one({'value': value})

    async def get_del_timer(self):
        data = await self.del_timer_data.find_one({})
        if data:
            return data.get('value', 600)
        return 600

    # SET BOOLEAN VALUES FOR DIFFERENT SETTINGS

    async def set_auto_delete(self, value: bool):
        existing = await self.auto_delete_data.find_one({})
        if existing:
            await self.auto_delete_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.auto_delete_data.insert_one({'value': value})

    async def set_hide_caption(self, value: bool):
        existing = await self.hide_caption_data.find_one({})
        if existing:
            await self.hide_caption_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.hide_caption_data.insert_one({'value': value})

    async def set_protect_content(self, value: bool):
        existing = await self.protect_content_data.find_one({})
        if existing:
            await self.protect_content_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.protect_content_data.insert_one({'value': value})

    async def set_channel_button(self, value: bool):
        existing = await self.channel_button_data.find_one({})
        if existing:
            await self.channel_button_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.channel_button_data.insert_one({'value': value})

    async def set_request_forcesub(self, value: bool):
        existing = await self.rqst_fsub_data.find_one({})
        if existing:
            await self.rqst_fsub_data.update_one({}, {'$set': {'value': value}})
        else:
            await self.rqst_fsub_data.insert_one({'value': value})


    # GET BOOLEAN VALUES FOR DIFFERENT SETTINGS        

    async def get_auto_delete(self):
        data = await self.auto_delete_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    async def get_hide_caption(self):
        data = await self.hide_caption_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    async def get_protect_content(self):
        data = await self.protect_content_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    async def get_channel_button(self):
        data = await self.channel_button_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    async def get_request_forcesub(self):
        data = await self.rqst_fsub_data.find_one({})
        if data:
            return data.get('value', False)
        return False

    # CHANNEL MANAGEMENT
    async def channel_exist(self, channel_id: int):
        found = await self.channel_data.find_one({'_id': channel_id})
        return bool(found)

    async def add_channel(self, channel_id: int):
        if not await self.channel_exist(channel_id):
            await self.channel_data.insert_one({'_id': channel_id})
            return

    async def del_channel(self, channel_id: int):
        if await self.channel_exist(channel_id):
            await self.channel_data.delete_one({'_id': channel_id})
            return

    async def get_all_channels(self):
        channel_docs = await self.channel_data.find().to_list(length=None)
        channel_ids = [doc['_id'] for doc in channel_docs]
        return channel_ids

    # REQUEST FORCE-SUB MANAGEMENT

    # Initialize a channel with an empty user_ids array (acting as a set)
    async def add_reqChannel(self, channel_id: int):
        await self.rqst_fsub_Channel_data.update_one(
            {'_id': channel_id}, 
            {'$setOnInsert': {'user_ids': []}},  # Start with an empty array to represent the set
            upsert=True  # Insert the document if it doesn't exist
        )

    # Set the request_forcesub mode for a specific channel
    async def set_request_forcesub_channel(self, channel_id: int, fsub_mode: bool):
        await self.rqst_fsub_Channel_data.update_one(
        {'_id': channel_id},
        {'$set': {'fsub_mode': fsub_mode}},
        upsert=True
    )

    # Method 1: Add user to the channel set
    async def reqSent_user(self, channel_id: int, user_id: int):
        await db.rqst_fsub_Channel_data.update_one(
            {'_id': channel_id}, 
            {'$addToSet': {'user_ids': user_id}}, 
            upsert=True
        )
        print(f"✅ User {user_id} added to request list for channel {channel_id}")
        

    # Method 2: Remove a user from the channel set
    async def del_reqSent_user(self, channel_id: int, user_id: int):
        # Remove the user from the set of users for the channel
        await self.rqst_fsub_Channel_data.update_one(
            {'_id': channel_id}, 
            {'$pull': {'user_ids': user_id}}
        )

    # Clear the user set (user_ids array) for a specific channel
    async def clear_reqSent_user(self, channel_id: int):
        if await self.reqChannel_exist(channel_id):
            await self.rqst_fsub_Channel_data.update_one(
                {'_id': channel_id}, 
                {'$set': {'user_ids': []}}  # Reset user_ids to an empty array
            )

    # Method 3: Check if a user exists in the channel set
    async def reqSent_user_exist(self, channel_id: int, user_id: int):
        found = await db.rqst_fsub_Channel_data.find_one(
            {'_id': channel_id, 'user_ids': {'$in': [user_id]}}  # ✅ Correct array lookup
    )
        return bool(found)

    # Method 4: Remove a channel and its set of users
    async def del_reqChannel(self, channel_id: int):
        # Delete the entire channel's user set
        await self.rqst_fsub_Channel_data.delete_one({'_id': channel_id})

    # Method 5: Check if a channel exists
    async def reqChannel_exist(self, channel_id: int):
        # Check if the channel exists
        found = await self.rqst_fsub_Channel_data.find_one({'_id': channel_id})
        return bool(found)

    # Method 6: Get all users from a channel's set
    async def get_reqSent_user(self, channel_id: int):
        # Retrieve the list of users for a specific channel
        data = await self.rqst_fsub_Channel_data.find_one({'_id': channel_id})
        if data:
            return data.get('user_ids', [])
        return []

    # Method 7: Get all available channel IDs
    async def get_reqChannel(self):
        # Retrieve all channel IDs
        channel_docs = await self.rqst_fsub_Channel_data.find().to_list(length=None)
        channel_ids = [doc['_id'] for doc in channel_docs]
        return channel_ids


    # Get all available channel IDs in store_reqLink_data
    async def get_reqLink_channels(self):
        # Retrieve all documents from store_reqLink_data
        channel_docs = await self.store_reqLink_data.find().to_list(length=None)
        # Extract the channel IDs from the documents
        channel_ids = [doc['_id'] for doc in channel_docs]
        return channel_ids

    # Get the stored link for a specific channel
    async def get_stored_reqLink(self, channel_id: int):
        # Retrieve the stored link for a specific channel_id from store_reqLink_data
        data = await self.store_reqLink_data.find_one({'_id': channel_id})
        if data:
            return data.get('link')
        return None

    # Set (or update) the stored link for a specific channel
    async def store_reqLink(self, channel_id: int, link: str):
        # Insert or update the link for the channel_id in store_reqLink_data
        await self.store_reqLink_data.update_one(
            {'_id': channel_id}, 
            {'$set': {'link': link}}, 
            upsert=True
        )

    # Delete the stored link and the channel from store_reqLink_data
    async def del_stored_reqLink(self, channel_id: int):
        # Delete the document with the channel_id in store_reqLink_data
        await self.store_reqLink_data.delete_one({'_id': channel_id})

        # Set Main Channel ID
    async def set_main_channel(self, channel_id: int):
        await self.main_channel_data.update_one(
            {"_id": "main_channel"},
            {"$set": {"channel_id": channel_id}},
            upsert=True
        )
    # Get Main Channel ID
    async def get_main_channel(self):
        data = await self.main_channel_data.find_one({"_id": "main_channel"})
        return data["channel_id"] if data else None
    
    # Remove Main Channel ID
    async def remove_main_channel(self):
         await self.main_channel_data.delete_one({"_id": "main_channel"})


    async def set_anime_channel(self, anime_name: str, channel_id: int):
        anime_key = normalize_title(anime_name)
        await self.anime_channel_map.update_one(
            {"_id": anime_key},
            {"$set": {"original": anime_name, "channel_id": channel_id}},
            upsert=True
        )

    async def get_anime_channel(self, anime_name: str):
        anime_key = normalize_title(anime_name)
        data = await self.anime_channel_map.find_one({"_id": anime_key})
        return data["channel_id"] if data else None

    async def del_anime_channel(self, anime_name: str):
        anime_key = normalize_title(anime_name)
        await self.anime_channel_map.delete_one({"_id": anime_key})

    async def list_all_anime_channels(self):
        docs = await self.anime_channel_map.find().to_list(length=None)
        print("📄 Raw docs in anime_channel_map:", docs)
        return {doc["original"]: doc["channel_id"] for doc in docs if "original" in doc}

    async def set_anime_invite(self, anime_name: str, invite: str):
        await self.anime_invites.update_one(
            {"_id": normalize_title(anime_name)},
            {"$set": {"original": anime_name, "invite": invite}},
            upsert=True
        )

    async def get_anime_invite(self, anime_name: str):
        doc = await self.anime_invites.find_one({"_id": normalize_title(anime_name)})
        return doc.get("invite") if doc else None

    async def delete_anime_invite(self, anime_name: str):
        await self.anime_invites.delete_one({"_id": normalize_title(anime_name)})



    # === CUSTOM RENAME MANAGEMENT ===
    async def set_custom_rename(self, title: str, rename_pattern: str):
        """
        Set or update a custom rename pattern for a given title.
        Automatically deletes the oldest entry if total exceeds 50.
        """
        await self.rename.update_one(
            {"title": title},
            {"$set": {"rename": rename_pattern, "timestamp": datetime.utcnow()}},
            upsert=True
        )

        # Check if total entries exceed 50
        count = await self.rename.count_documents({})
        if count > 50:
            # Find and delete the oldest entry
            oldest = await self.rename.find_one(sort=[("timestamp", 1)])
            if oldest:
                await self.rename.delete_one({"_id": oldest["_id"]})

    async def get_custom_rename(self, title: str) -> str | None:
        """
        Get the custom rename pattern for a given title.
        """
        data = await self.rename.find_one({"title": title})
        return data.get("rename") if data else None

    async def remove_custom_rename(self, title: str):
        """
        Remove custom rename pattern after use.
        """
        await self.rename.delete_one({"title": title})

    async def task_exists(self, title: str) -> bool:
        return await self.tasks.find_one({"title": title}) is not None

    # === GROQ API KEYS MANAGEMENT ===
    async def add_groq_api_key(self, user_id: int, api_key: str):
        """Add a Groq API key to the global pool. Keep maximum of 15 keys."""
        # Using a fixed ID for the global pool
        pool_id = "global_groq_pool"
        await self.user_data.update_one(
            {"_id": pool_id},
            {"$addToSet": {"keys": api_key}},
            upsert=True
        )
        # Enforce max 15 keys
        data = await self.user_data.find_one({"_id": pool_id})
        if data and len(data.get("keys", [])) > 15:
            await self.user_data.update_one(
                {"_id": pool_id},
                {"$pop": {"keys": -1}} # Remove the first/oldest key
            )

    async def get_groq_api_pool(self, user_id: int) -> list:
        """Get the global pool of Groq API keys."""
        pool_id = "global_groq_pool"
        data = await self.user_data.find_one({"_id": pool_id})
        return data.get("keys", []) if data else []

    async def clear_groq_api_pool(self, user_id: int):
        """Clear all Groq API keys from the global pool."""
        pool_id = "global_groq_pool"
        await self.user_data.update_one(
            {"_id": pool_id},
            {"$set": {"keys": []}}
        )

    # === UPLOAD MODE MANAGEMENT ===
    # Mode is hardcoded to "document" now, these methods are no longer needed.

    async def get_shortner_settings(self):
        data = await self.shortner_data.find_one({"_id": "shortner_settings"})
        if not data:
            return {
                'enabled': False,
                'short_url': 'publicearn.com',
                'short_api': '',
                'tutorial_link': 'https://t.me/How_to_Download_7x/26',
                'verification_time': 86400
            }
        return data

    async def update_shortner_settings(self, settings: dict):
        await self.shortner_data.update_one(
            {"_id": "shortner_settings"},
            {"$set": settings},
            upsert=True
        )

    async def is_user_verified(self, user_id: int):
        settings = await self.get_shortner_settings()
        if not settings.get('enabled', False):
            return True

        user_data = await self.verify_data.find_one({"_id": user_id})
        if not user_data:
            return False

        last_verify = user_data.get('last_verify', 0)
        verify_time = settings.get('verification_time', 86400)

        if (time.time() - last_verify) < verify_time:
            return True
        return False

    async def update_user_verification(self, user_id: int):
        await self.verify_data.update_one(
            {"_id": user_id},
            {"$set": {"last_verify": time.time()}},
            upsert=True
        )


db = MongoDB(Var.MONGO_URI, "Raiden_Shogun_File_Bot")
