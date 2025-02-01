import os
import uuid, time, secrets, logging, threading
import certifi
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import telebot
from telebot import types
import requests

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_URL2 = os.getenv("WEBHOOK_URL2")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID"))

PRIVATE_GROUP_ID = os.getenv("PRIVATE_GROUP_ID")
if PRIVATE_GROUP_ID:
    PRIVATE_GROUP_ID = int(PRIVATE_GROUP_ID)
else:
    PRIVATE_GROUP_ID = None

ADMINS = os.getenv("ADMINS")
if ADMINS:
    ADMINS = list(map(int, ADMINS.split(',')))
else:
    ADMINS = []

try:
    client = MongoClient(MONGO_URI, server_api=ServerApi('1'), tlsCAFile=certifi.where())
    db = client["media_shortener"]
    users_collection = db["users"]
    file_storage_collection = db["file_storage"]
    logging.info("Connected to MongoDB successfully!")
except Exception as e:
    logging.error(f"MongoDB connection error: {e}")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

def generate_unique_id(chat_id):
    random_string = secrets.token_urlsafe(8)
    return f"{random_string}_{chat_id}"

def check_subscription(chat_id):
    user = users_collection.find_one({"chat_id": chat_id})
    if user and user.get("subscribed_until"):
        return datetime.utcnow() < user["subscribed_until"]
    return False

def user_joined_channel(chat_id, group_id):
    if group_id == -1002398328247:
        logging.info(f"Skipping membership check for group {group_id}.")
        return True
    if not group_id:
        logging.info("No group provided for membership check.")
        return False
    try:
        member_status = bot.get_chat_member(group_id, chat_id).status
        return member_status in ["member", "administrator"]
    except Exception as e:
        logging.error(f"Error checking membership for {chat_id} in {group_id}: {e}")
        return False

