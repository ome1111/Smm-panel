import sys
import io
import math
import time
import os
import threading
import re
import random
from datetime import datetime, timedelta

# ASCII Encoding Fix
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from telebot import types
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col
from config import *
import api

def update_spy(uid, action_text):
    pass

# ==========================================
# 1. CURRENCY ENGINE & FAST SETTINGS CACHE
# ==========================================
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')

user_actions, blocked_users = {}, {}
CURRENCY_RATES = {"BDT": 120, "INR": 83, "USD": 1}
CURRENCY_SYMBOLS = {"BDT": "৳", "INR": "₹", "USD": "$"}

def fmt_curr(usd_amount, curr_code="BDT"):
    rate = CURRENCY_RATES.get(curr_code, 120)
    sym = CURRENCY_SYMBOLS.get(curr_code, "৳")
    val = float(usd_amount) * rate
    decimals = 3 if curr_code == "USD" else 2
    return f"{sym}{val:.{decimals}f}"

SETTINGS_CACHE = {"data": None, "time": 0}

def get_settings():
    global SETTINGS_CACHE
    if SETTINGS_CACHE["data"] and time.time() - SETTINGS_CACHE["time"] < 30:
        return SETTINGS_CACHE["data"]
    s = config_col.find_one({"_id": "settings"})
    if not s:
        s = {
            "_id": "settings", "channels": [], "profit_margin": 20.0, 
            "maintenance": False, "maintenance_msg": "Bot is currently upgrading.", 
            "payments": [], "ref_bonus": 0.05, "dep_commission": 5.0, 
            "welcome_bonus_active": False, "welcome_bonus": 0.0, 
            "flash_sale_active": False, "flash_sale_discount": 0.0, 
            "reward_top1": 10.0, "reward_top2": 5.0, "reward_top3": 2.0, 
            "best_choice_sids": [], "points_per_usd": 100, "points_to_usd_rate": 1000,
            "proof_channel": ""
        }
        config_col.insert_one(s)
    SETTINGS_CACHE["data"] = s
    SETTINGS_CACHE["time"] = time.time()
    return s

def check_spam(uid):
    if str(uid) == str(ADMIN_ID): return False 
    current_time = time.time()
    if uid in blocked_users and current_time < blocked_users[uid]: return True
    if uid not in user_actions: user_actions[uid] = []
    user_actions[uid].append(current_time)
    user_actions[uid] = [t for t in user_actions[uid] if current_time - t < 3]
    if len(user_actions[uid]) > 5:
        blocked_users[uid] = current_time + 300
        try: bot.send_message(uid, "🛡 **ANTI-SPAM ACTIVATED!**\nYou are clicking too fast. Please wait 5 minutes.", parse_mode="Markdown")
        except: pass
        return True
    return False

