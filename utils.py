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
from bson import json_util
from pymongo import ReturnDocument # 🔥 NEW: For MongoDB Atomic Lock

# ASCII Encoding Fix for Server Logs
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from telebot import types
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, redis_client, logs_col
from config import *
import api

def update_spy(uid, action_text):
    pass

# ==========================================
# 🔥 GLOBAL CACHE VARIABLES (To save Redis limits)
# ==========================================
local_settings_cache = None
last_settings_update = 0

# ==========================================
# 0. SECURITY: MARKDOWN ESCAPE ENGINE
# ==========================================
def escape_md(text):
    """টেলিগ্রামের Legacy Markdown পার্স এরর ঠেকানোর জন্য স্পেশাল ক্যারেক্টার এস্কেপ করা"""
    if not text: return ""
    text = str(text)
    # 🔥 FIX: Added '_' to prevent Telegram Markdown formatting crashes
    escape_chars = ['*', '_', '`', '['] 
    for char in escape_chars:
        text = text.replace(char, f"\\{char}")
    return text

# ==========================================
# 1. CURRENCY ENGINE & FAST SETTINGS CACHE
# ==========================================
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')

def get_currency_rates():
    cached = redis_client.get("currency_rates")
    if cached:
        return json.loads(cached)
    return {"BDT": 120, "INR": 83, "USD": 1}

def fmt_curr(usd_amount, curr_code="BDT"):
    rates = get_currency_rates()
    rate = rates.get(curr_code, 120)
    sym = {"BDT": "৳", "INR": "₹", "USD": "$"}.get(curr_code, "৳")
    val = float(usd_amount) * rate
    
    if curr_code == "USD":
        return f"{sym}{val:.3f}"
    else:
        # No decimal if it's a whole number for local currencies
        formatted_val = int(val) if val.is_integer() else round(val, 2)
        return f"{sym}{formatted_val}"

def get_settings():
    global local_settings_cache, last_settings_update
    now = time.time()
    
    # 1. Check local memory first (Zero Cost & Ultra Fast)
    if local_settings_cache and (now - last_settings_update < 60):
        return local_settings_cache
        
    # 2. Check Redis
    try:
        cached = redis_client.get("settings_cache")
        if cached:
            local_settings_cache = json.loads(cached)
            last_settings_update = now
            return local_settings_cache
    except:
        pass
        
    # 3. Check Database
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
            "proof_channel": "", "profit_tiers": [], "external_apis": [],
            "cryptomus_merchant": "", "cryptomus_api": "", "coinpayments_pub": "", "coinpayments_priv": "",
            "cryptomus_active": False, "coinpayments_active": False,
            "nowpayments_api": "", "nowpayments_ipn": "", "nowpayments_active": False,
            "payeer_merchant": "", "payeer_secret": "", "payeer_active": False,
            "stars_rate": 50, "stars_active": False
        }
        config_col.insert_one(s)
        
    local_settings_cache = s
    last_settings_update = now
    try: redis_client.setex("settings_cache", 60, json.dumps(s)) 
    except: pass
    return s

def update_settings_cache(key, value):
    global local_settings_cache, last_settings_update
    s = get_settings()
    s[key] = value
    local_settings_cache = s # Update local memory instantly
    last_settings_update = time.time() # 🔥 FIX: Update the timestamp
    try: redis_client.setex("settings_cache", 60, json.dumps(s))
    except: pass

def get_cached_user(uid):
    try:
        cached = redis_client.get(f"user_cache_{uid}")
        if cached:
            return json.loads(cached, object_hook=json_util.object_hook)
    except:
        pass
    
    user = users_col.find_one({"_id": uid})
    if user:
        try: redis_client.setex(f"user_cache_{uid}", 300, json.dumps(user, default=json_util.default)) 
        except: pass
    return user

def clear_cached_user(uid):
    try: redis_client.delete(f"user_cache_{uid}")
    except: pass

def check_spam(uid):
    if str(uid) == str(ADMIN_ID): return False 
    try:
        if redis_client.get(f"blocked_{uid}"): return True
        key = f"spam_{uid}"
        reqs = redis_client.incr(key)
        if reqs == 1: redis_client.expire(key, 3) 
        if reqs > 5:
            redis_client.setex(f"blocked_{uid}", 300, "1") 
            try: bot.send_message(uid, "🛡 **ANTI-SPAM ACTIVATED!**\nYou are clicking too fast. Please wait 5 minutes.", parse_mode="Markdown")
            except: pass
            return True
    except:
        pass
    return False

