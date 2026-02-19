import telebot
from pymongo import MongoClient
from config import BOT_TOKEN, MONGO_URL

# টেলিগ্রাম বট ইনিশিয়ালাইজেশন
bot = telebot.TeleBot(BOT_TOKEN)

# ডাটাবেস কানেকশন
client = MongoClient(MONGO_URL)
db = client['smm_database']

# ডাটাবেসের কালেকশন (টেবিল) গুলো
users_col = db['users']
orders_col = db['orders']
config_col = db['settings']
