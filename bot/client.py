from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
import os
import sys
import asyncio
import re
from .database.db_manager import Database
from .utils.downloader import get_video_formats, download_video
from .utils.compressor import compress_video
from .utils.helpers import Helper, create_format_buttons, clean_files, get_video_duration, take_screenshot
from config import API_ID, API_HASH, BOT_TOKEN, DUMP_CHANNEL, DOWNLOADS_DIR, AUTH_USERS
import logging
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import time
from .utils.l_download import HTTPDownloader
# Set up logging
logging.basicConfig(level=logging.INFO)


ENCODE_DIR = os.path.join(DOWNLOADS_DIR, "Encode")
os.makedirs(ENCODE_DIR, exist_ok=True)

class Bot:
    def __init__(self):
        logging.info("Initializing bot...")
        self.app = Client(
            "video_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN
        )
        self.db = Database()
        self.tasks = []
        self.video_urls = {}
        self.helper = Helper()  # Initialize the Helper class
        self.setup_handlers()
        self.download_tasks = {}
        self.current_processes = []
        self.http_downloader = HTTPDownloader() 

    def setup_handlers(self):
        logging.info("Setting up handlers...")

        @self.app.on_message(filters.command("start"))
        async def start_command(_, message: Message):
            logging.info("Received /start command")
            await message.reply_text(
                "Hello! I can help you download and compress videos.\n"
                "Commands:\n"
                "/yl <url> - Download YouTube video\n"
                "/l <url> - Download Direct files\n"
                "/ylc <url> - Download YouTube video and Compress them\n"
                "/set <ffmpeg_code> - Set custom FFmpeg code\n"
                "/add - Reply to video/document to compress\n"
                "/cancel - Cancel ongoing tasks\n"   
            )
        @self.app.on_message(filters.command("l"))
        async def download_and_upload(client: Client, message: Message):
            url = message.text.split(" ", 1)[1]
            output_name = None
            file_path = None  # Initialize to None to handle potential errors safely

            if "-n" in url:
                parts = url.split("-n", 1)
                url = parts[0].strip()
                output_name = parts[1].strip()

            status_msg = await message.reply_text("🚀 Starting download...")

            try:
                # Download the file
                file_path = await self.http_downloader.download_file(url, output_name, status_msg)

                if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    # Upload the file as a document
                    try:
                        upload_msg = await client.send_document(
                            chat_id=message.chat.id,
                            document=file_path,
                            caption=f"Downloaded {output_name or os.path.basename(file_path)}",
                            progress=self.helper.progress_for_pyrogram,
                            progress_args=(status_msg, time.time(), "Uploading to user")
                        )

                        # Forward the uploaded file to the dump channel
                        await client.forward_messages(
                            chat_id=DUMP_CHANNEL,
                            from_chat_id=message.chat.id,
                            message_ids=upload_msg.id
                        )

                        await status_msg.edit_text("✅ Download and upload complete!")
                    except Exception as e:
                        logging.error(f"Error during upload: {e}")
                        await status_msg.edit_text("❌ Upload failed.")
                else:
                    logging.error("Download failed or file is empty.")
                    await status_msg.edit_text("❌ Download failed or file is empty.")
            except Exception as e:
                logging.error(f"Error during download/upload process: {e}")
                await status_msg.edit_text("❌ An error occurred during the process.")
            finally:
                # Clean up by removing the downloaded file if it exists
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    
        @self.app.on_message(filters.command("restart"))
        async def restart_bot(_, message: Message):
            logging.info("Received /restart command")
            if self.is_restarting:
                await message.reply_text("Restart already in progress...")
                return

            self.is_restarting = True
            status_msg = await message.reply_text("🔄 Restarting bot...")

            try:
                await self.stop_all_operations()
                await status_msg.edit_text("🧹 Cleaning up resources...")
                await asyncio.sleep(2)
                await status_msg.edit_text("🔄 Rebooting bot process...")
                logging.info("Rebooting bot process")
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception as e:
                await status_msg.edit_text(f"❌ Error during restart: {str(e)}")
                logging.error(f"Error in restart_bot: {e}")
            finally:
                self.is_restarting = False

        @self.app.on_message(filters.command("ylc"))
        async def youtube_compressed_command(_, message: Message):
            logging.info("Received /ylc command")
            if len(message.command) < 2:
                await message.reply_text("Please provide a YouTube URL")
                return

            status_msg = await message.reply_text("Fetching video information...")
            try:
                url = message.text.split(None, 1)[1]
                formats, title = await get_video_formats(url)
                keyboard = create_format_buttons(formats, prefix="dlc_")

                await status_msg.edit_text(
                    f"Select format for: {title}",
                    reply_markup=keyboard
                )
                user_id = message.from_user.id
                self.video_urls[user_id] = url
            except Exception as e:
                await status_msg.edit_text(f"Error: {str(e)}")
                logging.error(f"Error in youtube_compressed_command: {e}")

        @self.app.on_callback_query(filters.regex(r"^dlc_"))
        async def download_compressed_callback(_, callback_query: CallbackQuery):
            format_id = callback_query.data.split("_")[1]
            user_id = callback_query.from_user.id
            url = self.video_urls.get(user_id)

            if not url:
                await callback_query.answer("Session expired. Please try again.", show_alert=True)
                return

            await callback_query.answer("Processing...")
            status_msg = await callback_query.message.reply_text("Starting download process...")

            input_path = None
            output_path = None
            start_time = time.time()

            try:
                formats, title = await get_video_formats(url)
                sanitized_title = re.sub(r'[^\w\-_\.]', '_', title).strip()
                input_path = os.path.join(DOWNLOADS_DIR, f"{sanitized_title}.mp4")
                output_path = os.path.join(ENCODE_DIR, f"{sanitized_title}_Compressed.mp4")

                # Create and store the download task
                download_task = asyncio.create_task(
                    download_video(url, format_id, input_path, status_msg)
                )
                self.download_tasks[user_id] = download_task
                success = await download_task

                if success and os.path.exists(input_path):
                    duration = await get_video_duration(input_path)
                    thumb_image_path = await take_screenshot(input_path)

                    await status_msg.edit_text("✅ Download complete! Preparing to upload...")

                    await self.app.send_video(
                        DUMP_CHANNEL,
                        input_path,
                        progress=self.helper.progress_for_pyrogram,
                        duration=duration,
                        caption=f"{sanitized_title}\nDuration: {duration} seconds",
                        thumb=thumb_image_path,
                        width=1280,
                        height=720,
                        progress_args=(status_msg, start_time, "📤 Uploading to dump channel")
                    )
                    
                    ffmpeg_code = await self.db.get_ffmpeg_code(user_id)
                    await status_msg.edit_text("Starting compression process...")

                    compress_task = asyncio.create_task(
                        compress_video(input_path, output_path, ffmpeg_code, status_msg, self)
                    )
                    self.tasks.append(compress_task)
                    success = await compress_task

                    if success and os.path.exists(output_path):
                        duration = await get_video_duration(output_path)
                        thumb_image_path = await take_screenshot(output_path)

                        await self.app.send_video(
                            callback_query.message.chat.id,
                            output_path,
                            caption=f"{sanitized_title} (Smashed)\nDuration: {duration} seconds",
                            duration=duration,
                            thumb=thumb_image_path,
                            width=1280,
                            height=720,
                            reply_to_message_id=callback_query.message.id,
                            progress=self.helper.progress_for_pyrogram,
                            progress_args=(status_msg, start_time, "📤 Uploading compressed video")
                        )
                        await status_msg.delete()
                        if os.path.exists(thumb_image_path):
                            os.remove(thumb_image_path)
                else:
                    await status_msg.edit_text("Download failed!")

            except asyncio.CancelledError:
                await status_msg.edit_text("Download cancelled!")
                raise
            except Exception as e:
                await status_msg.edit_text(f"Error: {str(e)}")
                logging.error(f"Error in download_compressed_callback: {e}")
            finally:
                clean_files(input_path, output_path)
                if user_id in self.video_urls:
                    del self.video_urls[user_id]
                if user_id in self.download_tasks:
                    del self.download_tasks[user_id]

                    
        @self.app.on_message(filters.command("add") & filters.reply)
        async def compress_command(_, message: Message):
            replied = message.reply_to_message
            if not (replied.video or replied.document):
                await message.reply_text("Please reply to a video/document")
                return

            status_msg = await message.reply_text("Starting process...")
            input_path = None
            output_path = None
            start_time = time.time()

            try:
                title = replied.video.file_name if replied.video else replied.document.file_name
                sanitized_title = re.sub(r'[^\w\-_\.]', '_', title).strip()
                input_path = os.path.join(DOWNLOADS_DIR, f"{sanitized_title}.mp4")
                
                # Download with progress tracking
                await replied.download(
                    file_name=input_path,
                    progress=self.helper.progress_for_pyrogram,
                    progress_args=(status_msg, start_time, "Downloading video")
                )

                await replied.forward(DUMP_CHANNEL)

                output_path = os.path.join(ENCODE_DIR, f"{sanitized_title}_Smashed.mp4")
                ffmpeg_code = await self.db.get_ffmpeg_code(message.from_user.id)
                
                await status_msg.edit_text("Starting compression process...")
                compress_task = asyncio.create_task(
                    compress_video(input_path, output_path, ffmpeg_code, status_msg,self)
                )
                self.tasks.append(compress_task)
                await compress_task

                if os.path.exists(output_path):
                    # Reset start time for final upload
                    start_time = time.time()
                    # Get duration and thumbnail
                    duration = await get_video_duration(output_path)
                    thumb_image_path = await take_screenshot(output_path)

                    await self.app.send_video(
                        message.chat.id,
                        output_path,
                        caption=f"📹 {sanitized_title} (Smashed)\n⏱️ Duration: {duration} seconds",
                        duration=duration,
                        thumb=thumb_image_path,
                        width=1280,
                        height=720,
                        reply_to_message_id=message.id,
                        progress=self.helper.progress_for_pyrogram,
                        progress_args=(status_msg, start_time, "📤 Uploading compressed video")
                    )
                    await status_msg.delete()
                    if os.path.exists(thumb_image_path):
                        os.remove(thumb_image_path)

            except Exception as e:
                await status_msg.edit_text(f"Error: {str(e)}")
                logging.error(f"Error in compress_command: {e}")
            finally:
                clean_files(input_path, output_path)
                self.tasks.clear()

        @self.app.on_message(filters.command("get"))
        async def get_ffmpeg(_, message: Message):
            logging.info("Received /get command")
            try:
                user_id = message.from_user.id
                ffmpeg_code = await self.db.get_ffmpeg_code(user_id)
                
                if ffmpeg_code:
                    await message.reply_text(
                        f"Your current FFmpeg code is:\n<code>{ffmpeg_code}</code>",
                    )
                else:
                    await message.reply_text(
                        "You haven't set any FFmpeg code yet.\n"
                        "Use /set <ffmpeg_code> to set your compression preferences.",
                    )
            except Exception as e:
                await message.reply_text(f"Error retrieving FFmpeg code: {str(e)}")
                logging.error(f"Error in get_ffmpeg command: {e}")

        @self.app.on_message(filters.command("set"))
        async def set_ffmpeg(_, message: Message):
            logging.info("Received /set command")
            if len(message.command) < 2:
                await message.reply_text("Please provide FFmpeg code.")
                return

            user_id = message.from_user.id
            ffmpeg_code = message.text.split(None, 1)[1]

            await self.db.set_ffmpeg_code(user_id, ffmpeg_code)
            await message.reply_text("Your FFmpeg code has been set!")

        @self.app.on_message(filters.command("cancel"))

        async def cancel_tasks(_, message: Message):
            logging.info("Received /cancel command")
            user_id = message.from_user.id
            
            # Cancel download task if exists
            if user_id in self.download_tasks:
                self.download_tasks[user_id].cancel()
                del self.download_tasks[user_id]
            
            # Cancel other tasks
            if not self.tasks:
                await message.reply_text("No ongoing tasks to cancel.")
                return
            
            for task in self.tasks:
                task.cancel()
            self.tasks.clear()
            await message.reply_text("All ongoing tasks have been canceled.")


        @self.app.on_message(filters.command("yl"))
        async def youtube_no_compress_command(_, message: Message):
            logging.info("Received /yl command")
            if len(message.command) < 2:
                await message.reply_text("Please provide a YouTube URL")
                return

            status_msg = await message.reply_text("Fetching video information...")
            try:
                url = message.text.split(None, 1)[1]
                formats, title = await get_video_formats(url)
                keyboard = create_format_buttons(formats, prefix="dl_nocompress_")

                await status_msg.edit_text(
                    f"Select format for: {title}",
                    reply_markup=keyboard
                )
                user_id = message.from_user.id
                self.video_urls[user_id] = url
            except Exception as e:
                await status_msg.edit_text(f"Error: {str(e)}")
                logging.error(f"Error in youtube_no_compress_command: {e}")

        @self.app.on_callback_query(filters.regex(r"^dl_nocompress_"))
        async def download_no_compress_callback(_, callback_query: CallbackQuery):
            format_id = callback_query.data.split("_")[2]
            user_id = callback_query.from_user.id
            url = self.video_urls.get(user_id)

            if not url:
                await callback_query.answer("Session expired. Please try again.", show_alert=True)
                return

            await callback_query.answer("Processing...")
            status_msg = await callback_query.message.reply_text("Starting download process...")

            input_path = None
            try:
                formats, title = await get_video_formats(url)
                sanitized_title = re.sub(r'[^\w\-_\.]', '_', title).strip()
                input_path = os.path.join(DOWNLOADS_DIR, f"{sanitized_title}.mp4")

                download_task = asyncio.create_task(
                    download_video(url, format_id, input_path, status_msg)
                )
                self.download_tasks[user_id] = download_task
                success = await download_task

                if success and os.path.exists(input_path):
                    duration = await get_video_duration(input_path)
                    thumb_image_path = await take_screenshot(input_path)

                    await status_msg.edit_text("✅ Download complete! Preparing to upload...")

                    # Upload the video to the user
                    upload_msg = await self.app.send_video(
                        callback_query.message.chat.id,
                        input_path,
                        progress=self.helper.progress_for_pyrogram,
                        duration=duration,
                        thumb=thumb_image_path,
                        width=1280,
                        height=720,
                        progress_args=(status_msg, time.time(), "📤 Uploading to user")
                    )

                    # Now forward the uploaded video to the dump channel
                    await self.app.forward_messages(
                        chat_id=DUMP_CHANNEL,
                        from_chat_id=callback_query.message.chat.id,
                        message_ids=upload_msg.id
                    )

                    await status_msg.delete()
                    if os.path.exists(thumb_image_path):
                        os.remove(thumb_image_path)
                else:
                    await status_msg.edit_text("Download failed!")

            except asyncio.CancelledError:
                await status_msg.edit_text("Download cancelled!")
                raise
            except Exception as e:
                await status_msg.edit_text(f"Error: {str(e)}")
                logging.error(f"Error in download_no_compress_callback: {e}")
            finally:
                clean_files(input_path)
                if user_id in self.video_urls:
                    del self.video_urls[user_id]
                if user_id in self.download_tasks:
                    del self.download_tasks[user_id]




    async def run(self):
        await self.app.start()
        logging.info("Bot is running...")
        await asyncio.Event().wait()

if __name__ == "__main__":
    bot = Bot()
    asyncio.run(bot.run())
