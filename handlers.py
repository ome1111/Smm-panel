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

# 🔥 SUPER FAST SPY SYSTEM
def update_spy(uid, action_text):
    pass

# ==========================================
# 1. CURRENCY ENGINE & SETTINGS CACHE
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
        s = {"_id": "settings", "channels": [], "profit_margin": 20.0, "maintenance": False, "best_choice_sids": []}
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
        return True
    return False

# ==========================================
# 2. AUTO SYNC ENGINE
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

def get_cached_services():
    global GLOBAL_SERVICES_CACHE
    if GLOBAL_SERVICES_CACHE: return GLOBAL_SERVICES_CACHE
    cache = config_col.find_one({"_id": "api_cache"})
    return cache.get('data', []) if cache else []

def calculate_price(base_rate, user_spent, user_custom_discount=0.0):
    s = get_settings()
    profit = s.get('profit_margin', 20.0)
    rate_with_profit = float(base_rate) * (1 + (profit / 100))
    return rate_with_profit * (1 - (user_custom_discount / 100))

def clean_service_name(raw_name):
    n = str(raw_name)
    n = re.sub(r'[-|:._/]+', ' ', n)
    return " ".join(n.split()).strip()[:45]

def identify_platform(cat_name):
    cat = cat_name.lower()
    if 'instagram' in cat or 'ig' in cat: return "📸 Instagram"
    if 'facebook' in cat or 'fb' in cat: return "📘 Facebook"
    if 'youtube' in cat or 'yt' in cat: return "▶️ YouTube"
    if 'telegram' in cat or 'tg' in cat: return "✈️ Telegram"
    return "🌐 Other Services"

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🚀 New Order", "⭐ Favorites")
    markup.add("🔍 Smart Search", "📦 Orders")
    markup.add("💰 Deposit", "🤝 Affiliate")
    markup.add("👤 Profile", "🎟️ Voucher")
    markup.add("🏆 Leaderboard", "💬 Live Chat")
    return markup

# ==========================================
# 3. START & FORCE SUB
# ==========================================
def check_sub(chat_id):
    channels = get_settings().get("channels", [])
    if not channels: return True
    for ch in channels:
        try:
            member = bot.get_chat_member(ch, chat_id)
            if member.status in ['left', 'kicked']: return False
        except: return False
    return True

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    users_col.update_one({"_id": uid}, {"$set": {"last_active": datetime.now()}, "$unset": {"step": "", "temp_sid": "", "temp_link": ""}}, upsert=True)
    
    if not check_sub(uid):
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🟢 VERIFY ACCOUNT 🟢", callback_data="CHECK_SUB"))
        return bot.send_message(uid, "🛑 **ACCESS RESTRICTED**\nJoin our channel to unlock the bot.", reply_markup=markup, parse_mode="Markdown")

    hour = datetime.now().hour
    greeting = "🌅 Good Morning" if hour < 12 else "☀️ Good Afternoon" if hour < 18 else "🌙 Good Evening"
    
    # Cyberpunk Welcome
    welcome_text = f"""{greeting}, {message.from_user.first_name}! ⚡️

🚀 **𝗪𝗘𝗟𝗖𝗢𝗠𝗘 𝗧𝗢 𝗡𝗘𝗫𝗨𝗦 𝗦𝗠𝗠**
_"Your Ultimate Social Growth Engine"_
━━━━━━━━━━━━━━━━━━━━━
👤 **𝗨𝘀𝗲𝗿:** {message.from_user.first_name}
🆔 **𝗦𝘆𝘀𝘁𝗲𝗺 𝗜𝗗:** `{uid}`
👑 **𝗦𝘁𝗮𝘁𝘂𝘀:** Connected 🟢
━━━━━━━━━━━━━━━━━━━━━
Let's boost your digital presence today! 👇"""
    bot.send_message(uid, welcome_text, reply_markup=main_menu(), parse_mode="Markdown")

# ==========================================
# 4. ORDERING SYSTEM
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def new_order_start(message):
    services = get_cached_services()
    platforms = sorted(list(set(identify_platform(s['category']) for s in services)))
    markup = types.InlineKeyboardMarkup(row_width=2)
    for p in platforms: markup.add(types.InlineKeyboardButton(p, callback_data=f"PLAT|{p}|0"))
    bot.send_message(message.chat.id, "📂 **Select a Platform:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|"))
