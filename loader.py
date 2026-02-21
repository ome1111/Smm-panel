import telebot
from pymongo import MongoClient
from config import BOT_TOKEN, MONGO_URL

# Webhook এর জন্য threaded=False রাখা হয়েছে
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# MongoDB কানেকশন লিমিট (OOM Memory Crash ফিক্স করার জন্য)
client = MongoClient(MONGO_URL + ("&maxPoolSize=20" if "?" in MONGO_URL else "?maxPoolSize=20"))
db = client['smm_database']

users_col = db['users']
orders_col = db['orders']
config_col = db['settings']
tickets_col = db['tickets']
vouchers_col = db['vouchers']
logs_col = db['logs']  # 🔥 এই লাইনটি অ্যাড করা হয়েছে!
