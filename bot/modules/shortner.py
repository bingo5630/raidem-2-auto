import requests
import random
import string
import time
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from bot.core.database import db
from bot.core.func_utils import sync_to_async
from bot import Var

# ✅ In-memory cache
shortened_urls_cache = {}

def generate_random_alphanumeric():
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(8))
    
async def get_short(url):
    settings = await db.get_shortner_settings()
    shortner_enabled = settings.get('enabled', False)
    if not shortner_enabled:
        return url

    if url in shortened_urls_cache:
        return shortened_urls_cache[url]

    try:
        alias = generate_random_alphanumeric()
        short_url = settings.get('short_url')
        short_api = settings.get('short_api')
       
        api_url = f"https://{short_url}/api?api={short_api}&url={url}&alias={alias}"
        response = await sync_to_async(requests.get, api_url)
        rjson = response.json()
        if rjson.get("status") == "success" and response.status_code == 200:
            short_url_res = rjson.get("shortenedUrl", url)
            shortened_urls_cache[url] = short_url_res
            return short_url_res
    except Exception as e:
        print(f"[Shortener Error] {e}")
    return url

async def generate_verification_link(user_id, client):
    bot_info = await client.get_me()
    token = generate_random_alphanumeric()
    # We store the token or just use it to generate a link that redirects back to the bot with a specific param
    # For simplicity, we can just use the user_id in the token or just a random one if we don't need to verify the token itself strictly (the shortener already does that by delivering the user to the link)
    # The target link should be https://t.me/bot_username?start=verify_{user_id}
    target_url = f"https://t.me/{bot_info.username}?start=verify_{user_id}"
    short_link = await get_short(target_url)
    return short_link

#===============================================================#
@Client.on_message(filters.command('shortner') & filters.private)
async def shortner_command(client: Client, message: Message):
    if message.from_user.id not in Var.ADMINS:
        return
    await shortner_panel(client, message)
#===============================================================#
async def shortner_panel(client, query_or_message):
    # Get current shortner settings from DB
    settings = await db.get_shortner_settings()
    short_url = settings.get('short_url')
    short_api = settings.get('short_api')
    tutorial_link = settings.get('tutorial_link')
    shortner_enabled = settings.get('enabled', False)
    verification_time = settings.get('verification_time', 86400)
   
    # Check if shortner is working (only if enabled)
    if shortner_enabled:
        try:
            test_response = requests.get(f"https://{short_url}/api?api={short_api}&url=https://google.com&alias=test_{int(time.time())}", timeout=5)
            status = "✓ ᴡᴏʀᴋɪɴɢ" if test_response.status_code == 200 else "✗ ɴᴏᴛ ᴡᴏʀᴋɪɴɢ"
        except:
            status = "✗ ɴᴏᴛ ᴡᴏʀᴋɪɴɢ"
    else:
        status = "✗ ᴅɪsᴀʙʟᴇᴅ"
   
    enabled_text = "✓ ᴇɴᴀʙʟᴇᴅ" if shortner_enabled else "✗ ᴅɪsᴀʙʟᴇᴅ"
    toggle_text = "✗ ᴏғғ" if shortner_enabled else "✓ ᴏɴ"
   
    # Format verification time
    hours = verification_time // 3600
    if hours >= 24:
        days = hours / 24
        validity_text = f"{days:.1f} Days" if days % 1 != 0 else f"{int(days)} Days"
    else:
        validity_text = f"{hours} Hours"

    msg = f"""<blockquote>✦ 𝗦𝗛𝗢𝗥𝗧𝗡𝗘𝗥 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦</blockquote>
**<u>ᴄᴜʀʀᴇɴᴛ ꜱᴇᴛᴛɪɴɢꜱ:</u>**
<blockquote>›› **ꜱʜᴏʀᴛɴᴇʀ ꜱᴛᴀᴛᴜꜱ:** {enabled_text}
›› **ꜱʜᴏʀᴛɴᴇʀ ᴜʀʟ:** `{short_url}`
›› **ꜱʜᴏʀᴛɴᴇʀ ᴀᴘɪ:** `{short_api}`</blockquote>
<blockquote>›› **ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ:** `{tutorial_link}`
›› **ᴀᴘɪ ꜱᴛᴀᴛᴜꜱ:** {status}
›› **ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴠᴀʟɪᴅɪᴛʏ:** {validity_text}</blockquote>
<blockquote>**≡ ᴜꜱᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ ᴛᴏ ᴄᴏɴꜰɪɢᴜʀᴇ ʏᴏᴜʀ ꜱʜᴏʀᴛɴᴇʀ ꜱᴇᴛᴛɪɴɢꜱ!**</blockquote>"""
   
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f'• {toggle_text} ꜱʜᴏʀᴛɴᴇʀ •', 'toggle_shortner'), InlineKeyboardButton('• ᴀᴅᴅ ꜱʜᴏʀᴛɴᴇʀ •', 'add_shortner')],
        [InlineKeyboardButton('• ꜱᴇᴛ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ •', 'set_tutorial_link')],
        [InlineKeyboardButton('• ꜱᴇᴛ ᴠᴀʟɪᴅɪᴛʏ •', 'set_validity')],
        [InlineKeyboardButton('• ᴛᴇꜱᴛ ꜱʜᴏʀᴛɴᴇʀ •', 'test_shortner')],
        [InlineKeyboardButton('◂ ʙᴀᴄᴋ ᴛᴏ ꜱᴇᴛᴛɪɴɢꜱ', 'setting')]
    ])
   
    image_url = "https://telegra.ph/file/8aaf4df8c138c6685dcee-05d3b183d4978ec347.jpg"
   
    if isinstance(query_or_message, CallbackQuery):
        await query_or_message.message.edit_media(
            media=InputMediaPhoto(media=image_url, caption=msg),
            reply_markup=reply_markup
        )
    else:
        await query_or_message.reply_photo(photo=image_url, caption=msg, reply_markup=reply_markup)
#===============================================================#