def info_card(call):
    sid = call.data.split("|")[1]
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    if not s: return
    
    user = users_col.find_one({"_id": call.message.chat.id})
    curr = user.get("currency", "BDT")
    rate = calculate_price(s['rate'], 0, user.get('custom_discount', 0))
    
    # Live Average Time Logic
    avg_time = s.get('time', 'Instant - 24h')
    
    txt = f"ℹ️ **SERVICE DETAILS**\n━━━━━━━━━━━━━━━━━━━━\n🏷 **Name:** {s['name']}\n🆔 **ID:** `{sid}`\n💰 **Price:** `{fmt_curr(rate, curr)}` / 1000\n📉 **Min:** {s.get('min','0')} | 📈 **Max:** {s.get('max','0')}\n⏱ **Live Time:** `{avg_time}`\n━━━━━━━━━━━━━━━━━━━━"
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🛒 Order Now", callback_data=f"ORD|{sid}"), types.InlineKeyboardButton("⭐ Fav", callback_data=f"FAV_ADD|{sid}"))
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

# ==========================================
# 5. MASTER ROUTER (Link Warning & Live Chat)
# ==========================================
@bot.message_handler(func=lambda m: True)
def text_router(message):
    uid = message.chat.id
    text = message.text.strip()
    u = users_col.find_one({"_id": uid})
    if not u: return
    step = u.get("step")

    # Admin Live Chat Reply
    if str(uid) == str(ADMIN_ID) and message.reply_to_message:
        reply_text = message.reply_to_message.text
        if "ID: " in reply_text:
            try:
                target_uid = int(reply_text.split("ID: ")[1].split("\n")[0].strip().replace("`", ""))
                bot.send_message(target_uid, f"👨‍💻 **ADMIN REPLY:**\n{text}", parse_mode="Markdown")
                return bot.send_message(ADMIN_ID, "✅ Reply sent!")
            except: pass

    if text in ["🚀 New Order", "⭐ Favorites", "🔍 Smart Search", "📦 Orders", "💰 Deposit", "🤝 Affiliate", "👤 Profile", "🎟️ Voucher", "🏆 Leaderboard", "💬 Live Chat"]:
        return universal_buttons(message)

    if step == "awaiting_link":
        # Duplicate Link Warning
        existing = orders_col.find_one({"uid": uid, "link": text, "status": "pending"})
        if existing:
            bot.send_message(uid, "⚠️ **WARNING:** You have a pending order with this link!", parse_mode="Markdown")
        
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_qty", "temp_link": text}})
        return bot.send_message(uid, "🔢 **Enter Quantity:**", parse_mode="Markdown")

    elif step == "awaiting_qty":
        try:
            qty = int(text)
            sid, link = u.get("temp_sid"), u.get("temp_link")
            services = get_cached_services()
            s = next((x for x in services if str(x['service']) == str(sid)), None)
            rate = calculate_price(s['rate'], 0, u.get('custom_discount', 0))
            cost = (rate / 1000) * qty
            if u.get('balance', 0) < cost: return bot.send_message(uid, "❌ Insufficient Balance!")
            
            users_col.update_one({"_id": uid}, {"$set": {"draft": {"sid": sid, "link": link, "qty": qty, "cost": cost}, "step": ""}})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ CONFIRM", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
            bot.send_message(uid, f"⚠️ **ORDER PREVIEW**\nID: {sid}\nLink: {link}\nQty: {qty}\nCost: {fmt_curr(cost, u.get('currency', 'BDT'))}", reply_markup=markup, parse_mode="Markdown")
        except: bot.send_message(uid, "⚠️ Numbers only!")

def universal_buttons(message):
    uid = message.chat.id
    if message.text == "💬 Live Chat":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_live_chat"}})
        bot.send_message(uid, "💬 **LIVE CHAT SUPPORT**\nSend your message here:", parse_mode="Markdown")
    # ... Other buttons like profile/orders go here (same as before)

@bot.callback_query_handler(func=lambda c: c.data == "PLACE_ORD")
def final_ord(call):
    uid = call.message.chat.id
    u = users_col.find_one({"_id": uid})
    draft = u.get('draft')
    res = api.place_order(draft['sid'], draft['link'], draft['qty'])
    if res and 'order' in res:
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost']}, "$unset": {"draft": ""}})
        orders_col.insert_one({"oid": res['order'], "uid": uid, "sid": draft['sid'], "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], "status": "pending", "date": datetime.now()})
        bot.edit_message_text(f"✅ **Order Placed!** ID: `{res['order']}`", uid, call.message.message_id, parse_mode="Markdown")