def check_maintenance(chat_id):
    s = get_settings()
    if s.get('maintenance', False) and str(chat_id) != str(ADMIN_ID):
        msg = s.get('maintenance_msg', "Bot is currently upgrading.")
        bot.send_message(chat_id, f"🚧 **SYSTEM MAINTENANCE**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
        return True
    return False

# ==========================================
# 2. PRO-LEVEL CACHE, SYNC & DRIP CAMPAIGNS
# ==========================================
GLOBAL_SERVICES_CACHE = []

def auto_sync_services_cron():
    global GLOBAL_SERVICES_CACHE
    while True:
        try:
            res = api.get_services()
            if res and isinstance(res, list): 
                GLOBAL_SERVICES_CACHE = res
                config_col.update_one({"_id": "api_cache"}, {"$set": {"data": res, "time": time.time()}}, upsert=True)
        except: pass
        time.sleep(600)
threading.Thread(target=auto_sync_services_cron, daemon=True).start()

def exchange_rate_sync_cron():
    global CURRENCY_RATES
    while True:
        try:
            rates = api.get_live_exchange_rates()
            if rates:
                CURRENCY_RATES["BDT"] = rates.get("BDT", 120)
                CURRENCY_RATES["INR"] = rates.get("INR", 83)
        except: pass
        time.sleep(43200)
threading.Thread(target=exchange_rate_sync_cron, daemon=True).start()

def drip_campaign_cron():
    while True:
        try:
            now = datetime.now()
            users = list(users_col.find({"is_fake": {"$ne": True}}))
            for u in users:
                joined = u.get("joined")
                if not joined: continue
                days = (now - joined).days
                uid = u["_id"]
                if days >= 3 and not u.get("drip_3"):
                    try: bot.send_message(uid, "🎁 **Hey! It's been 3 Days!**\nHope you're enjoying our lightning-fast services. Deposit today to boost your socials!", parse_mode="Markdown")
                    except: pass
                    users_col.update_one({"_id": uid}, {"$set": {"drip_3": True}})
                elif days >= 7 and not u.get("drip_7"):
                    try: bot.send_message(uid, "🔥 **1 Week Anniversary!**\nYou've been with us for 7 days. Check out our Flash Sales and keep growing!", parse_mode="Markdown")
                    except: pass
                    users_col.update_one({"_id": uid}, {"$set": {"drip_7": True}})
                elif days >= 15 and not u.get("drip_15"):
                    try: bot.send_message(uid, "💎 **VIP Reminder!**\nAs a loyal user, we invite you to check our Best Choice services today!", parse_mode="Markdown")
                    except: pass
                    users_col.update_one({"_id": uid}, {"$set": {"drip_15": True}})
        except: pass
        time.sleep(43200)
threading.Thread(target=drip_campaign_cron, daemon=True).start()

# 🔥 FIXED: Order Notification Emojis & Completion Check
def auto_sync_orders_cron():
    while True:
        try:
            active_orders = list(orders_col.find({"status": {"$nin": ["completed", "canceled", "refunded", "fail", "partial"]}}))
            for o in active_orders:
                if o.get("is_shadow"): continue
                try: res = api.check_order_status(o['oid'])
                except: continue
                if res and 'status' in res:
                    new_status = res['status'].lower()
                    old_status = str(o.get('status', '')).lower()
                    if new_status != old_status and new_status != 'error':
                        orders_col.update_one({"_id": o["_id"]}, {"$set": {"status": new_status}})
                        
                        st_emoji = "⏳"
                        if new_status == "completed": st_emoji = "✅"
                        elif new_status in ["canceled", "refunded", "fail"]: st_emoji = "❌"
                        elif new_status in ["in progress", "processing"]: st_emoji = "🔄"
                        elif new_status == "partial": st_emoji = "⚠️"

                        try:
                            msg = f"🔔 **ORDER UPDATE!**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Order ID: `{o['oid']}`\n🔗 Link: {str(o.get('link', 'N/A'))[:25]}...\n📦 Status: {st_emoji} **{new_status.upper()}**"
                            bot.send_message(o['uid'], msg, parse_mode="Markdown")
                        except: pass
                        if new_status in ['canceled', 'refunded', 'fail']:
                            u = users_col.find_one({"_id": o['uid']})
                            curr = u.get("currency", "BDT") if u else "BDT"
                            cost_str = fmt_curr(o['cost'], curr)
                            users_col.update_one({"_id": o['uid']}, {"$inc": {"balance": o['cost'], "spent": -o['cost']}})
                            try: bot.send_message(o['uid'], f"💰 **ORDER REFUNDED!**\nOrder `{o['oid']}` failed or canceled by server. `{cost_str}` has been added back to your balance.", parse_mode="Markdown")
                            except: pass
        except: pass
        time.sleep(120)
threading.Thread(target=auto_sync_orders_cron, daemon=True).start()

def get_cached_services():
    global GLOBAL_SERVICES_CACHE
    if GLOBAL_SERVICES_CACHE: return GLOBAL_SERVICES_CACHE
    cache = config_col.find_one({"_id": "api_cache"})
    return cache.get('data', []) if cache else []

def calculate_price(base_rate, user_spent, user_custom_discount=0.0):
    s = get_settings()
    profit = s.get('profit_margin', 20.0)
    fs = s.get('flash_sale_discount', 0.0) if s.get('flash_sale_active', False) else 0.0
    _, tier_discount = get_user_tier(user_spent)
    total_disc = tier_discount + fs + user_custom_discount
    rate_w_profit = float(base_rate) * (1 + (profit / 100))
    return rate_w_profit * (1 - (total_disc / 100))

def clean_service_name(raw_name):
    try:
        n = str(raw_name)
        emojis = ""
        n_lower = n.lower()
        if "instant" in n_lower or "fast" in n_lower: emojis += "⚡"
        if "non drop" in n_lower or "norefill" in n_lower or "no refill" in n_lower: emojis += "💎"
        elif "refill" in n_lower: emojis += "♻️"
        if "stable" in n_lower: emojis += "🛡️"
        if "real" in n_lower: emojis += "👤"
        n = re.sub(r'(?i)speed\s*[:\-]?\s*', '', n)
        n = re.sub(r'📍?\s*\d+(-\d+)?[KkMm]?/[Dd]\s*', '', n)
        words = ["Telegram", "TG", "Instagram", "IG", "Facebook", "FB", "YouTube", "YT", "TikTok", "Twitter", "1xpanel", "Instant", "fast", "NoRefill", "No refill", "Refill", "Stable", "price", "Non drop", "real"]
        for w in words: n = re.sub(r'(?i)\b' + re.escape(w) + r'\b', '', n)
        n = re.sub(r'[-|:._/]+', ' ', n)
        n = " ".join(n.split()).strip()
        return f"{n[:45]} {emojis}".strip() if n else f"Premium Service {emojis}"
    except: return str(raw_name)[:50]

def identify_platform(cat_name):
    cat = cat_name.lower()
    if 'instagram' in cat or 'ig' in cat: return "📸 Instagram"
    if 'facebook' in cat or 'fb' in cat: return "📘 Facebook"
    if 'youtube' in cat or 'yt' in cat: return "▶️ YouTube"
    if 'telegram' in cat or 'tg' in cat: return "✈️ Telegram"
    if 'tiktok' in cat: return "🎵 TikTok"
    if 'twitter' in cat or ' x ' in cat: return "🐦 Twitter"
    return "🌐 Other Services"

def get_user_tier(spent):
    if spent >= 50: return "🥇 Gold VIP", 5 
    elif spent >= 10: return "🥈 Silver VIP", 2 
    else: return "🥉 Bronze", 0

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🚀 New Order", "⭐ Favorites")
    markup.add("🔍 Smart Search", "📦 Orders")
    markup.add("💰 Deposit", "🤝 Affiliate")
    markup.add("👤 Profile", "🎟️ Voucher")
    markup.add("🏆 Leaderboard", "🎧 Support Ticket")
    return markup

def check_sub(chat_id):
    channels = get_settings().get("channels", [])
    if not channels: return True
    for ch in channels:
        try:
            member = bot.get_chat_member(ch, chat_id)
            if member.status in ['left', 'kicked']: return False
        except: return False
    return True
