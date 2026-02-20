import telebot
from pymongo import MongoClient
from config import BOT_TOKEN, MONGO_URL

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
client = MongoClient(MONGO_URL)
db = client['smm_database']

users_col = db['users']
orders_col = db['orders']
config_col = db['settings']
tickets_col = db['tickets'] # সাপোর্ট টিকিটের জন্য নতুন