def check_maintenance(chat_id):
    s = get_settings()
    if s.get('maintenance', False) and str(chat_id) != str(ADMIN_ID):
        msg = escape_md(s.get('maintenance_msg', "Bot is currently upgrading."))
        bot.send_message(chat_id, f"🚧 **SYSTEM MAINTENANCE**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
        return True
    return False

# ==========================================
# 2. PRO-LEVEL CACHE, SYNC & HYBRID WORKERS
# ==========================================
def auto_sync_services_cron():
    """Hybrid Sync: 1xpanel + Custom External APIs"""
    while True:
        try:
            if not redis_client.set("lock_sync_services_running", "locked", nx=True, ex=43200):
                time.sleep(60)
                continue
        except:
            time.sleep(60)
            continue
            
        try:
            logging.info("🔄 Syncing services from Main API...")
            main_res = api.get_services()
            
            if main_res and isinstance(main_res, list) and len(main_res) > 0: 
                combined_res = main_res.copy()
                s = get_settings()
                ext_apis = s.get("external_apis", [])
                
                for i, ext in enumerate(ext_apis):
                    ext_url = ext.get('url')
                    ext_key = ext.get('key')
                    target_sids = [str(sid).strip() for sid in ext.get('services', []) if str(sid).strip()]
                    
                    if ext_url and ext_key and target_sids:
                        logging.info(f"🔄 Syncing external API {i}...")
                        try:
                            ext_data = api.get_external_services(ext_url, ext_key)
                            if ext_data and isinstance(ext_data, list):
                                for srv in ext_data:
                                    original_id = str(srv.get('service'))
                                    if original_id in target_sids:
                                        new_srv = srv.copy()
                                        new_id = f"ext_{i}_{original_id}"
                                        new_srv['service'] = new_id
                                        new_srv['name'] = f"{new_srv.get('name', 'Unknown')} 🌟"
                                        combined_res.append(new_srv)
                        except Exception as inner_e:
                            logging.error(f"External API {i} Sync Error: {inner_e}")

                try: redis_client.setex("services_cache", 43200, json.dumps(combined_res))
                except: pass
                config_col.update_one({"_id": "api_cache"}, {"$set": {"data": combined_res, "time": time.time()}}, upsert=True)
                logging.info(f"✅ Successfully synced {len(combined_res)} services (Hybrid Mode).")
                
                time.sleep(43200)
                continue
            else:
                logging.warning("⚠️ Main API returned empty data. Retrying in 5 minutes...")
                try: redis_client.delete("lock_sync_services_running")
                except: pass
        except Exception as e: 
            logging.error(f"❌ Service Sync Failed: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Service Sync", "date": datetime.now()})
            except: pass
            try: redis_client.delete("lock_sync_services_running")
            except: pass
            
        time.sleep(300)

threading.Thread(target=auto_sync_services_cron, daemon=True).start()

def exchange_rate_sync_cron():
    while True:
        try:
            if not redis_client.set("lock_exchange_running", "locked", nx=True, ex=43200):
                time.sleep(60)
                continue
        except:
            time.sleep(60)
            continue
            
        try:
            rates = api.get_live_exchange_rates()
            if rates:
                try: redis_client.set("currency_rates", json.dumps(rates))
                except: pass
                logging.info(f"✅ Live Exchange Rates Synced: {rates}")
                
                time.sleep(43200)
                continue
            else:
                try: redis_client.delete("lock_exchange_running")
                except: pass
        except Exception as e: 
            logging.error(f"❌ Exchange Rate Sync Failed: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Exchange Rate Sync", "date": datetime.now()})
            except: pass
            try: redis_client.delete("lock_exchange_running")
            except: pass
            
        time.sleep(300)

threading.Thread(target=exchange_rate_sync_cron, daemon=True).start()

def drip_campaign_cron():
    while True:
        try:
            if not redis_client.set("lock_drip", "locked", nx=True, ex=43000):
                time.sleep(60)
                continue
        except:
            time.sleep(60)
            continue
            
        now = datetime.now()
        try:
            users_cursor = users_col.find({"is_fake": {"$ne": True}}, {"joined": 1, "drip_3": 1, "drip_7": 1, "drip_15": 1})
            
            for u in users_cursor:
                try: 
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
                    logging.error(f"Drip Campaign User Error: {e}")
        except Exception as e: 
            logging.error(f"Drip Campaign Outer Error: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Drip Campaign", "date": datetime.now()})
            except: pass
        time.sleep(43200)

threading.Thread(target=drip_campaign_cron, daemon=True).start()

