import telebot
from pymongo import MongoClient
from config import BOT_TOKEN, MONGO_URL

# Bot Initializer
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# Database Connection
client = MongoClient(MONGO_URL)
db = client['smm_database']

# Collections
users_col = db['users']
orders_col = db['orders']
config_col = db['settings']
tickets_col = db['tickets']
vouchers_col = db['vouchers']
logs_col = db['logs']
