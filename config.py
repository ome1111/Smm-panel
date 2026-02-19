import os

# --- SECRET KEYS (Render Env Variables) ---
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN')
API_KEY = os.environ.get('API_KEY', 'YOUR_API_KEY')
API_URL = "https://1xpanel.com/api/v2" # আপনার প্যানেলের আসল এপিআই লিঙ্ক দিন
MONGO_URL = os.environ.get('MONGO_URL', 'YOUR_MONGO_URL')

# --- ADMIN PANEL SECURITY ---
ADMIN_PASSWORD = os.environ.get('ADMIN_PASS', 'admin123')
SECRET_KEY = os.environ.get('SECRET_KEY', 'super_secret_key_123')

# --- BUSINESS SETTINGS ---
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
FORCE_SUB_CHANNEL = os.environ.get('FORCE_SUB_CHANNEL', '') # যেমন: @YourChannel
PROOF_CHANNEL_ID = os.environ.get('PROOF_CHANNEL_ID', '')   # পেমেন্ট প্রুফ চ্যানেল

PROFIT_MARGIN = int(os.environ.get('PROFIT_MARGIN', '20'))  # আপনার লাভের হার (%)
EXCHANGE_RATE = int(os.environ.get('EXCHANGE_RATE', '120')) # $1 = কত টাকা
PAYMENT_NUMBER = os.environ.get('PAYMENT_NUMBER', '01700000000') # বিকাশ/নগদ নাম্বার

# --- BONUS SETTINGS ---
REF_BONUS = 0.05   # প্রতি রেফারে $০.০৫
DAILY_BONUS = 0.01 # প্রতিদিনের বোনাস $০.০১
SUPPORT_USER = os.environ.get('SUPPORT_USER', '@YourAdminUsername')