def auto_sync_orders_cron():
    while True:
        try:
            # 🔥 Order Sync Lock is now 10 minutes (590s) to save massive Redis limit
            if not redis_client.set("lock_orders_sync", "locked", nx=True, ex=590):
                time.sleep(60)
                continue
        except:
            time.sleep(60)
            continue
            
        try:
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
                        remains = res.get('remains', 0)
                        
                        update_data = {"status": new_status, "remains": remains}
                        orders_col.update_one({"_id": o["_id"]}, {"$set": update_data})
                        
                        if new_status != old_status and new_status != 'error':
                            st_emoji = "⏳"
                            if new_status == "completed": st_emoji = "✅"
                            elif new_status in ["canceled", "refunded", "fail"]: st_emoji = "❌"
                            elif new_status in ["in progress", "processing"]: st_emoji = "🔄"
                            elif new_status == "partial": st_emoji = "⚠️"

                            try:
                                safe_link = escape_md(str(o.get('link', 'N/A'))[:25])
                                msg = f"🔔 **ORDER UPDATE!**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Order ID: `{o['oid']}`\n🔗 Link: {safe_link}...\n📦 Status: {st_emoji} **{new_status.upper()}**"
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
                    logging.error(f"Orders Sync Inner Error: {e}")
        except Exception as e: 
            logging.error(f"Orders Sync Outer Error: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Order Sync", "date": datetime.now()})
            except: pass
            
        # 🔥 Sleep for 10 minutes (Huge Optimization)
        time.sleep(600)

threading.Thread(target=auto_sync_orders_cron, daemon=True).start()

# ==========================================
# 🔥 1 HOUR AUTO REDIS CLEANUP CRON (NEW)
# ==========================================
def auto_redis_cleanup_cron():
    while True:
        try:
            time.sleep(3600) # 1 Hour interval
            
            # 1. Clear Cache
            cache_keys = redis_client.keys("*cache*")
            if cache_keys: 
                redis_client.delete(*cache_keys)
            
            # 2. Release Locks
            lock_keys = redis_client.keys("*lock*")
            if lock_keys: 
                redis_client.delete(*lock_keys)
            
            # 3. Reset Spam
            spam_keys = redis_client.keys("spam_*") + redis_client.keys("blocked_*")
            if spam_keys: 
                redis_client.delete(*spam_keys)
                
            logging.info("🧹 Auto Redis Cleanup Executed: Cache, Locks & Spam Cleared!")
            
        except Exception as e:
            logging.error(f"Auto Redis Cleanup Error: {e}")

threading.Thread(target=auto_redis_cleanup_cron, daemon=True).start()

def get_cached_services():
    try:
        cached = redis_client.get("services_cache")
        if cached: 
            return json.loads(cached)
    except: pass
    
    cache = config_col.find_one({"_id": "api_cache"})
    data = cache.get('data', []) if cache else []
    if data:
        try: redis_client.setex("services_cache", 43200, json.dumps(data))
        except: pass
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
            except: pass

    fs = float(s.get('flash_sale_discount', 0.0)) if s.get('flash_sale_active', False) else 0.0
    _, tier_discount = get_user_tier(user_spent)
    total_disc = float(tier_discount) + fs + float(user_custom_discount)
    
    rate_w_profit = base * (1 + (profit / 100))
    final_rate = rate_w_profit * (1 - (total_disc / 100))
    
    return max(final_rate, 0.001)

def clean_service_name(raw_name):
    if not raw_name: return "Premium Service ⚡"
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
        
        n = re.sub(r'(?i)\bTelegram\b', 'TG', n)
        n = re.sub(r'(?i)\bInstagram\b|\bInsta\b', 'IG', n)
        n = re.sub(r'(?i)\bFacebook\b', 'FB', n)
        n = re.sub(r'(?i)\bYouTube\b', 'YT', n)
        n = re.sub(r'(?i)\bTwitter\b', 'X', n)
        
        n = re.sub(r'\[(TG|IG|FB|YT|X|TikTok)\]', r'\1', n, flags=re.IGNORECASE)
        n = re.sub(r'\((TG|IG|FB|YT|X|TikTok)\)', r'\1', n, flags=re.IGNORECASE)
        
        words = ["1xpanel", "Instant", "fast", "NoRefill", "No refill", "Refill", "Stable", "price", "Non drop", "real"]
        for w in words: 
            n = re.sub(r'(?i)\b' + re.escape(w) + r'\b', '', n)
            
        n = re.sub(r'[-|:._/]+', ' ', n)
        n = " ".join(n.split()).strip()
        
        return f"{n[:45]} {emojis}".strip() if n else f"Premium Service {emojis}"
    except: return str(raw_name)[:50]

