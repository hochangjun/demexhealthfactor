import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp
import json
import asyncio
from datetime import datetime

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
# Load configuration from environment variables
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
USER_DATA_FILE = os.environ.get('USER_DATA_FILE', 'demexhealthchatids.json')
CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', 3600))  # Default to 1 hour

# File to store user data
USER_DATA_FILE = 'demexhealthchatids.json'

# Load user data from file
def load_user_data():
    try:
        with open(USER_DATA_FILE, 'r') as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
            else:
                return {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Save user data to file
def save_user_data(data):
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(data, f)

# Global variable to store user data
user_data = load_user_data()

# Function to check health factor
async def check_health_factor(address):
    url = f"https://api.carbon.network/carbon/cdp/v1/health_factor/{address}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data.get('health_factor', 0))
                else:
                    logger.error(f"Error fetching health factor: HTTP {response.status}")
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"Network error when fetching health factor: {e}")
            return None

# Function to handle the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to the Demex Health Factor Monitor Bot!\n\n"
        "Here are the available commands:\n"
        "/start - Show this help message\n"
        "/monitor <threshold> <address> - Start monitoring an address\n"
        "/check - Check your current monitoring settings\n"
        "/stop - Stop monitoring\n\n"
        "You can also simply paste a Demex address to check its current health factor.\n\n"
        "DISCLAIMER: This bot is not officially affiliated with or endorsed by Demex. "
        "It is an independent tool created for informational purposes only. "
        "The bot is not guaranteed to be always accurate or available. "
        "Users should not rely solely on this bot for making financial decisions."
    )

# Function to handle /monitor command
async def monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /monitor <threshold> <address>")
        return

    chat_id = str(update.effective_chat.id)  # Convert to string for JSON compatibility
    threshold = float(context.args[0])
    address = context.args[1]

    if not address.startswith('swth'):
        await update.message.reply_text("Invalid address. Demex addresses must start with 'swth'.")
        return

    if chat_id in user_data:
        user_data[chat_id]['threshold'] = threshold
        user_data[chat_id]['address'] = address
        message = f"Updated monitoring for address {address} with new threshold {threshold}"
    else:
        user_data[chat_id] = {'threshold': threshold, 'address': address}
        message = f"Started monitoring address {address} with threshold {threshold}"

    save_user_data(user_data)
    await update.message.reply_text(message)
    await check_and_notify(context, chat_id)

# Function to handle /check command
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if chat_id in user_data:
        threshold = user_data[chat_id]['threshold']
        address = user_data[chat_id]['address']
        health_factor = await check_health_factor(address)
        
        if health_factor is not None:
            await update.message.reply_text(
                f"Currently monitoring address {address}\n"
                f"Threshold: {threshold}\n"
                f"Current health factor: {health_factor}"
            )
        else:
            await update.message.reply_text(
                f"Currently monitoring address {address}\n"
                f"Threshold: {threshold}\n"
                f"Unable to fetch current health factor. Please try again later."
            )
    else:
        await update.message.reply_text("You are not currently monitoring any address.")

# Function to handle /stop command
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if chat_id in user_data:
        del user_data[chat_id]
        save_user_data(user_data)
        await update.message.reply_text("Monitoring stopped.")
    else:
        await update.message.reply_text("You were not monitoring any address.")

# Function to handle direct address input
async def handle_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    address = update.message.text.strip()
    if not address.startswith('swth'):
        await update.message.reply_text("Invalid address. Demex addresses must start with 'swth'.")
        return

    health_factor = await check_health_factor(address)
    if health_factor is not None:
        await update.message.reply_text(f"Current health factor for {address}: {health_factor}")
    else:
        await update.message.reply_text("Unable to fetch health factor. Please try again later.")
    
    logger.info(f"Health factor check requested for address: {address}")

# Function to check health factor and notify user
async def check_and_notify(context: ContextTypes.DEFAULT_TYPE, chat_id: str) -> None:
    if chat_id not in user_data:
        return

    address = user_data[chat_id]['address']
    threshold = user_data[chat_id]['threshold']
    health_factor = await check_health_factor(address)

    if health_factor is not None:
        if health_factor < threshold:
            await context.bot.send_message(
                chat_id=int(chat_id),  # Convert back to int for sending message
                text=f"Alert: Health factor for {address} is {health_factor}, which is below your threshold of {threshold}!\n"
                     f"Check your position here: https://app.dem.exchange/nitron"
            )
    else:
        await context.bot.send_message(
            chat_id=int(chat_id),  # Convert back to int for sending message
            text=f"Unable to fetch health factor for {address}. Will try again in the next check."
        )

# Function to periodically check health factors
async def periodic_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    for chat_id in user_data:
        await check_and_notify(context, chat_id)

def main() -> None:
    if not TOKEN:
        logger.error("No bot token provided. Please set the TELEGRAM_BOT_TOKEN environment variable.")
        return

    application = Application.builder().token(TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("monitor", monitor))
    application.add_handler(CommandHandler("check", check))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_address))

    # Set up periodic task
    job_queue = application.job_queue
    job_queue.run_repeating(periodic_check, interval=CHECK_INTERVAL, first=5)

    logger.info("Bot started. Polling for updates...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
