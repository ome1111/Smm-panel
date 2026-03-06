import os
import time
import logging
import telebot
import redis
from pymongo import MongoClient, ASCENDING, DESCENDING
from config import BOT_TOKEN, MONGO_URL, REDIS_URL

# ==========================================
# 1. TIMEZONE & LOGGING SETUP (PRO-LEVEL)
# ==========================================
# Default Timezone সেট করা হলো (Asia/Dhaka)
os.environ['TZ'] = 'Asia/Dhaka'
try:
    time.tzset()  
except AttributeError:
    pass

# Advanced Logging System (Added Process ID for Gunicorn Workers)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [Worker-%(process)d] %(message)s',
    datefmt='%Y-%m-%d %I:%M:%S %p'
)

# ==========================================
# 2. GLOBAL ERROR HANDLER (CRASH PROTECTION)
# ==========================================
class CrashPreventer(telebot.ExceptionHandler):
    def handle(self, exception):
        logging.error(f"🔥 BOT CRASH PREVENTED: {exception}")
        return True  

# Webhook ব্যবহারের সময় threaded=False রাখা বাধ্যতামূলক
bot = telebot.TeleBot(BOT_TOKEN, threaded=False, exception_handler=CrashPreventer())

# ==========================================
# 3. MONGODB CONNECTION (Optimized for Gunicorn)
# ==========================================
# Gunicorn-এর একাধিক ওয়ার্কার সামলানোর জন্য Pool Size বাড়ানো হয়েছে
mongo_options = "&maxPoolSize=50&connectTimeoutMS=10000" if "?" in MONGO_URL else "?maxPoolSize=50&connectTimeoutMS=10000"
client = MongoClient(MONGO_URL + mongo_options)

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
logs_col = db['logs'] 
scheduled_col = db['scheduled_orders'] # 🔥 NEW: Custom Drip-Feed Collection

# ==========================================
# 4. REDIS CONNECTION (FAST CACHE ENGINE - OPTIMIZED)
# ==========================================
try:
    # 🔥 max_connections বাড়িয়ে 50 করা হলো ThreadPool এর সাথে ম্যাচ করার জন্য
    redis_pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True, max_connections=50)
    redis_client = redis.Redis(connection_pool=redis_pool)
    redis_client.ping()
    logging.info("✅ Redis Engine Connected Successfully! Lightning Speed ON 🚀")
except Exception as e:
    logging.error(f"❌ REDIS CONNECTION FAILED: {e}")

# ==========================================
# 5. MONGODB INDEXING (100x SPEED BOOST)
# ==========================================
try:
    orders_col.create_index([("oid", ASCENDING)], unique=True)
    orders_col.create_index([("uid", ASCENDING)]) 
    users_col.create_index([("spent", DESCENDING)])
    users_col.create_index([("ref_earnings", DESCENDING)])
    vouchers_col.create_index([("code", ASCENDING)], unique=True)
    
    # 🔥 NEW: Indexing for fast background background drip-feed loop
    scheduled_col.create_index([("status", ASCENDING), ("next_run", ASCENDING)])
    
    logging.info("✅ Database Indexing Applied Successfully! Lightning Fast Mode ON 🚀")
except Exception as e:
    logging.warning(f"⚠️ Indexing Status: Indexes are already optimized or skipped. ({e})")
