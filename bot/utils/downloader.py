import os
import logging
import yt_dlp
import time
import asyncio
import json
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pyrogram.types import Message
from config import COOKIES_PATH
# Initialize logging and executor
LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
executor = ThreadPoolExecutor(max_workers=4)

def format_time(seconds):
    """Format seconds into HH:MM:SS."""
    try:
        seconds = int(seconds)
        if seconds < 0:
            seconds = 0
        return str(timedelta(seconds=seconds))
    except:
        return "00:00:00"

def format_size(bytes):
    """Format bytes into appropriate units."""
    try:
        bytes = float(bytes)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024:
                return f"{bytes:.2f} {unit}"
            bytes /= 1024
        return f"{bytes:.2f} TB"
    except:
        return "0 B"

def create_progress_bar(percentage):
    """Create a futuristic 10-segment progress bar with hexagonal symbols."""
    try:
        # Ensure percentage is within bounds and round to 1 decimal place
        percentage = min(max(float(percentage), 0), 100)
        
        # Calculate the number of filled segments based on 10 total segments
        filled = int(10 * percentage / 100)
        
        # Build the progress bar with filled and unfilled hexagons
        bar = '⬢' * filled + '⬡' * (10 - filled)
        return f'[{bar}] {percentage:.1f}%'
    
    except Exception as e:
        print(f"Error creating progress bar: {e}")
        # Return default progress bar in case of an error
        return '[⬡⬡⬡⬡⬡⬡⬡⬡⬡⬡] 0.0%'

def load_cookies(cookie_path):
    """Load cookies from a file and return them as a dictionary."""
    cookies = {}
    if os.path.exists(cookie_path):
        try:
            with open(cookie_path, 'r') as cookie_file:
                cookies = json.load(cookie_file)
        except json.JSONDecodeError as e:
            LOGGER.error(f"Error decoding cookies: {e}")
    return cookies

cookies_dict = load_cookies(COOKIES_PATH)

class ProgressHandler:
    def __init__(self, status_msg, event_loop):
        self.status_msg = status_msg
        self.event_loop = event_loop
        self.last_update_time = 0
        self._progress_lock = asyncio.Lock()
        self.update_interval = 5  # 10 seconds interval for progress update
        
    async def update_status(self, text):
        try:
            async with self._progress_lock:
                await self.status_msg.edit_text(text)
        except Exception as e:
            LOGGER.error(f"Error updating status: {e}")

    def progress_hook(self, d):
        """Progress hook that handles both downloading and post-processing."""
        try:
            current_time = time.time()
            
            # Only update progress every 10 seconds
            if current_time - self.last_update_time < self.update_interval:
                return
                
            downloaded = d.get('downloaded_bytes', 0) or 0
            total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0) or 0
            speed = d.get('speed', 0) or 0
            elapsed = d.get('elapsed', 0) or 0
            eta = d.get('eta', 0) or 0
            
            if total > 0:
                percent = (downloaded * 100 / total)
            else:
                percent = 0
                
            progress_bar = create_progress_bar(percent)
            
            status_text = (
                f"<blockquote>"
                f"<b>📥 Downloading Video...</b>\n\n"
                f"<code>{progress_bar}</code>\n"
                f"Time: {format_time(elapsed)} / {format_time(elapsed + eta)}\n"
                f"Speed: {format_size(speed)}/s\n"
                f"ETA: {format_time(eta)}\n"
                f"Size: {format_size(downloaded)} / {format_size(total)}"
                f"</blockquote>"
            )

            asyncio.run_coroutine_threadsafe(
                self.update_status(status_text),
                self.event_loop
            )
            self.last_update_time = current_time
                
            if d['status'] == 'finished':
                asyncio.run_coroutine_threadsafe(
                    self.update_status("⚙️ Processing video..."),
                    self.event_loop
                )
                
        except Exception as e:
            LOGGER.error(f"Progress hook error: {e}")


async def get_video_formats(url):
    """Extracts video formats from a URL using cookies."""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'cookies': cookies_dict  # Added cookies here
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(
                executor, 
                lambda: ydl.extract_info(url, download=False)
            )
            
            formats = [
                {
                    'format_id': f.get('format_id'),
                    'ext': f.get('ext', 'unknown'),
                    'resolution': f.get('height', 0),
                    'fps': f.get('fps', 'N/A'),
                }
                for f in info.get('formats', [])
                if (f.get('vcodec') != 'none' and 
                    f.get('height', 0) >= 360 and 
                    f.get('filesize', 0) is not None and 
                    f.get('filesize', 0) > 0)
            ]

            title = info.get('title', 'No title available')
            LOGGER.info("Formats extracted successfully")
            return formats, title
            
    except Exception as e:
        LOGGER.error(f"Error fetching video formats: {e}")
        return [], "Error"

async def download_video(url, format_id, output_path, status_msg):
    """Downloads video with progress reporting."""
    try:
        if os.path.exists(output_path):
            await status_msg.edit_text("✅ File already exists. Skipping download.")
            return True

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Get the current event loop
        loop = asyncio.get_running_loop()
        
        # Initialize progress handler
        progress_handler = ProgressHandler(status_msg, loop)
        
        # Configure yt-dlp options
        ydl_opts = {
            'format': f"{format_id}+bestaudio/best",
            'outtmpl': output_path,
            'progress_hooks': [progress_handler.progress_hook],
            'merge_output_format': 'mp4',
            'quiet': False,
            'no_warnings': True,
            'cookies': cookies_dict  # Added cookies here
        }

        await status_msg.edit_text("🔍 Starting download...")

        # Run the download in a thread pool
        await loop.run_in_executor(
            executor,
            lambda: download_with_ytdlp(url, ydl_opts)
        )
        
        # Check if download was successful
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            await status_msg.edit_text(
                f"✅ Download Complete!\n\n"
                f"📊 File Size: {format_size(file_size)}\n"
                f"📂 Saved to: {os.path.basename(output_path)}"
            )
            return True
        else:
            await status_msg.edit_text("❌ Download failed: Output file not found")
            return False

    except asyncio.CancelledError:
        LOGGER.info("Download task was cancelled")
        raise
    except Exception as e:
        LOGGER.error(f"Download error: {str(e)}")
        await status_msg.edit_text(f"❌ Unexpected error: {str(e)}")
        return False

def download_with_ytdlp(url, ydl_opts):
    """Execute yt-dlp download in a separate thread."""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        LOGGER.error(f"YT-DLP download error: {e}")
        raise
