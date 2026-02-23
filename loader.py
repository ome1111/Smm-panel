import os
import time
import logging
import telebot
from pymongo import MongoClient, ASCENDING, DESCENDING
from config import BOT_TOKEN, MONGO_URL, ADMIN_ID

# ==========================================
# 1. TIMEZONE & LOGGING SETUP (PRO-LEVEL)
# ==========================================
# Default Timezone செট করা হলো (Asia/Dhaka) - রেন্ডারের ডিফল্ট টাইমের সমস্যা দূর করতে
os.environ['TZ'] = 'Asia/Dhaka'
try:
    time.tzset()  # এটি লিনাক্স/সার্ভারে টাইমজোন ফিক্স করে দেবে
except AttributeError:
    pass

# Advanced Logging System (Terminal-এ সুন্দরভাবে ডেট-টাইম সহ লগ দেখাবে)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %I:%M:%S %p'
)

# ==========================================
# 2. GLOBAL ERROR HANDLER (CRASH PROTECTION)
# ==========================================
# API বা সার্ভারে কোনো আন-এক্সপেক্টেড সমস্যা হলে বট যাতে হ্যাং বা ক্র্যাশ না করে
class CrashPreventer(telebot.ExceptionHandler):
    def handle(self, exception):
        logging.error(f"🔥 BOT CRASH PREVENTED: {exception}")
        return True  # True রিটার্ন করলে বট এরর ইগনোর করে চলতে থাকবে

# Webhook এর জন্য threaded=False এবং Crash Preventer যুক্ত করা হয়েছে
bot = telebot.TeleBot(BOT_TOKEN, threaded=False, exception_handler=CrashPreventer())

# ==========================================
# 3. DATABASE CONNECTION & HEALTH CHECK
# ==========================================
# MongoDB কানেকশন লিমিট (OOM Memory Crash ফিক্স করার জন্য)
client = MongoClient(MONGO_URL + ("&maxPoolSize=20" if "?" in MONGO_URL else "?maxPoolSize=20"))

# 🔥 Health Check (Auto-Ping): ডাটাবেস ঠিকমতো কাজ করছে কি না তা স্টার্ট হওয়ার সময় চেক করবে
try:
    client.admin.command('ping')
    logging.info("✅ MongoDB Database Connected & Healthy!")
except Exception as e:
    logging.error(f"❌ DATABASE CONNECTION FAILED: {e}")

db = client['smm_database']

users_col = db['users']
orders_col = db['orders']
config_col = db['settings']
tickets_col = db['tickets']
vouchers_col = db['vouchers']
logs_col = db['logs']  # 🔥 এই লাইনটি অ্যাড করা হয়েছে!

# ==========================================
# 4. MONGODB INDEXING (100x SPEED BOOST)
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
    
    logging.info("✅ Database Indexing Applied Successfully! Lightning Fast Mode ON 🚀")
except Exception as e:
    # যদি ইনডেক্স আগে থেকেই তৈরি থাকে, তবে কোনো এরর ছাড়াই স্কিপ করবে
    logging.warning(f"⚠️ Indexing Status: Indexes are already optimized or skipped. ({e})")
