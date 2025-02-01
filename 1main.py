import os
import uuid, time
import certifi
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, abort
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import telebot
from telebot import types
import requests
from flask import Flask, request, jsonify, abort, render_template
import secrets
import pytz
from datetime import datetime, timedelta
from datetime import datetime, timezone


# --- Load Environment Variables ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_URL2 = os.getenv("WEBHOOK_URL2")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID"))  # Bot owner ID

# --- MongoDB Setup ---
try:
    client = MongoClient(MONGO_URI, server_api=ServerApi('1'), tlsCAFile=certifi.where())
    db = client["media_shortener"]
    users_collection = db["users"]
    print("Connected to MongoDB successfully!")
except Exception as e:
    print(f"MongoDB connection error: {e}")
    exit(1)

# --- Telegram Bot Setup ---
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Helper Functions ---
def generate_unique_id(chat_id):
    """Generate a shorter unique subscription link for the user."""
    random_string = secrets.token_urlsafe(8)  # 8 characters long
    return f"{random_string}_{chat_id}"

def check_subscription(chat_id):
    """Check if the user's subscription token is valid."""
    user = users_collection.find_one({"chat_id": chat_id})
    if user and user.get("subscribed_until"):
        return datetime.utcnow() < user["subscribed_until"]
    return False

def save_subscription(chat_id, unique_id):
    """Save the user's subscription with a 2-minute expiration in IST."""
    ist = pytz.timezone('Asia/Kolkata')
    subscribed_until = datetime.now(timezone.utc) + timedelta(minutes=2)

    users_collection.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "subscribed_until": subscribed_until,
                "unique_id": unique_id,
                "verified": False
            }
        },
        upsert=True
    )
    print(f"User {chat_id} subscribed until {subscribed_until}")

def verify_token(unique_id):
    """Mark the subscription token as verified."""
    result = users_collection.update_one(
        {"unique_id": unique_id},
        {"$set": {"verified": True}}
    )
    return result.modified_count > 0

def is_token_verified(chat_id):
    """Check if the user's token is verified."""
    user = users_collection.find_one({"chat_id": chat_id})
    return user.get("verified", False) if user else False

def user_joined_channel(chat_id):
    """Check if the user has joined the required Telegram channel."""
    try:
        member_status = bot.get_chat_member(CHANNEL_ID, chat_id).status
        return member_status in ["member", "administrator"]
    except Exception as e:
        print(f"Error checking channel join status for {chat_id}: {e}")
        return False

