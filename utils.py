import sys
import io
import math
import time
import os
import threading
import re
import random
import json
import urllib.parse
import hashlib
import base64
import requests
import hmac
import logging
import traceback
from datetime import datetime, timedelta
from bson import json_util # 🔥 MongoDB Date/Object serialize করার জন্য

# ASCII Encoding Fix
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from telebot import types
# 🔥 loader থেকে redis_client এবং logs_col ইম্পোর্ট করা হলো
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, redis_client, logs_col
from config import *
import api

def update_spy(uid, action_text):
    pass

# ==========================================
# 1. CURRENCY ENGINE & FAST SETTINGS CACHE
# ==========================================
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')

CURRENCY_RATES = {"BDT": 120, "INR": 83, "USD": 1}
CURRENCY_SYMBOLS = {"BDT": "৳", "INR": "₹", "USD": "$"}

def fmt_curr(usd_amount, curr_code="BDT"):
    rate = CURRENCY_RATES.get(curr_code, 120)
    sym = CURRENCY_SYMBOLS.get(curr_code, "৳")
    val = float(usd_amount) * rate
    decimals = 3 if curr_code == "USD" else 2
    return f"{sym}{val:.{decimals}f}"

# 🔥 Redis Based Settings Cache (Super Fast)
def get_settings():
    cached = redis_client.get("settings_cache")
    if cached:
        return json.loads(cached)
        
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
            "proof_channel": "", "profit_tiers": [],
            "cryptomus_merchant": "", "cryptomus_api": "", "coinpayments_pub": "", "coinpayments_priv": "",
            "cryptomus_active": False, "coinpayments_active": False
        }
        config_col.insert_one(s)
        
    redis_client.setex("settings_cache", 30, json.dumps(s)) # 30 সেকেন্ডের জন্য ক্যাশে থাকবে
    return s

def update_settings_cache(key, value):
    s = get_settings()
    s[key] = value
    redis_client.setex("settings_cache", 30, json.dumps(s))

# 🔥 Super Fast User Caching Engine (New)
def get_cached_user(uid):
    """MongoDB এর বদলে Redis থেকে ইউজারের ডেটা আনবে"""
    cached = redis_client.get(f"user_cache_{uid}")
    if cached:
        return json.loads(cached, object_hook=json_util.object_hook)
    
    user = users_col.find_one({"_id": uid})
    if user:
        redis_client.setex(f"user_cache_{uid}", 300, json.dumps(user, default=json_util.default)) # ৫ মিনিট ক্যাশ
    return user

def clear_cached_user(uid):
    """ইউজারের ব্যালেন্স বা ডেটা আপডেট হলে ক্যাশ ক্লিয়ার করবে"""
    redis_client.delete(f"user_cache_{uid}")

# 🔥 Redis Based Anti-Spam (100% Accurate & Distributed)
def check_spam(uid):
    if str(uid) == str(ADMIN_ID): return False 
    
    if redis_client.get(f"blocked_{uid}"): 
        return True
        
    key = f"spam_{uid}"
    reqs = redis_client.incr(key)
    
    if reqs == 1: 
        redis_client.expire(key, 3) # ৩ সেকেন্ডের উইন্ডো
        
    if reqs > 5:
        redis_client.setex(f"blocked_{uid}", 300, "1") # ৫ মিনিটের জন্য ব্লক
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

# 🔥 1xpanel API Auto-Sync 
def auto_sync_services_cron():
    while True:
        # 🔥 Redis Distributed Lock to prevent duplicate Gunicorn workers
        if not redis_client.set("lock_sync_services", "locked", nx=True, ex=43000):
            time.sleep(60)
            continue
            
        try:
            res = api.get_services()
            if res and isinstance(res, list): 
                # Redis এ ১২ ঘণ্টার জন্য সেভ রাখা (43200 সেকেন্ড)
                redis_client.setex("services_cache", 43200, json.dumps(res))
                # ডাটাবেসে ব্যাকআপ হিসেবে রাখা
                config_col.update_one({"_id": "api_cache"}, {"$set": {"data": res, "time": time.time()}}, upsert=True)
        except Exception as e:
            logging.error(f"Service Sync Error: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Service Sync", "date": datetime.now()})
            except: pass
        time.sleep(43200) # ১২ ঘণ্টা ঘুমাবে 

threading.Thread(target=auto_sync_services_cron, daemon=True).start()