def send_force_subscribe_message(chat_id):
    try:
        channel_info = bot.get_chat(CHANNEL_ID)
        markup = types.InlineKeyboardMarkup([[types.InlineKeyboardButton("Join Channel", url=f"https://t.me/{channel_info.username}")]])
        bot.send_message(chat_id, "*You need to join our compulsory channel 😇\n\nClick the link below to join 🔗:*", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Failed to send force-join message: {e}")

def send_subscription_message(chat_id, unique_id, file_token=None):
    subscription_link = f"{WEBHOOK_URL2}/verify/{unique_id}"
    if file_token:
        subscription_link += f"?file_token={file_token}"
    greeting_text = ("Your Ads token has expired or you have not subscribed yet. Please refresh your token and subscribe.\n\n"
                     "Token Timeout: *2 Minutes*\n\n"
                     "*What is the token?*\n"
                     "This is an ads token. After completing the process, you can use the bot for 2 minutes.")
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("Subscribe Here", url=subscription_link),
               types.InlineKeyboardButton("Close", callback_data="close"))
    try:
        bot.send_message(chat_id, greeting_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        logging.error(f"Failed to send subscription message: {e}")

def send_welcome_message(message):
    user_name = message.from_user.first_name or message.from_user.username
    greeting_text = f"Hello, *{user_name}*! 😉\n\nYou have successfully subscribed and joined our channel."
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("Chat Channel", url="https://t.me/+tvWHQ58slElmNmQ1"),
               types.InlineKeyboardButton("Close", callback_data="close"))
    try:
        bot.send_message(message.chat.id, greeting_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        logging.error(f"Failed to send welcome message: {e}")

@bot.message_handler(commands=["start"])
def handle_start(message):
    chat_id = message.chat.id
    text_parts = message.text.split(" ")
    if len(text_parts) > 1:
        file_token = text_parts[1]
        file_info = load_file_storage(file_token)
        if file_info:
            if not check_subscription(chat_id):
                new_token = generate_unique_id(chat_id)
                subscription_record = {"chat_id": chat_id, "unique_id": new_token, "subscribed_until": None, "verified": False}
                users_collection.update_one({"chat_id": chat_id}, {"$set": subscription_record}, upsert=True)
                logging.info(f"Updated subscription record for file mode: {subscription_record}")
                send_subscription_message(chat_id, new_token, file_token=file_token)
                return
            if chat_id != OWNER_ID and not user_joined_channel(chat_id, CHANNEL_ID):
                send_force_subscribe_message(chat_id)
                return
            send_file(chat_id, file_info[0], file_info[1])
        else:
            bot.send_message(chat_id, "Invalid or expired link. No file found.")
        return
    if check_subscription(chat_id):
        if chat_id == OWNER_ID or user_joined_channel(chat_id, CHANNEL_ID):
            send_welcome_message(message)
        else:
            send_force_subscribe_message(chat_id)
    else:
        new_token = generate_unique_id(chat_id)
        subscription_record = {"chat_id": chat_id, "unique_id": new_token, "subscribed_until": None, "verified": False}
        users_collection.update_one({"chat_id": chat_id}, {"$set": subscription_record}, upsert=True)
        logging.info(f"Subscription record created: {subscription_record}")
        send_subscription_message(chat_id, new_token)

def save_file_storage(unique_id, file_info):
    try:
        file_storage_collection.update_one({'unique_id': unique_id}, {'$set': {'file_id': file_info[0], 'file_type': file_info[1]}}, upsert=True)
        logging.info(f"File {unique_id} saved to the database.")
    except Exception as e:
        logging.error(f"Failed to save file {unique_id}: {e}")

def load_file_storage(unique_id):
    try:
        file_info = file_storage_collection.find_one({'unique_id': unique_id})
        if file_info:
            return (file_info['file_id'], file_info['file_type'])
        else:
            return None
    except Exception as e:
        logging.error(f"Failed to load file {unique_id}: {e}")
        return None

@bot.callback_query_handler(func=lambda call: call.data == "close")
def close_button(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception as e:
        logging.error(f"Failed to delete message with buttons: {e}")

def send_file(chat_id, file_id, file_type):
    try:
        sent_message = None
        if file_type == 'photo':
            sent_message = bot.send_photo(chat_id, file_id, protect_content=True)
        elif file_type == 'video':
            sent_message = bot.send_video(chat_id, file_id, protect_content=True)
        elif file_type == 'document':
            sent_message = bot.send_document(chat_id, file_id, protect_content=True)
        elif file_type == 'audio':
            sent_message = bot.send_audio(chat_id, file_id, protect_content=True)
        elif file_type == 'voice':
            sent_message = bot.send_voice(chat_id, file_id, protect_content=True)
        if sent_message:
            schedule_delete_message(chat_id, sent_message.message_id, delay=1200)
    except Exception as e:
        logging.error(f"Failed to send the file: {e}")

def schedule_delete_message(chat_id, message_id, delay=1200):
    def delete_msg():
        try:
            bot.delete_message(chat_id, message_id)
            logging.info(f"Message {message_id} deleted from chat {chat_id}")
        except Exception as e:
            logging.error(f"Failed to delete message {message_id}: {e}")
    threading.Timer(delay, delete_msg).start()

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def receive_updates():
    try:
        json_string = request.get_data(as_text=True)
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
    except Exception as e:
        logging.error(f"Failed to process update: {e}")
    return "", 200

@app.route("/verify/<unique_id>", methods=["GET"])
def verify(unique_id):
    try:
        return render_template("verify.html", unique_id=unique_id)
    except Exception as e:
        logging.error(f"Error rendering verification page: {e}")
        return "<h1>Something went wrong.</h1>", 500

@app.route("/verify_continue/<unique_id>", methods=["GET"])
def verify_continue(unique_id):
    try:
        return render_template("verify_continue.html", unique_id=unique_id, webhook_url2=WEBHOOK_URL2)
    except Exception as e:
        logging.error(f"Error rendering continue page: {e}")
        return "<h1>Something went wrong.</h1>", 500

@app.route("/verify_final/<unique_id>", methods=["GET"])
def verify_final(unique_id):
    try:
        user = users_collection.find_one({"unique_id": unique_id})
        if not user:
            return "<h1>Invalid or expired token. Please try again.</h1>", 400
        return render_template("complete_subscription.html", unique_id=unique_id)
    except Exception as e:
        logging.error(f"Error rendering final verification page: {e}")
        return "<h1>Something went wrong.</h1>", 500

@app.route("/verify_success/<unique_id>", methods=["POST"])
def verify_success(unique_id):
    try:
        user = users_collection.find_one({"unique_id": unique_id})
        if not user:
            return jsonify({"message": "Invalid or expired token."}), 400
        subscribed_until = datetime.utcnow() + timedelta(minutes=10)
        users_collection.update_one({"unique_id": unique_id}, {"$set": {"verified": True, "subscribed_until": subscribed_until}})
        chat_id = user["chat_id"]
        bot.send_message(chat_id, "🎉 *Subscription successful!* You can now use the bot for the next 10 minutes. 😊", parse_mode="Markdown")
        file_token = request.args.get("file_token")
        if file_token:
            file_info = load_file_storage(file_token)
            if file_info:
                send_file(chat_id, file_info[0], file_info[1])
            else:
                bot.send_message(chat_id, "File info not found or expired.")
        return jsonify({"message": "Subscription verified successfully!"}), 200
    except Exception as e:
        logging.error(f"Error verifying subscription: {e}")
        return jsonify({"message": "An error occurred."}), 500

@app.route("/", methods=["GET"])
def index():
    return ""

@bot.message_handler(func=lambda message: (PRIVATE_GROUP_ID and message.chat.id == PRIVATE_GROUP_ID) and (message.from_user.id in ADMINS),
                     content_types=['photo', 'video', 'document', 'audio', 'voice'])
def handle_files(message):
    try:
        file_info = None
        if message.photo:
            file_info = (message.photo[-1].file_id, 'photo')
        elif message.video:
            file_info = (message.video.file_id, 'video')
        elif message.document:
            file_info = (message.document.file_id, 'document')
        elif message.audio:
            file_info = (message.audio.file_id, 'audio')
        elif message.voice:
            file_info = (message.voice.file_id, 'voice')
        if file_info:
            unique_id = str(uuid.uuid4())
            while load_file_storage(unique_id):
                unique_id = str(uuid.uuid4())
            save_file_storage(unique_id, file_info)
            shareable_link = f"https://t.me/{bot.get_me().username}?start={unique_id}"
            processing_msg = bot.send_message(message.chat.id, WAIT_MSG_HANDLE_FILES, parse_mode='HTML')
            bot.edit_message_text(f"<b>{message.from_user.first_name}, your file is stored!</b>\n\n"
                                  f"<code>Use this link to access it 🔗 :\n||{shareable_link}||\n\nLeave Reaction 🤪😇</code>\n\n{shareable_link}",
                                  message.chat.id, processing_msg.message_id, parse_mode='HTML')
        else:
            bot.reply_to(message, 'Failed to process the file.')
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

WAIT_MSG_HANDLE_FILES = "<b>⌛ Please Wait...</b>"

def set_webhook(max_retries=3):
    webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
    for attempt in range(max_retries):
        try:
            response = requests.get(url)
            response_json = response.json()
            logging.info(f"Set Webhook Response (Attempt {attempt + 1}): {response_json}")
            if response_json.get("ok"):
                logging.info("Webhook set successfully.")
                return True
            elif response_json.get("error_code") == 429:
                retry_after = response_json.get('parameters', {}).get('retry_after', 1)
                logging.info(f"Too many requests. Retrying after {retry_after} seconds...")
                time.sleep(retry_after)
            else:
                logging.error(f"Error setting webhook: {response_json.get('description')}")
                return False
        except Exception as e:
            logging.error(f"Error while setting webhook: {e}")
            return False
    logging.error("Max retries reached. Failed to set webhook.")
    return False

if __name__ == "__main__":
    logging.info("Setting up webhook...")
    set_webhook()
    app.run(host="0.0.0.0", port=5000)
