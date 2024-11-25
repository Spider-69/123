import os
import logging
import math
import time
import asyncio
from datetime import timedelta
import subprocess
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import DOWNLOADS_DIR

# Initialize logger with custom format
LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

# Progress bar constants
FINISHED_PROGRESS_STR = "⬢"
UNFINISHED_PROGRESS_STR = "⬡"

class Helper:
    def __init__(self):
        self.last_update_time = 0
        self.lock = asyncio.Lock()

    def format_time(self, seconds):
        """Format seconds into HH:MM:SS."""
        return str(timedelta(seconds=int(seconds)))

    def format_size(self, bytes):
        """Format bytes into appropriate units."""
        if bytes == 0:
            return "0B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        u = 0
        while bytes >= 1024 and u < len(units) - 1:
            bytes /= 1024
            u += 1
        return f"{bytes:.2f} {units[u]}"

    def create_progress_bar(self, current, total):
        """Create a futuristic 10-segment progress bar."""
        progress = (current / total) if total else 0
        filled = int(10 * progress)
        
        # Using hexagonal symbols
        bar = "⬢" * filled + "⬡" * (10 - filled)
        percentage = progress * 100
        return f"[{bar}] {percentage:.1f}%"

    async def progress_for_pyrogram(self, current, total, status_msg, start_time, action="Processing"):
        """Enhanced progress display for Pyrogram file transfers with asyncio-based updates."""
        try:
            if total == 0:
                return

            now = time.time()
            
            # Use lock to prevent multiple simultaneous updates
            async with self.lock:
                # Check if 10 seconds have passed since last update
                if now - self.last_update_time < 10 and self.last_update_time != 0:
                    return

                elapsed_time = now - start_time
                
                # Calculate speeds and progress
                speed = current / elapsed_time if elapsed_time > 0 else 0
                progress = (current / total) * 100
                estimated_total_time = elapsed_time * (total / current) if current > 0 else 0
                eta = estimated_total_time - elapsed_time if estimated_total_time > 0 else 0
                
                # Create the progress bar
                progress_bar = self.create_progress_bar(current, total)
                
                # Format the progress message
                status_text = (
                    f"<blockquote>"
                    f"<b> {action}...</b>\n\n"
                    f"<code>{progress_bar}</code>\n"
                    f"⏱️ Time: {self.format_time(elapsed_time)} / {self.format_time(estimated_total_time)}\n"
                    f"🚀 Speed: {self.format_size(speed)}/s\n"
                    f"⏳ ETA: {self.format_time(eta)}\n"
                    f"📊 Size: {self.format_size(current)} / {self.format_size(total)}"
                    f"</blockquote>"
                )

                # Update the message if content has changed and enough time has passed
                if status_msg is not None and (status_msg.text != status_text or now - self.last_update_time >= 5):
                    await status_msg.edit_text(status_text)
                    self.last_update_time = now

        except Exception as e:
            LOGGER.error(f"Progress update error: {str(e)}")

    def clean_filename(self, filename):
        """Clean filename by removing invalid characters."""
        return "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).strip()

def create_format_buttons(formats, prefix="dl_"):
    """Creates an inline keyboard with video format options in two-column layout."""
    buttons = []
    row = []
    for format in formats:
        format_id = format['format_id']
        resolution = format['resolution']
        ext = format['ext']
        fps = format.get('fps', 'N/A')

        button_label = f"{resolution} ({ext}, {fps} FPS)"
        row.append(InlineKeyboardButton(button_label, callback_data=f"{prefix}{format_id}"))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(buttons)

def clean_files(*files):
    """Remove specified files if they exist."""
    for file in files:
        try:
            if os.path.exists(file):
                if os.path.isfile(file):
                    os.remove(file)
                    LOGGER.info(f"Deleted file: {file}")
                else:
                    LOGGER.warning(f"Skipped deletion. {file} is a directory.")
            else:
                LOGGER.info(f"File not found and skipped: {file}")
        except Exception as e:
            LOGGER.error(f"Failed to delete file {file}: {e}")

async def get_video_duration(video_path):
    """Get the duration of a video file in seconds."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return round(float(result.stdout)) if result.returncode == 0 else None
    except Exception as e:
        LOGGER.error(f"Error fetching video duration: {e}")
        return None

async def take_screenshot(path):
    """Capture a screenshot from the video and save it as thumb.jpg in DOWNLOADS_DIR."""
    thumb_path = os.path.join(DOWNLOADS_DIR, "thumb.jpg")
    try:
        subprocess.call(["ffmpeg", "-i", path, "-ss", "00:00:01.000", "-vframes", "1", thumb_path])
        LOGGER.info(f"Screenshot taken and saved to {thumb_path}")
    except Exception as e:
        LOGGER.error(f"Failed to take screenshot: {e}")
        return None
    return thumb_path