def send_force_subscribe_message(chat_id):
    """Send a message prompting the user to join the channel."""
    try:
        channel_info = bot.get_chat(CHANNEL_ID)
        bot.send_message(
            chat_id,
            "*You need to join our compulsory channel😇 \n\nClick the link below to join 🔗 :*",
            reply_markup=types.InlineKeyboardMarkup(
                [[types.InlineKeyboardButton("Join Channel", url=f"https://t.me/{channel_info.username}")]]
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Failed to send subscription message: {e}")

def send_subscription_message(chat_id, unique_id):
    """Send a message prompting the user to subscribe."""
    try:
        subscription_link = f"{WEBHOOK_URL2}/verify/{unique_id}"
        greeting_text = (
            "Your Ads token has expired. Refresh your token and try again.\n\n"
            "Token Timeout: *2 Minutes*\n\n"
            "*What is the token?*\n"
            "This is an ads token. After completing the process, you can use the bot for 2 minutes."
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("Subscribe Here", url=subscription_link),
            types.InlineKeyboardButton("Close", callback_data="close")
        )
        bot.send_message(chat_id, greeting_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Failed to send subscription message: {e}")

def send_welcome_message(message):
    """Send a welcome message to the user."""
    user_name = message.from_user.first_name or message.from_user.username
    greeting_text = f"Hello, *{user_name}*! 😉\n\nYou need to Join Our Chat Channel From "
    markup = types.InlineKeyboardMarkup(row_width=2)
    channel_button = types.InlineKeyboardButton("Chat Channel", url="https://t.me/+tvWHQ58slElmNmQ1")
    close_button = types.InlineKeyboardButton("Close", callback_data="close")
    markup.add(channel_button, close_button)
    bot.send_message(message.chat.id, greeting_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=["start"])
def handle_start(message):
    """Handle the /start command and guide the user based on their subscription status."""
    chat_id = message.chat.id

    # Check if the user already has an active subscription
    if check_subscription(chat_id):
        if user_joined_channel(chat_id):
            # User has subscription and has joined the channel, send welcome message
            send_welcome_message(message)
        else:
            # User has subscription but hasn't joined the channel, send force-subscribe message
            send_force_subscribe_message(chat_id)
    else:
        # User does not have a subscription, prompt them to get one
        unique_id = generate_unique_id(chat_id)
        users_collection.update_one(
            {"chat_id": chat_id},
            {
                "$set": {
                    "chat_id": chat_id,
                    "unique_id": unique_id,
                    "subscribed_until": None,  # No subscription yet
                    "verified": False,
                }
            },
            upsert=True
        )
        send_subscription_message(chat_id, unique_id)


@bot.callback_query_handler(func=lambda call: call.data == "close")
def close_button(call):
    """Handle the 'Close' button."""
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception as e:
        print(f"Failed to delete message with buttons: {e}")

# --- Flask Routes ---
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def receive_updates():
    """Webhook endpoint to receive updates from Telegram."""
    try:
        json_string = request.get_data(as_text=True)
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
    except Exception as e:
        print(f"Failed to process update: {e}")
    return "", 200

@app.route("/verify/<unique_id>", methods=["GET"])
def verify(unique_id):
    """Serve the subscription verification page."""
    try:
        return render_template("verify.html", unique_id=unique_id)
    except Exception as e:
        print(f"Error rendering verification page: {e}")
        return "<h1>Something went wrong.</h1>", 500


@app.route("/verify_continue/<unique_id>", methods=["GET"])
def verify_continue(unique_id):
    """
    Serve the second verification page.
    After 5 seconds, redirects back to WEBHOOK_URL2.
    """
    try:
        return render_template("verify_continue.html", unique_id=unique_id, webhook_url2=WEBHOOK_URL2)
    except Exception as e:
        print(f"Error rendering continue page: {e}")
        return "<h1>Something went wrong.</h1>", 500


@app.route("/verify_final/<unique_id>", methods=["GET"])
def verify_final(unique_id):
    """
    Serve the final verification page with a 5-second timer and "Get Subscription" button.
    """
    try:
        user = users_collection.find_one({"unique_id": unique_id})
        if not user:
            return "<h1>Invalid or expired token. Please try again.</h1>", 400

        return render_template("complete_subscription.html", unique_id=unique_id)
    except Exception as e:
        print(f"Error rendering final verification page: {e}")
        return "<h1>Something went wrong.</h1>", 500


@app.route("/verify_success/<unique_id>", methods=["POST"])
def verify_success(unique_id):
    """
    Finalize subscription verification and notify the bot.
    """
    try:
        user = users_collection.find_one({"unique_id": unique_id})
        if not user:
            return jsonify({"message": "Invalid or expired token."}), 400

        # Update subscription status in the database
        subscribed_until = datetime.utcnow() + timedelta(minutes=2)
        users_collection.update_one(
            {"unique_id": unique_id},
            {"$set": {"verified": True, "subscribed_until": subscribed_until}}
        )

        # Notify the user via Telegram
        chat_id = user["chat_id"]
        bot.send_message(
            chat_id,
            "🎉 *Subscription successful!* You can now use the bot for the next 2 minutes. 😊",
            parse_mode="Markdown"
        )

        return jsonify({"message": "Subscription verified successfully!"}), 200
    except Exception as e:
        print(f"Error verifying subscription: {e}")
        return jsonify({"message": "An error occurred."}), 500



@app.route("/", methods=["GET"])
def index():
    return ""
    
# --- Main ---
def set_webhook(max_retries=3):
    """Forcefully set the webhook for the bot with retry logic."""
    webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{BOT_TOKEN}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url)
            response_json = response.json()
            print(f"Set Webhook Response (Attempt {attempt + 1}): {response_json}")
            
            if response_json.get("ok"):
                print("Webhook set successfully.")
                return True
            elif response_json.get("error_code") == 429:
                retry_after = response_json.get('parameters', {}).get('retry_after', 1)
                print(f"Too many requests. Retrying after {retry_after} seconds...")
                time.sleep(retry_after)
            else:
                print(f"Error setting webhook: {response_json.get('description')}")
                return False
        except Exception as e:
            print(f"Error while setting webhook: {e}")
            return False
    
    print("Max retries reached. Failed to set webhook.")
    return False

if __name__ == "__main__":
    print("Setting up webhook...")
    set_webhook()
    app.run(host="0.0.0.0", port=5000, debug=True)