def exchange_rate_sync_cron():
    while True:
        # 🔥 Redis Lock
        if not redis_client.set("lock_exchange_rate", "locked", nx=True, ex=43000):
            time.sleep(60)
            continue
            
        try:
            rates = api.get_live_exchange_rates()
            if rates:
                global CURRENCY_RATES
                CURRENCY_RATES["BDT"] = rates.get("BDT", 120)
                CURRENCY_RATES["INR"] = rates.get("INR", 83)
        except Exception as e:
            logging.error(f"Exchange Rate Sync Error: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Exchange Rate Sync", "date": datetime.now()})
            except: pass
        time.sleep(43200)

threading.Thread(target=exchange_rate_sync_cron, daemon=True).start()

def drip_campaign_cron():
    while True:
        # 🔥 Redis Lock
        if not redis_client.set("lock_drip", "locked", nx=True, ex=43000):
            time.sleep(60)
            continue
            
        now = datetime.now()
        try:
            users = list(users_col.find({"is_fake": {"$ne": True}}))
            for u in users:
                try: # 🔥 Moved INSIDE the loop so one user error doesn't crash everything
                    time.sleep(0.05) 
                    joined = u.get("joined")
                    if not joined: continue
                    days = (now - joined).days
                    uid = u["_id"]
                    
                    if days >= 3 and not u.get("drip_3"):
                        try: bot.send_message(uid, "🎁 **Hey! It's been 3 Days!**\nHope you're enjoying our lightning-fast services. Deposit today to boost your socials!", parse_mode="Markdown")
                        except: pass
                        users_col.update_one({"_id": uid}, {"$set": {"drip_3": True}})
                        clear_cached_user(uid)
                    elif days >= 7 and not u.get("drip_7"):
                        try: bot.send_message(uid, "🔥 **1 Week Anniversary!**\nYou've been with us for 7 days. Check out our Flash Sales and keep growing!", parse_mode="Markdown")
                        except: pass
                        users_col.update_one({"_id": uid}, {"$set": {"drip_7": True}})
                        clear_cached_user(uid)
                    elif days >= 15 and not u.get("drip_15"):
                        try: bot.send_message(uid, "💎 **VIP Reminder!**\nAs a loyal user, we invite you to check our Best Choice services today!", parse_mode="Markdown")
                        except: pass
                        users_col.update_one({"_id": uid}, {"$set": {"drip_15": True}})
                        clear_cached_user(uid)
                except Exception as e: 
                    logging.error(f"Drip Campaign Inner Error: {e}")
        except Exception as e:
            logging.error(f"Drip Campaign Outer Error: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Drip Campaign", "date": datetime.now()})
            except: pass
        time.sleep(43200)

threading.Thread(target=drip_campaign_cron, daemon=True).start()

def auto_sync_orders_cron():
    while True:
        # 🔥 Redis Lock 
        if not redis_client.set("lock_orders_sync", "locked", nx=True, ex=110):
            time.sleep(10)
            continue
            
        try:
            # 🔥 Processes all active orders safely
            active_orders = orders_col.find({"status": {"$nin": ["completed", "canceled", "refunded", "fail", "partial"]}})
            for o in active_orders:
                try:
                    time.sleep(0.1) 
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
                                u = get_cached_user(o['uid'])
                                curr = u.get("currency", "BDT") if u else "BDT"
                                cost_str = fmt_curr(o['cost'], curr)
                                users_col.update_one({"_id": o['uid']}, {"$inc": {"balance": o['cost'], "spent": -o['cost']}})
                                clear_cached_user(o['uid'])
                                try: bot.send_message(o['uid'], f"💰 **ORDER REFUNDED!**\nOrder `{o['oid']}` failed or canceled by server. `{cost_str}` has been added back to your balance.", parse_mode="Markdown")
                                except: pass
                except Exception as e: 
                    logging.error(f"Auto Sync Inner Error: {e}")
        except Exception as e: 
            logging.error(f"Auto Sync Outer Error: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Order Sync", "date": datetime.now()})
            except: pass
        time.sleep(120)

threading.Thread(target=auto_sync_orders_cron, daemon=True).start()

# 🔥 Get Services strictly from Redis Cache
def get_cached_services():
    cached = redis_client.get("services_cache")
    if cached: 
        return json.loads(cached)
        
    cache = config_col.find_one({"_id": "api_cache"})
    data = cache.get('data', []) if cache else []
    if data:
        redis_client.setex("services_cache", 43200, json.dumps(data))
    return data