def identify_platform(cat_name):
    if not cat_name: return "🌐 Other Services"
    cat = str(cat_name).lower()
    if 'instagram' in cat or 'ig' in cat: return "📸 Instagram"
    if 'facebook' in cat or 'fb' in cat: return "📘 Facebook"
    if 'youtube' in cat or 'yt' in cat: return "▶️ YouTube"
    if 'telegram' in cat or 'tg' in cat: return "✈️ Telegram"
    if 'tiktok' in cat: return "🎵 TikTok"
    if 'twitter' in cat or ' x ' in cat: return "🐦 Twitter"
    return "🌐 Other Services"

def detect_platform_from_link(link):
    if not link: return None
    link = str(link).lower()
    if 'instagram.com' in link or 'ig.me' in link: return "📸 Instagram"
    if 'facebook.com' in link or 'fb.com' in link or 'fb.watch' in link: return "📘 Facebook"
    if 'youtube.com' in link or 'youtu.be' in link: return "▶️ YouTube"
    if 't.me' in link or 'telegram.me' in link or 'telegram.dog' in link: return "✈️ Telegram"
    if 'tiktok.com' in link: return "🎵 TikTok"
    if 'twitter.com' in link or 'x.com' in link: return "🐦 Twitter"
    return None

def generate_progress_bar(remains, quantity):
    try:
        if remains is None or remains == "": remains = quantity
        remains = int(remains)
        quantity = int(quantity)
        
        if remains <= 0: return "[██████████] 100%", quantity
        if remains >= quantity: return "[░░░░░░░░░░] 0%", 0
        
        delivered = quantity - remains
        percent = int((delivered / quantity) * 100)
        filled = int(percent / 10)
        bar = "█" * filled + "░" * (10 - filled)
        return f"[{bar}] {percent}%", delivered
    except:
        return "[░░░░░░░░░░] 0%", 0

def get_user_tier(spent):
    if spent >= 50: return "🥇 Gold VIP", 5 
    elif spent >= 10: return "🥈 Silver VIP", 2 
    else: return "🥉 Bronze", 0

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🚀 New Order", "⭐ Favorites")
    markup.add("🔍 Smart Search", "📦 Orders")
    markup.add("💰 Deposit", "📝 Bulk Order") 
    markup.add("👤 Profile", "🤝 Affiliate")
    markup.add("🎟️ Voucher", "💬 Live Chat")
    markup.add("🏆 Leaderboard")
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
# 3. AUTO CRYPTO PAYMENT GATEWAYS
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
    except Exception as e: 
        logging.error(f"Cryptomus URL Error: {e}")
    return None

def create_coinpayments_payment(amount, custom_uid, pub_key, priv_key):
    url = "https://www.coinpayments.net/api.php"
    params = {
        "version": 1, 
        "cmd": "create_transaction",
        "amount": amount, 
        "currency1": "USD", 
        "currency2": "USDT.TRC20",
        "buyer_email": "user@nexusbot.com",
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
    except Exception as e: 
        logging.error(f"CoinPayments URL Error: {e}")
    return None

def create_nowpayments_payment(amount, order_id, api_key, ipn_url):
    url = "https://api.nowpayments.io/v1/invoice"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "price_amount": amount,
        "price_currency": "usd",
        "order_id": str(order_id),
        "ipn_callback_url": ipn_url,
        "success_url": "https://t.me/nexusbot", 
        "cancel_url": "https://t.me/nexusbot"
    }
    try:
        r = requests.post(url, json=payload, headers=headers)
        if r.status_code == 200:
            return r.json().get("invoice_url")
    except Exception as e:
        logging.error(f"NowPayments URL Error: {e}")
    return None

def create_payeer_payment(amount, order_id, merchant_id, secret_key):
    amount_str = f"{float(amount):.2f}"
    desc = base64.b64encode(f"Deposit_{order_id}".encode('utf-8')).decode('utf-8')
    sign_str = f"{merchant_id}:{order_id}:{amount_str}:USD:{desc}:{secret_key}"
    sign = hashlib.sha256(sign_str.encode('utf-8')).hexdigest().upper()
    
    url = f"https://payeer.com/merchant/?m_shop={merchant_id}&m_orderid={order_id}&m_amount={amount_str}&m_curr=USD&m_desc={desc}&m_sign={sign}"
    return url

