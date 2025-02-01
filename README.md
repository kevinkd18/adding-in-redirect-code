# adding-in-redirect-code

pip install -r requirements.txt

Okay! I'll now explain the code in **Hinglish** (mix of Hindi and English). 🚀  

This bot is built using **Flask**, **MongoDB**, and **Telegram Bot API**.  
It includes **subscription management**, **file storage**, and **auto-deletion** features.

---

# **📌 1. Importing Required Libraries**  
```python
import os
import uuid, time
import certifi
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, abort, render_template
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import telebot
from telebot import types
import requests
import secrets
import pytz
```
✅ **Kya ho raha hai?**  
- Sabhi **important libraries** import ho rahi hain:
  - `Flask` → Web server ke liye  
  - `telebot` → Telegram bot ke liye  
  - `pymongo` → MongoDB se connect hone ke liye  
  - `dotenv` → `.env` file se secrets load karne ke liye  

---

# **📌 2. Load Environment Variables**  
```python
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_URL2 = os.getenv("WEBHOOK_URL2")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_ID"))
```
✅ **Kya ho raha hai?**  
- `.env` file se **API keys aur configuration values** load ho rahi hain, jaise:  
  - **Telegram bot ka token**  
  - **MongoDB ka connection URL**  
  - **Telegram channel ID**  
  - **Webhook URL**  

---

# **📌 3. MongoDB se Connection Banaana**  
```python
try:
    client = MongoClient(MONGO_URI, server_api=ServerApi('1'), tlsCAFile=certifi.where())
    db = client["media_shortener"]
    users_collection = db["users"]
    print("Connected to MongoDB successfully!")
except Exception as e:
    print(f"MongoDB connection error: {e}")
    exit(1)
```
✅ **Kya ho raha hai?**  
- **MongoDB se connection** establish kar rahe hain.  
- Agar connection fail hota hai, toh **error print karke program exit** kar diya jayega.  

---

# **📌 4. Telegram Bot Setup**  
```python
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
```
✅ **Kya ho raha hai?**  
- **Telegram bot ka object create** ho raha hai.  
- **Flask web server start** ho raha hai.  

---

# **📌 5. Unique Subscription ID Generate Karna**  
```python
def generate_unique_id(chat_id):
    """Generate a unique subscription ID for a user."""
    random_string = secrets.token_urlsafe(8)
    return f"{random_string}_{chat_id}"
```
✅ **Kya ho raha hai?**  
- **Ek unique ID generate ho rahi hai** jo user ke `chat_id` ke saath store hoti hai.  
- `secrets.token_urlsafe(8)` **random string (8 characters) create** karta hai.  

---

# **📌 6. Check Karna Ki Subscription Active Hai Ya Nahi**  
```python
def check_subscription(chat_id):
    """Check if the user's subscription token is valid."""
    user = users_collection.find_one({"chat_id": chat_id})
    if user and user.get("subscribed_until"):
        return datetime.utcnow() < user["subscribed_until"]
    return False
```
✅ **Kya ho raha hai?**  
- **Database check karta hai ki user ka subscription valid hai ya expire ho gaya hai.**  
- **Agar valid hai, toh `True` return karta hai.**  

---

# **📌 7. User Ki Subscription Save Karna**  
```python
def save_subscription(chat_id, unique_id):
    """Save user's subscription with a 2-minute expiration."""
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
```
✅ **Kya ho raha hai?**  
- **User ka subscription 2 minutes ke liye activate ho raha hai.**  
- **MongoDB me user ki subscription expire hone ka time save ho raha hai.**  

---

# **📌 8. Token Verification Karna**  
```python
def verify_token(unique_id):
    """Mark the subscription token as verified."""
    result = users_collection.update_one(
        {"unique_id": unique_id},
        {"$set": {"verified": True}}
    )
    return result.modified_count > 0
```
✅ **Kya ho raha hai?**  
- **Database me update hota hai ki user ka subscription verified hai.**  
- **Agar update successful hota hai, toh `True` return karega.**  

---

# **📌 9. Check Karna Ki User Ne Channel Join Kiya Hai Ya Nahi**  
```python
def user_joined_channel(chat_id):
    """Check if the user has joined the required Telegram channel."""
    try:
        member_status = bot.get_chat_member(CHANNEL_ID, chat_id).status
        return member_status in ["member", "administrator"]
    except Exception as e:
        print(f"Error checking channel join status for {chat_id}: {e}")
        return False
```
✅ **Kya ho raha hai?**  
- **Telegram API se check karta hai ki user ne required channel join kiya hai ya nahi.**  

---

# **📌 10. Agar User Ne Channel Join Nahi Kiya, Toh Message Send Karna**  
```python
def send_force_subscribe_message(chat_id):
    """Send a message prompting the user to join the channel."""
    try:
        channel_info = bot.get_chat(CHANNEL_ID)
        bot.send_message(
            chat_id,
            "You need to join our compulsory channel...",
            reply_markup=types.InlineKeyboardMarkup(
                [[types.InlineKeyboardButton("Join Channel", url=f"https://t.me/{channel_info.username}")]]
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Failed to send subscription message: {e}")
```
✅ **Kya ho raha hai?**  
- **User ko force karta hai ki wo channel join kare.**  
- **Join button provide karta hai.**  

---

# **📌 11. `/start` Command Ko Handle Karna**  
```python
@bot.message_handler(commands=["start"])
def handle_start(message):
    """Handle the /start command and guide the user based on subscription status."""
    chat_id = message.chat.id
    if check_subscription(chat_id):
        if user_joined_channel(chat_id):
            send_welcome_message(message)
        else:
            send_force_subscribe_message(chat_id)
    else:
        unique_id = generate_unique_id(chat_id)
        users_collection.update_one(
            {"chat_id": chat_id},
            {"$set": {"unique_id": unique_id, "subscribed_until": None, "verified": False}},
            upsert=True
        )
        send_subscription_message(chat_id, unique_id)
```
✅ **Kya ho raha hai?**  
- **Agar user ka subscription valid hai, toh welcome message bhejta hai.**  
- **Agar valid nahi hai, toh subscription link provide karta hai.**  

---

# **📌 12. Flask Server Start Karna**  
```python
if __name__ == "__main__":
    print("Setting up webhook...")
    set_webhook()
    app.run(host="0.0.0.0", port=5000, debug=True)
```
✅ **Kya ho raha hai?**  
- **Webhook setup karta hai aur Flask server run karta hai.**  

---

### **🚀 Ab Aapka Bot Fully Explained Hai!**  
Agar koi question hai ya kuch aur changes chahiye, toh batao! 😃