def calculate_price(base_rate, user_spent, user_custom_discount=0.0):
    s = get_settings()
    base = float(base_rate)
    
    profit = float(s.get('profit_margin', 20.0))
    
    profit_tiers = s.get('profit_tiers', [])
    if profit_tiers:
        for tier in profit_tiers:
            try:
                t_min = float(tier.get('min', 0))
                t_max = float(tier.get('max', 999999))
                t_margin = float(tier.get('margin', profit))
                if t_min <= base <= t_max:
                    profit = t_margin
                    break
            except:
                pass

    fs = float(s.get('flash_sale_discount', 0.0)) if s.get('flash_sale_active', False) else 0.0
    _, tier_discount = get_user_tier(user_spent)
    total_disc = float(tier_discount) + fs + float(user_custom_discount)
    
    rate_w_profit = base * (1 + (profit / 100))
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
        
        # Long names to Short Form convert
        n = re.sub(r'(?i)\bTelegram\b', 'TG', n)
        n = re.sub(r'(?i)\bInstagram\b|\bInsta\b', 'IG', n)
        n = re.sub(r'(?i)\bFacebook\b', 'FB', n)
        n = re.sub(r'(?i)\bYouTube\b', 'YT', n)
        n = re.sub(r'(?i)\bTwitter\b', 'X', n)
        
        # Remove brackets from shortforms like [TG] -> TG
        n = re.sub(r'\[(TG|IG|FB|YT|X|TikTok)\]', r'\1', n, flags=re.IGNORECASE)
        n = re.sub(r'\((TG|IG|FB|YT|X|TikTok)\)', r'\1', n, flags=re.IGNORECASE)
        
        # Remove unnecessary words
        words = ["1xpanel", "Instant", "fast", "NoRefill", "No refill", "Refill", "Stable", "price", "Non drop", "real"]
        
        for w in words: 
            n = re.sub(r'(?i)\b' + re.escape(w) + r'\b', '', n)
        
        n = re.sub(r'[-|:._/]+', ' ', n)
        n = " ".join(n.split()).strip()
        return f"{n[:45]} {emojis}".strip() if n else f"Premium Service {emojis}"
    except: return str(raw_name)[:50]

def identify_platform(cat_name):
    cat = str(cat_name).lower()
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
    markup.add("🏆 Leaderboard", "💬 Live Chat")
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

# ==========================================
# 3. AUTO CRYPTO PAYMENT GATEWAYS (NEW)
# ==========================================
def create_cryptomus_payment(amount, order_id, merchant, api_key):
    url = "https://api.cryptomus.com/v1/payment"
    payload = {
        "amount": str(amount),
        "currency": "USD",
        "order_id": str(order_id),
        "url_callback": f"{BASE_URL.rstrip('/')}/cryptomus_webhook" 
    }
    json_payload = json.dumps(payload)
    sign = hashlib.md5((base64.b64encode(json_payload.encode('utf-8')).decode('utf-8') + api_key).encode('utf-8')).hexdigest()
    
    headers = {'merchant': merchant, 'sign': sign, 'Content-Type': 'application/json'}
    try:
        r = requests.post(url, data=json_payload, headers=headers)
        res = r.json()
        if res.get('state') == 0: 
            return res['result']['url']
    except Exception: 
        pass
    return None

def create_coinpayments_payment(amount, custom_uid, pub_key, priv_key):
    url = "https://www.coinpayments.net/api.php"
    params = {
        "version": 1, 
        "cmd": "create_transaction",
        "amount": amount, 
        "currency1": "USD", 
        "currency2": "USDT.TRC20", # Default Crypto
        "buyer_email": "user@nexusbot.com", # API Requirement
        "custom": str(custom_uid),
        "key": pub_key, 
        "format": "json"
    }
    encoded = urllib.parse.urlencode(params)
    sign = hmac.new(priv_key.encode('utf-8'), encoded.encode('utf-8'), hashlib.sha512).hexdigest()
    headers = {'HMAC': sign}
    try:
        r = requests.post(url, data=params, headers=headers)
        res = r.json()
        if res.get('error') == 'ok': 
            return res['result']['checkout_url']
    except Exception: 
        pass
    return None
