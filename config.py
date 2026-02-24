import os

# --- SECRET KEYS (Render Env Variables) ---
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN')
API_KEY = os.environ.get('API_KEY', 'YOUR_API_KEY')
API_URL = "https://1xpanel.com/api/v2" # আপনার প্যানেলের আসল এপিআই লিঙ্ক

# --- DATABASE URLS ---
MONGO_URL = os.environ.get('MONGO_URL', 'YOUR_MONGO_URL')

# 🔥 আপনার দেওয়া Upstash Redis URL (TLS/SSL সাপোর্টের জন্য rediss:// ব্যবহার করা হয়েছে)
REDIS_URL = os.environ.get('REDIS_URL', 'rediss://default:AcTrAAIncDE4ZjY1N2NiZjYxNjg0ZjE3YmJhMWM1OGQxMmYwYTNmYnAxNTA0MTE@large-whippet-50411.upstash.io:6379')

# --- ADMIN PANEL SECURITY ---
ADMIN_PASSWORD = os.environ.get('ADMIN_PASS', 'admin123')
SECRET_KEY = os.environ.get('SECRET_KEY', 'super_secret_key_123')

# --- BUSINESS SETTINGS ---
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
FORCE_SUB_CHANNEL = os.environ.get('FORCE_SUB_CHANNEL', '') 
PROOF_CHANNEL_ID = os.environ.get('PROOF_CHANNEL_ID', '')   

PROFIT_MARGIN = int(os.environ.get('PROFIT_MARGIN', '20'))  
EXCHANGE_RATE = int(os.environ.get('EXCHANGE_RATE', '120')) 
PAYMENT_NUMBER = os.environ.get('PAYMENT_NUMBER', '01700000000') 

# --- RENDER URL ---
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')

# --- BONUS SETTINGS ---
REF_BONUS = 0.05   
DAILY_BONUS = 0.01 
SUPPORT_USER = os.environ.get('SUPPORT_USER', '@YourAdminUsername')
