
import requests
import os, string, random, subprocess, json, shutil
import re
import time
import socket
import logging
from bot import bot, bot_loop, Var, ani_cache
from bot.core.database import db
from bot.core.func_utils import *
from bot.core.auto_animes import get_animes
from bot.core.reporter import rep
from bot.func import *
from bot.autoDelete import *
from bot.query import *
import aria2p

LOGS = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Utility Functions
# ──────────────────────────────────────────────────────────────

def wait_for_aria2(port=6800, timeout=10):
    """Wait until aria2 RPC server is ready."""
    start_time = time.time()
    while True:
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                LOGS.info("aria2c RPC server is ready!")
                return
        except (OSError, ConnectionRefusedError):
            if time.time() - start_time > timeout:
                raise RuntimeError("aria2c RPC server failed to start in time.")
            time.sleep(1)

def get_aria2_client(retries=5, delay=2):
    """Get aria2p client, retrying if needed."""
    for attempt in range(retries):
        try:
            return aria2p.API(
                aria2p.Client(host="http://localhost", port=6800, secret="")
            )
        except Exception:
            LOGS.warning(f"Aria2 not ready yet, retrying... ({attempt+1}/{retries})")
            time.sleep(delay)
    raise RuntimeError("Could not connect to aria2c RPC server.")

def sanitize_filename(file_name):
    """Remove invalid characters from the file name."""
    return re.sub(r'[<>:"/\\|?*]', '', file_name)

# ──────────────────────────────────────────────────────────────
# Start aria2c RPC server in background
# ──────────────────────────────────────────────────────────────

system(
    "aria2c --enable-rpc --rpc-listen-all=true --rpc-allow-origin-all "
    "--continue=true --max-connection-per-server=16 --min-split-size=1M -D"
)

wait_for_aria2()
aria2 = get_aria2_client()

# ──────────────────────────────────────────────────────────────
# Download function
# ──────────────────────────────────────────────────────────────


def download_file(url, download_path):
    """
    Download a file using aria2p for high-speed downloading.
    Returns the actual saved file path.
    """
    os.makedirs(os.path.dirname(download_path), exist_ok=True)

    # Add download
    download = aria2.add_uris(
        [url],
        options={
            "dir": os.path.abspath(os.path.dirname(download_path)),
            "out": os.path.basename(download_path)
        }
    )

    # Wait until aria2 reports completion
    while True:
        download.update()
        if download.status == "complete":
            break
        if download.status == "error":
            raise Exception(f"Download failed: {download.error_message}")
        time.sleep(1)

    # Get actual path saved by aria2
    actual_path = download.files[0].path

    # Extra wait to ensure file is ready
    for _ in range(10):
        if os.path.exists(actual_path):
            return actual_path
        time.sleep(1)

    raise FileNotFoundError(f"File not found after download: {actual_path}")



def create_short_name(name):
    # Check if the name length is greater than 25
    if len(name) > 30:
        # Extract all capital letters from the name
        short_name = ''.join(word[0].upper() for word in name.split())					
        return short_name    
    return name
def get_media_details(path):
    try:
        # Run ffprobe command to get media info in JSON format
        result = subprocess.run(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Error: Unable to process the file. FFprobe output:\n{result.stderr}")
            return None

        # Parse JSON output
        media_info = json.loads(result.stdout)

        # Extract width, height, and duration
        video_stream = next((stream for stream in media_info["streams"] if stream["codec_type"] == "video"), None)
        width = video_stream.get("width") if video_stream else None
        height = video_stream.get("height") if video_stream else None
        duration = media_info["format"].get("duration")

        return width, height, duration

    except Exception as e:
        print(f"An error occurred: {e}")
        return None

        



def send_and_delete_file(client, chat_id, file_path, thumbnail=None, caption="", user_id=None):
    upload_method = get_upload_method(user_id)  # Retrieve user's upload method
    forwarding_channel = Var.LOG_CHANNEL  # Channel to forward the file

    try:        
        user_info = client.get_users(user_id)
        user_details = f"Downloaded by: @{user_info.username if user_info.username else 'Unknown'} (ID: {user_id})"
        
        # Add user info to the caption
        caption_with_info = f"{caption}\n\n{user_details}"
        if upload_method == "document":
            # Send as document
            sent_message = client.send_document(
                chat_id,
                file_path,
                thumb=thumbnail if thumbnail else None,
                caption=caption
            )
        else:
            # Send as video
            details = get_media_details(file_path)
            if details:
                width, height, duration = details  # Unpack the values properly
                width = int(width) if width else None
                height = int(height) if height else None
                duration = int(float(duration)) if duration else None
            sent_message = client.send_video(
                chat_id,
                file_path,
                duration= duration if duration else None,
                width= width if width else None,
                height= height if height else None,
                supports_streaming= True,
                has_spoiler= True,
                thumb=None,
                caption=caption
            )
        
        # Forward the message to the specified channel
        forward_message = client.copy_message(
            chat_id=forwarding_channel,
            from_chat_id=chat_id,
            message_id=sent_message.id,
            caption=caption_with_info
        )
        
        # Delete the file after sending and forwarding
        os.remove(file_path)
        
    except Exception as e:
        client.send_message(chat_id, f"Error: {str(e)}")
        

def remove_directory(directory_path):
    if not os.path.exists(directory_path):
        raise FileNotFoundError(f"The directory '{directory_path}' does not exist.")
    
    try:
        shutil.rmtree(directory_path)
        #print(f"Directory '{directory_path}' has been removed successfully.")
    except PermissionError as e:
        print(f"Permission denied: {e}")
    except Exception as e:
        print(f"An error occurred while removing the directory: {e}")

def random_string(length):
    if length < 1:
        raise ValueError("Length must be a positive integer.")
    
    # Define the characters to choose from (letters and digits)
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

