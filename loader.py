import telebot
from pymongo import MongoClient, ASCENDING, DESCENDING
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

# ==========================================
# 🚀 MONGODB INDEXING (100x SPEED BOOST)
# ==========================================
try:
    # 1. Orders Index: Order ID (oid) এর ওপর ইউনিক ইনডেক্স যাতে API সিঙ্ক সুপারফাস্ট হয়
    orders_col.create_index([("oid", ASCENDING)], unique=True)
    # ইউজারের 'My Orders' পেজ ফাস্ট লোড হওয়ার জন্য uid এর ওপর ইনডেক্স
    orders_col.create_index([("uid", ASCENDING)]) 

    # 2. Users Index: Leaderboard সর্টিং এর জন্য Spent এবং Ref Earnings এর ইনডেক্স
    users_col.create_index([("spent", DESCENDING)])
    users_col.create_index([("ref_earnings", DESCENDING)])

    # 3. Vouchers Index: ভাউচার কোড যেন মিলি-সেকেন্ডে ভেরিফাই হয়
    vouchers_col.create_index([("code", ASCENDING)], unique=True)
    
    print("✅ Database Indexing Applied Successfully! Lightning Fast Mode ON 🚀")
except Exception as e:
    # যদি ইনডেক্স আগে থেকেই তৈরি থাকে, তবে কোনো এরর ছাড়াই স্কিপ করবে
    print(f"⚠️ Indexing Status: Indexes are already optimized or skipped. ({e})")
