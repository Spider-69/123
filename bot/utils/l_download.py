import asyncio
import os
import time
from datetime import timedelta
from typing import Tuple
import aiohttp
from config import DOWNLOADS_DIR

class Helper:
    def format_time(self, seconds: float) -> str:
        """Format seconds into HH:MM:SS."""
        return str(timedelta(seconds=int(seconds)))

    def format_size(self, bytes: float) -> str:
        """Format bytes into appropriate units."""
        if bytes == 0:
            return "0B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        u = 0
        while bytes >= 1024 and u < len(units) - 1:
            bytes /= 1024
            u += 1
        return f"{bytes:.2f} {units[u]}"

    def create_progress_bar(self, current: float, total: float) -> str:
        """Create a futuristic 10-segment progress bar."""
        progress = (current / total) if total else 0
        filled = int(10 * progress)
        
        # Using hexagonal symbols
        bar = "⬢" * filled + "⬡" * (10 - filled)
        percentage = progress * 100
        return f"[{bar}] {percentage:.1f}%"

class HTTPDownloader:
    def __init__(self, download_dir: str = DOWNLOADS_DIR):
        self.helper = Helper()
        self.download_dir = download_dir

    async def download_part(self, url: str, start_byte: int, end_byte: int, file_path: str, progress_tracker: list):
        headers = {"Range": f"bytes={start_byte}-{end_byte}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                with open(file_path, 'r+b') as f:
                    f.seek(start_byte)
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        f.write(chunk)
                        progress_tracker[0] += len(chunk)  # Update the shared progress tracker

    async def update_progress(self, total_size: float, status_msg, progress_tracker: list):
        start_time = time.time()

        while progress_tracker[0] < total_size:
            elapsed_time = time.time() - start_time
            downloaded_size = progress_tracker[0]
            speed = downloaded_size / elapsed_time if elapsed_time > 0 else 0
            progress = (downloaded_size / total_size) * 100
            estimated_total_time = elapsed_time * (total_size / downloaded_size) if downloaded_size > 0 else 0
            eta = estimated_total_time - elapsed_time if estimated_total_time > 0 else 0

            progress_bar = self.helper.create_progress_bar(downloaded_size, total_size)

            status_text = (
                f"<blockquote>"
                f"<b>Downloading...</b>\n\n"
                f"<code>{progress_bar}</code>\n"
                f"⏱️ Time: {self.helper.format_time(elapsed_time)} / {self.helper.format_time(estimated_total_time)}\n"
                f"🚀 Speed: {self.helper.format_size(speed)}/s\n"
                f"⏳ ETA: {self.helper.format_time(eta)}\n"
                f"📊 Size: {self.helper.format_size(downloaded_size)} / {self.helper.format_size(total_size)}"
                f"</blockquote>"
            )

            if status_msg is not None and status_msg.text != status_text:
                await status_msg.edit_text(status_text)

            await asyncio.sleep(2)

    async def download_file(self, url: str, output_name: str = None, status_msg=None, num_parts: int = 10) -> str:
        file_name = output_name or url.split('/')[-1]
        file_path = os.path.join(self.download_dir, file_name)

        # Get the file size
        async with aiohttp.ClientSession() as session:
            async with session.head(url) as response:
                total_size = int(response.headers.get('content-length', 0))

        # Open the file for writing
        with open(file_path, 'wb') as f:
            f.truncate(total_size)

        # Calculate part size
        part_size = total_size // num_parts

        # Initialize a shared progress tracker
        progress_tracker = [0]

        # Start the progress update coroutine
        progress_update_task = asyncio.create_task(self.update_progress(total_size, status_msg, progress_tracker))

        # Download the file in multiple parts concurrently
        await asyncio.gather(
            *[
                self.download_part(
                    url,
                    part * part_size,
                    (part + 1) * part_size - 1 if part < num_parts - 1 else total_size - 1,
                    file_path,
                    progress_tracker
                )
                for part in range(num_parts)
            ]
        )

        # Wait for the progress update task to complete
        await progress_update_task

        return file_path if os.path.exists(file_path) else None