# ==========================================
# 🔥 CUSTOM DRIP-FEED ENGINE (MONGODB ATOMIC LOCKING)
# ==========================================
def custom_drip_feed_cron():
    """
    এই ফাংশনটি প্রতি ১ মিনিট পরপর ডাটাবেস চেক করবে।
    MongoDB-এর Atomic Lock ব্যবহার করা হয়েছে, তাই Redis ছাড়াই 
    একাধিক ওয়ার্কার ক্র্যাশ বা ডুপ্লিকেট অর্ডার প্লেস করবে না।
    """
    # ফাংশনের ভেতরে ইমপোর্ট করা হচ্ছে যাতে Circular Import Error না হয়
    from loader import scheduled_col, orders_col, bot
    import api
    
    # বট স্টার্ট হওয়ার পর ১০ সেকেন্ড অপেক্ষা করবে, যাতে ডাটাবেস কানেকশন ঠিকমতো সেটেল হয়
    time.sleep(10)
    
    while True:
        try:
            now = datetime.now()
            
            # MongoDB Atomic Lock: এমন অর্ডার খুঁজবে যার সময় হয়েছে এবং যা অন্য কোনো ওয়ার্কার লক করেনি
            # find_one_and_update নিশ্চিত করে যে একই সময়ে ২টি ওয়ার্কার একই অর্ডার পাবে না
            task = scheduled_col.find_one_and_update(
                {
                    "status": "active",
                    "next_run": {"$lte": now},
                    "$or": [
                        {"locked": {"$ne": True}},
                        {"lock_expire": {"$lt": now}} # যদি কোনো ওয়ার্কার ক্র্যাশ করে, তবে ২ মিনিট পর লক খুলে যাবে
                    ]
                },
                {"$set": {"locked": True, "lock_expire": now + timedelta(minutes=2)}},
                return_document=ReturnDocument.AFTER
            )
            
            if not task:
                # যদি কোনো পেন্ডিং কাজ না থাকে, তবে ১ মিনিট ঘুমিয়ে থাকবে
                time.sleep(60)
                continue
                
            # --- আমরা টাস্ক পেয়েছি এবং এটি লকড! এবার মেইন প্যানেলে অর্ডার পাঠাব ---
            uid = task["uid"]
            sid = task["sid"]
            link = task["link"]
            qty = task["qty_per_run"]
            
            # মেইন প্যানেলে সিঙ্গেল অর্ডার প্লেস করা
            res = api.place_order(sid, link=link, quantity=qty)
            
            if res and 'order' in res:
                # মেইন orders কালেকশনে সেভ করা (যাতে ইউজার তার অর্ডারে দেখতে পারে)
                orders_col.insert_one({
                    "oid": res['order'], 
                    "uid": uid, 
                    "sid": sid, 
                    "link": link, 
                    "qty": qty, 
                    "cost": task.get('cost_per_run', 0), 
                    "status": "pending", 
                    "date": datetime.now(),
                    "is_drip_child": True # এটি দিয়ে বোঝা যাবে যে এটি অটোমেটিক ড্রিপ-ফিড থেকে এসেছে
                })
                
                runs_left = task.get("runs_left", 1) - 1
                
                if runs_left > 0:
                    # আরও রান বাকি আছে, তাই পরবর্তী সময় সেট করে লক আনলক করা
                    next_run_time = now + timedelta(minutes=task.get("interval", 15))
                    scheduled_col.update_one(
                        {"_id": task["_id"]},
                        {"$set": {"runs_left": runs_left, "next_run": next_run_time, "locked": False}}
                    )
                else:
                    # সবগুলো রান শেষ! স্ট্যাটাস কমপ্লিট করে দেওয়া
                    scheduled_col.update_one(
                        {"_id": task["_id"]},
                        {"$set": {"runs_left": 0, "status": "completed", "locked": False}}
                    )
                    # ইউজারকে মেসেজ দেওয়া
                    try:
                        bot.send_message(
                            uid, 
                            f"✅ **AUTO-ORDER COMPLETED!**\nআপনার `{link}` লিংকের সবগুলো ({task.get('runs_total', 1)} বার) অর্ডার সফলভাবে পাঠানো শেষ হয়েছে।", 
                            parse_mode="Markdown"
                        )
                    except Exception: 
                        pass
                        
            else:
                # API ফেইল করলে লক আনলক করে দেওয়া, যাতে পরের মিনিটে আবার ট্রাই করে
                scheduled_col.update_one({"_id": task["_id"]}, {"$set": {"locked": False}})
                
        except Exception as e:
            logging.error(f"Custom Drip Feed Error: {e}")
            time.sleep(30) # এরর হলে ৩০ সেকেন্ড অপেক্ষা করে আবার ট্রাই করবে

# থ্রেড চালু করা (Daemon=True দেওয়ার কারণে মেইন সার্ভার বন্ধ হলে এটিও নিজে থেকে বন্ধ হয়ে যাবে)
threading.Thread(target=custom_drip_feed_cron, daemon=True).start()

