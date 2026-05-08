from multiprocessing import cpu_count
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from json import loads as jloads
from re import findall
from math import floor
from os import path as ospath
from time import time, sleep
from traceback import format_exc
from asyncio import sleep as asleep, create_subprocess_shell
from asyncio.subprocess import PIPE
from base64 import urlsafe_b64encode, urlsafe_b64decode
from pyrogram import filters, Client
from aiohttp import ClientSession
from aiofiles import open as aiopen
from aioshutil import rmtree as aiormtree
from html_telegraph_poster import TelegraphPoster
from feedparser import parse as feedparse
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified, FloodWait, UserNotParticipant, ReplyMarkupInvalid, MessageIdInvalid
from pyrogram.errors import PeerIdInvalid
from bot import bot, bot_loop, LOGS, Var
from .reporter import rep
from PIL import Image
import shutil
import math, time
from datetime import datetime
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from urllib.parse import unquote, urlparse, parse_qs
import aiohttp
import bencodepy
import os, re
import asyncio
import subprocess
import base64
import binascii
from os import cpu_count

def handle_logs(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception:
            await rep.report(format_exc(), "error")
    return wrapper
    
async def sync_to_async(func, *args, wait=True, **kwargs):
    pfunc = partial(func, *args, **kwargs)
    future = bot_loop.run_in_executor(ThreadPoolExecutor(max_workers=cpu_count() * 125), pfunc)
    return await future if wait else future
    
def new_task(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return bot_loop.create_task(func(*args, **kwargs))
    return wrapper

async def getfeed(link, index=0):
    try:
        feed = await sync_to_async(feedparse, link)
        return feed.entries[index]
    except IndexError:
        return None
    except Exception as e:
        LOGS.error(format_exc())
        return None

@handle_logs
async def aio_urldownload(link):
    async with ClientSession() as sess:
        async with sess.get(link) as data:
            image = await data.read()
    path = f"thumbs/{link.split('/')[-1]}"
    if not path.endswith((".jpg" or ".png")):
        path += ".jpg"
    async with aiopen(path, "wb") as f:
        await f.write(image)
    return path

@handle_logs
async def get_telegraph(out):
    client = TelegraphPoster(use_api=True)
    client.create_api_token("Mediainfo")
    uname = Var.BRAND_UNAME.lstrip('@')
    page = client.post(
        title="Mediainfo",
        author=uname,
        author_url=f"https://t.me/{uname}",
        text=f"""<pre>
{out}
</pre>
""",
        )
    return page.get("url")
    
async def sendMessage(chat, text, buttons=None, get_error=False, **kwargs):
    try:
        kwargs.pop("reply_markup", None)  # ✅ Remove if already passed

        if isinstance(chat, int):
            return await bot.send_message(
                chat_id=chat,
                text=text,
                disable_web_page_preview=True,
                disable_notification=False,
                reply_markup=buttons,
                **kwargs
            )
        else:
            return await chat.reply(
                text=text,
                quote=True,
                disable_web_page_preview=True,
                disable_notification=False,
                reply_markup=buttons,
                **kwargs
            )

    except FloodWait as f:
        await rep.report(f, "warning")
        sleep(f.value * 1.2)
        return await sendMessage(chat, text, buttons, get_error, **kwargs)

    except ReplyMarkupInvalid:
        return await sendMessage(chat, text, None, get_error, **kwargs)

    except Exception as e:
        await rep.report(format_exc(), "error")
        if get_error:
            raise e
        return str(e)
        
async def editMessage(msg, text, buttons=None, get_error=False, **kwargs):
    try:
        if not msg:
            return None

        kwargs.pop("reply_markup", None)  # Prevent duplicate keyword

        return await msg.edit_text(
            text=text,
            disable_web_page_preview=True,
            reply_markup=buttons,
            **kwargs
        )

    except FloodWait as f:
        await rep.report(f, "warning")
        sleep(f.value * 1.2)
        return await editMessage(msg, text, buttons, get_error, **kwargs)

    except ReplyMarkupInvalid:
        return await editMessage(msg, text, None, get_error, **kwargs)

    except (MessageNotModified, MessageIdInvalid):
        pass

    except Exception as e:
        await rep.report(format_exc(), "error")
        if get_error:
            raise e
        return str(e)

async def encode(string):
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    base64_string = (base64_bytes.decode("ascii")).strip("=")
    return base64_string


async def decode(base64_string):
    base64_string = base64_string.strip("=") # links generated before this commit will be having = sign, hence striping them to handle padding errors.
    base64_bytes = (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii")
    string_bytes = base64.urlsafe_b64decode(base64_bytes) 
    string = string_bytes.decode("ascii")
    return string



async def mediainfo(file, get_json=False, get_duration=False):
    try:
        outformat = "HTML"
        if get_duration or get_json:
            outformat = "JSON"
        process = await create_subprocess_shell(f"mediainfo '''{file}''' --Output={outformat}", stdout=PIPE, stderr=PIPE)
        stdout, _ = await process.communicate()
        if get_duration:
            try:
                return float(jloads(stdout.decode())['media']['track'][0]['Duration'])
            except Exception:
                return 1440 # 24min
        return await get_telegraph(stdout.decode())
    except Exception as err:
        await rep.report(format_exc(), "error")
        return ""
        
async def clean_up():
    try:
        (await aiormtree(dirtree) for dirtree in ("downloads", "thumbs", "encode"))
    except Exception as e:
        LOGS.error(str(e))

def convertTime(s: int) -> str:
    m, s = divmod(int(s), 60)
    hr, m = divmod(m, 60)
    days, hr = divmod(hr, 24)
    convertedTime = (f"{int(days)}d, " if days else "") + \
          (f"{int(hr)}h, " if hr else "") + \
          (f"{int(m)}m, " if m else "") + \
          (f"{int(s)}s, " if s else "")
    return convertedTime[:-2]

def convertBytes(sz) -> str:
    if not sz: 
        return ""
    sz = int(sz)
    ind = 0
    Units = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T', 5: 'P'}
    while sz > 2**10:
        sz /= 2**10
        ind += 1
    return f"{round(sz, 2)} {Units[ind]}B"

def extract_title_from_magnet(magnet_link):
    try:
        qs = parse_qs(urlparse(magnet_link).query)
        return unquote(qs.get("dn", ["Magnet Task"])[0])
    except Exception:
        return "Magnet Task"


async def extract_title_from_torrent(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    info = bencodepy.decode(data)[b'info']
                    return info[b'name'].decode()
    except Exception as e:
        print(f"Failed to parse torrent: {e}")
    return "Torrent Task"


async def get_messages(client, message_ids):
    messages = []
    total_messages = 0
    while total_messages != len(message_ids):
        temb_ids = message_ids[total_messages:total_messages+200]
        try:
            msgs = await client.get_messages(
                chat_id=client.db_channel.id,
                message_ids=temb_ids
            )
        except FloodWait as e:
            await asyncio.sleep(e.x)
            msgs = await client.get_messages(
                chat_id=client.db_channel.id,
                message_ids=temb_ids
            )
        except:
            pass
        total_messages += len(temb_ids)
        messages.extend(msgs)
    return messages

async def get_message_id(client, message):
    if message.forward_from_chat:
        if message.forward_from_chat.id == Var.FILE_STORE:
            return message.forward_from_message_id
        else:
            return 0

    elif message.forward_sender_name:
        return 0

    elif message.text:
        pattern = r"https://t\.me/(?:c/)?(.*)/(\d+)"
        matches = re.match(pattern, message.text.strip())
        if not matches:
            return 0
        channel_id = matches.group(1)
        msg_id = int(matches.group(2))

        if channel_id.isdigit():
            if f"-100{channel_id}" == str(Var.FILE_STORE):
                return msg_id
        else:
            if channel_id == Var.FILE_STORE:
                return msg_id

    return 0