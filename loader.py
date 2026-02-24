import os
import time
import logging
import telebot
import redis
from pymongo import MongoClient, ASCENDING, DESCENDING
from config import BOT_TOKEN, MONGO_URL, REDIS_URL, ADMIN_ID

# ==========================================
# 1. TIMEZONE & LOGGING SETUP (PRO-LEVEL)
# ==========================================
# Default Timezone செট করা হলো (Asia/Dhaka)
os.environ['TZ'] = 'Asia/Dhaka'
try:
    time.tzset()  
except AttributeError:
    pass

# Advanced Logging System
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %I:%M:%S %p'
)

# ==========================================
# 2. GLOBAL ERROR HANDLER (CRASH PROTECTION)
# ==========================================
class CrashPreventer(telebot.ExceptionHandler):
    def handle(self, exception):
        logging.error(f"🔥 BOT CRASH PREVENTED: {exception}")
        return True  

bot = telebot.TeleBot(BOT_TOKEN, threaded=False, exception_handler=CrashPreventer())

# ==========================================
# 3. MONGODB CONNECTION & HEALTH CHECK
# ==========================================
client = MongoClient(MONGO_URL + ("&maxPoolSize=20" if "?" in MONGO_URL else "?maxPoolSize=20"))

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

# 🔥 NEW: Multi-Provider Collection (একাধিক প্যানেল স্টোর করার জন্য)
providers_col = db['providers']

# ==========================================
# 4. REDIS CONNECTION (FAST CACHE ENGINE)
# ==========================================
try:
    # Upstash Redis TLS/SSL Connection
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
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
    
    # 🔥 NEW: Provider Name Indexing (দ্রুত প্যানেল খোঁজার জন্য)
    providers_col.create_index([("name", ASCENDING)], unique=True)
    
    logging.info("✅ Database Indexing Applied Successfully! Lightning Fast Mode ON 🚀")
except Exception as e:
    logging.warning(f"⚠️ Indexing Status: Indexes are already optimized or skipped. ({e})")
