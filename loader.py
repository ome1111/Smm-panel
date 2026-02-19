import telebot
from pymongo import MongoClient
from config import BOT_TOKEN, MONGO_URL

# ==========================================
# ১. টেলিগ্রাম বট কানেকশন
# ==========================================
# Webhook-এর জন্য threaded=False রাখা বাধ্যতামূলক, 
# যাতে সাইলেন্ট এরর না হয় এবং লগে সমস্যা ধরা পড়ে।
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# ==========================================
# ২. ডাটাবেস (MongoDB) কানেকশন
# ==========================================
# MongoDB ক্লাস্টারের সাথে কানেক্ট করা হচ্ছে
client = MongoClient(MONGO_URL)
db = client['smm_database']

# ==========================================
# ৩. ডাটাবেস কালেকশন (টেবিল)
# ==========================================
users_col = db['users']
orders_col = db['orders']
config_col = db['settings'] # (ভবিষ্যতে মেইনটেন্যান্স মোড বা এক্সট্রা ফিচারের জন্য)
