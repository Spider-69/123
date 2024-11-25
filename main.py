import logging
import os
import asyncio
from bot.client import Bot
from config import DOWNLOADS_DIR
from flask import Flask, jsonify

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO  # Change to DEBUG for detailed logging
)

# Flask app for health check
app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "ok", "message": "Bot is running"}), 200

async def main():
    # Create downloads directory if it doesn't exist
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    logging.info("Downloads directory checked/created.")

    # Start bot
    bot = Bot()

    # Initialize the database
    await bot.db.initialize()
    logging.info("Database initialized.")

    await bot.run()  # Ensure this calls the correct run method of the bot

if __name__ == '__main__':
    try:
        # Start Flask in a separate thread
        from threading import Thread
        flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=8000))
        flask_thread.daemon = True
        flask_thread.start()

        # Run the bot
        asyncio.run(main())  # Start the main async function

    except KeyboardInterrupt:
        logging.info("Bot shutdown initiated.")
    except Exception as e:
        logging.error(f"An error occurred while starting the bot: {e}")
