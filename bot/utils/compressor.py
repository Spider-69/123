import asyncio
import os
import time
import re
import logging
from datetime import timedelta
import subprocess

LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

def format_time(seconds):
    return str(timedelta(seconds=int(seconds)))

def create_progress_bar(percentage, width=30):
    filled = int(width * percentage / 100)
    bar = '█' * filled + '░' * (width - filled)
    return f'[{bar}] {percentage:.1f}%'

async def compress_video(input_path, output_path, ffmpeg_code, status_msg, self):
    if not os.path.exists(input_path):
        await status_msg.edit_text("❌ Input file does not exist.")
        return False

    input_size = os.path.getsize(input_path) / (1024 * 1024)  # Size in MB

    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    # Generate unique progress file
    progress_file = os.path.join(output_dir, f"progress_{int(time.time())}.txt")
    with open(progress_file, 'w') as f:
        pass

    cmd = (
        f'ffmpeg -y -i "{input_path}" {ffmpeg_code} -progress {progress_file} '
        f'-loglevel error "{output_path}"'
    )
    LOGGER.info(f"Running FFmpeg command: {cmd}")

    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        self.current_processes.append(process)
    except Exception as e:
        await status_msg.edit_text(f"❌ Failed to start FFmpeg: {str(e)}")
        LOGGER.error(f"Failed to start FFmpeg process: {str(e)}")
        return False

    start_time = time.time()

    try:
        duration = extract_duration_from_ffmpeg(input_path)
        LOGGER.info(f"Video duration: {duration:.2f} seconds") if duration else LOGGER.warning("Failed to extract duration.")
        
        if duration is None:
            await status_msg.edit_text("⚠️ Failed to determine video duration. Progress tracking may be inaccurate.")

        is_done = False

        while process.returncode is None:
            await asyncio.sleep(10)

            with open(progress_file, 'r', encoding='utf-8') as file:
                text = file.read()
                
                time_in_us = re.findall("out_time_ms=(\\d+)", text)
                progress_matches = re.findall("progress=(\\w+)", text)
                
                if time_in_us:
                    elapsed_time = int(time_in_us[-1]) / 1_000_000
                else:
                    elapsed_time = 0
                
                if progress_matches and progress_matches[-1] == "end":
                    LOGGER.info("Compression complete.")
                    is_done = True
                    break

                if duration:
                    progress = (elapsed_time / duration) * 100
                    time_elapsed = time.time() - start_time
                    eta = ((duration - elapsed_time) / elapsed_time) * time_elapsed if elapsed_time > 0 else 0
                    
                    progress_bar = create_progress_bar(progress)
                    status_text = (
                        f"<blockquote>"
                        f"<b>🎥 Compressing Video...</b>\n\n"
                        f"<code>{progress_bar}</code>\n"
                        f"⏱️ Time: {format_time(time_elapsed)} / {format_time(duration)}\n"
                        f"⏳ ETA: {format_time(eta)}\n"
                        f"📊 Size: {input_size:.1f} MB"
                        f"</blockquote>"
                    )
                    
                    try:
                        await status_msg.edit_text(status_text)
                    except Exception as e:
                        LOGGER.error(f"Failed to update status: {str(e)}")

        await process.wait()
        
        if process.returncode == 0 and os.path.exists(output_path):
            output_size = os.path.getsize(output_path) / (1024 * 1024)
            compression_ratio = (1 - output_size / input_size) * 100 if input_size > 0 else 0
            final_status = (
                f"✅ Compression Complete!\n\n"
                f"📊 Original Size: {input_size:.1f} MB\n"
                f"📊 Final Size: {output_size:.1f} MB\n"
                f"📈 Compression: {compression_ratio:.1f}%\n"
                f"⏱️ Total Time: {format_time(time.time() - start_time)}"
            )
            await status_msg.edit_text(final_status)
            return True
        else:
            await status_msg.edit_text("❌ Compression failed.")
            return False

    except asyncio.CancelledError:
        LOGGER.info("Compression task was cancelled")
        process.terminate()
        await process.wait()
        raise

    except Exception as e:
        LOGGER.error(f"Unexpected error during compression: {str(e)}")
        await status_msg.edit_text(f"❌ Unexpected error: {str(e)}")
        return False

    finally:
        if process in self.current_processes:
            self.current_processes.remove(process)
        if os.path.exists(progress_file):
            os.remove(progress_file)

def extract_duration_from_ffmpeg(input_path):
    try:
        result = subprocess.run(
            ['ffmpeg', '-i', input_path],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True
        )
        match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        if match:
            hours, minutes, seconds = map(float, match.groups())
            return hours * 3600 + minutes * 60 + seconds
    except Exception as e:
        LOGGER.error(f"Failed to get duration: {e}")
    return None
