import os

# --- SECRET KEYS (Render Env Variables) ---
# Render ড্যাশবোর্ডে Environment Variables সেকশনে এই ভ্যালুগুলো সেট করবেন।
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN')
API_KEY = os.environ.get('API_KEY', 'YOUR_API_KEY')
API_URL = os.environ.get('API_URL', 'https://1xpanel.com/api/v2')

# --- DATABASE URLS ---
MONGO_URL = os.environ.get('MONGO_URL', 'YOUR_MONGO_URL')

# 🔥 Redis URL (Hardcoded সরানো হয়েছে সিকিউরিটির জন্য)
REDIS_URL = os.environ.get('REDIS_URL', 'rediss://default:YOUR_PASSWORD@YOUR_HOST:6379')

# --- ADMIN PANEL SECURITY ---
ADMIN_PASSWORD = os.environ.get('ADMIN_PASS', 'admin123')
SECRET_KEY = os.environ.get('SECRET_KEY', 'super_secret_key_123')

# --- BUSINESS SETTINGS ---
# Render Environment এ ADMIN_ID অবশ্যই দিতে হবে
try:
    ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
except ValueError:
    ADMIN_ID = 0

FORCE_SUB_CHANNEL = os.environ.get('FORCE_SUB_CHANNEL', '') 
PROOF_CHANNEL_ID = os.environ.get('PROOF_CHANNEL_ID', '')   

try:
    PROFIT_MARGIN = int(os.environ.get('PROFIT_MARGIN', '20'))  
    EXCHANGE_RATE = int(os.environ.get('EXCHANGE_RATE', '120')) 
except ValueError:
    PROFIT_MARGIN = 20
    EXCHANGE_RATE = 120

PAYMENT_NUMBER = os.environ.get('PAYMENT_NUMBER', '01700000000') 

# --- RENDER URL ---
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://your-app-name.onrender.com')

# --- BONUS SETTINGS ---
REF_BONUS = float(os.environ.get('REF_BONUS', '0.05'))
DAILY_BONUS = float(os.environ.get('DAILY_BONUS', '0.01'))
SUPPORT_USER = os.environ.get('SUPPORT_USER', '@YourAdminUsername')
