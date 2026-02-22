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
        s = {"_id": "settings", "channels": [], "profit_margin": 20.0, "maintenance": False, "maintenance_msg": "Bot is upgrading.", "payments": [], "ref_bonus": 0.05, "dep_commission": 5.0, "welcome_bonus_active": False, "welcome_bonus": 0.0, "flash_sale_active": False, "flash_sale_discount": 0.0, "reward_top1": 10.0, "reward_top2": 5.0, "reward_top3": 2.0, "best_choice_sids": []}
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
        try: bot.send_message(uid, "🛡 **ANTI-SPAM!** You are temporarily blocked.", parse_mode="Markdown")
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
                    try: bot.send_message(uid, "💎 **VIP Reminder!**\nIt's been 15 days of awesomeness. As a loyal user, we invite you to check our Best Choice services today!", parse_mode="Markdown")
                    except: pass
                    users_col.update_one({"_id": uid}, {"$set": {"drip_15": True}})
        except: pass
        time.sleep(43200)
threading.Thread(target=drip_campaign_cron, daemon=True).start()

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
                        try:
                            msg = f"🔔 **ORDER UPDATE!**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Order ID: `{o['oid']}`\n🔗 Link: {str(o.get('link', 'N/A'))[:25]}...\n📦 Status: **{new_status.upper()}**"
                            bot.send_message(o['uid'], msg, parse_mode="Markdown")
                        except: pass
                        if new_status in ['canceled', 'refunded', 'fail']:
                            u = users_col.find_one({"_id": o['uid']})
                            curr = u.get("currency", "BDT") if u else "BDT"
                            cost_str = fmt_curr(o['cost'], curr)
                            users_col.update_one({"_id": o['uid']}, {"$inc": {"balance": o['cost'], "spent": -o['cost']}})
                            try: bot.send_message(o['uid'], f"💰 **ORDER REFUNDED!**\nOrder `{o['oid']}` canceled. `{cost_str}` added back to your balance.", parse_mode="Markdown")
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

# ==========================================
# 3. FORCE SUB & START LOGIC
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
    if check_spam(uid) or check_maintenance(uid): return
    
    hour = datetime.now().hour
    greeting = "🌅 Good Morning" if hour < 12 else "☀️ Good Afternoon" if hour < 18 else "🌙 Good Evening"
    
    user = users_col.find_one({"_id": uid})
    if not user:
        users_col.insert_one({"_id": uid, "name": message.from_user.first_name, "balance": 0.0, "spent": 0.0, "points": 0, "currency": "BDT", "ref_paid": False, "ref_earnings": 0.0, "joined": datetime.now(), "favorites": []})
        user = users_col.find_one({"_id": uid})
        
    if not check_sub(uid):
        markup = types.InlineKeyboardMarkup()
        for ch in get_settings().get("channels", []): markup.add(types.InlineKeyboardButton(f"📢 Join Channel", url=f"https://t.me/{ch.replace('@','')}"))
        markup.add(types.InlineKeyboardButton("🟢 VERIFY ACCOUNT 🟢", callback_data="CHECK_SUB"))
        return bot.send_message(uid, "🛑 **ACCESS RESTRICTED**\nYou must join our official channels to unlock the bot.", reply_markup=markup, parse_mode="Markdown")

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

@bot.callback_query_handler(func=lambda c: c.data == "CHECK_SUB")
def sub_callback(call):
    bot.answer_callback_query(call.id)
    uid = call.message.chat.id
    if check_sub(uid):
        bot.delete_message(uid, call.message.message_id)
        bot.send_message(uid, "✅ **Access Granted! Welcome to the panel.**", reply_markup=main_menu())
        s = get_settings()
        user = users_col.find_one({"_id": uid})
        if s.get('welcome_bonus_active') and not user.get("welcome_paid"):
            w_bonus = s.get('welcome_bonus', 0.0)
            if w_bonus > 0:
                users_col.update_one({"_id": uid}, {"$inc": {"balance": w_bonus}, "$set": {"welcome_paid": True}})
                bot.send_message(uid, f"🎁 **WELCOME BONUS!**\nCongratulations! You received `${w_bonus}` just for joining us.", parse_mode="Markdown")
    else: bot.send_message(uid, "❌ You haven't joined all channels.")

# ==========================================
# 4. ORDERING ENGINE
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def new_order_start(message):
    uid = message.chat.id
    users_col.update_one({"_id": uid}, {"$unset": {"step": "", "temp_sid": "", "temp_link": ""}})
    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    services = get_cached_services()
    if not services: return bot.send_message(uid, "⏳ **API Syncing...** Try again in 5 seconds.")
    
    hidden = get_settings().get("hidden_services", [])
    platforms = sorted(list(set(identify_platform(s['category']) for s in services if str(s['service']) not in hidden)))
    markup = types.InlineKeyboardMarkup(row_width=2)
    best_sids = get_settings().get("best_choice_sids", [])
    if best_sids: markup.add(types.InlineKeyboardButton("🌟 ADMIN BEST CHOICE 🌟", callback_data="SHOW_BEST_CHOICE"))
    for p in platforms: markup.add(types.InlineKeyboardButton(p, callback_data=f"PLAT|{p}|0"))
    bot.send_message(uid, "📂 **Select a Platform:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "SHOW_BEST_CHOICE")
def show_best_choices(call):
    bot.answer_callback_query(call.id)
    services = get_cached_services()
    best_sids = get_settings().get("best_choice_sids", [])
    user = users_col.find_one({"_id": call.message.chat.id})
    curr = user.get("currency", "BDT")
    markup = types.InlineKeyboardMarkup(row_width=1)
    for tsid in best_sids:
        srv = next((x for x in services if str(x['service']) == str(tsid).strip()), None)
        if srv:
            rate = calculate_price(srv['rate'], user.get('spent', 0), user.get('custom_discount', 0))
            markup.add(types.InlineKeyboardButton(f"ID:{srv['service']} | {fmt_curr(rate, curr)} | {clean_service_name(srv['name'])}", callback_data=f"INFO|{tsid}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="NEW_ORDER_BACK"))
    bot.edit_message_text("🌟 **ADMIN BEST CHOICE** 🌟\nHandpicked premium services for you:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "NEW_ORDER_BACK")
def back_to_main(call):
    bot.answer_callback_query(call.id)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    new_order_start(call.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("PLAT|"))
def show_cats(call):
    _, platform, page = call.data.split("|")
    page = int(page)
    services = get_cached_services()
    hidden = get_settings().get("hidden_services", [])
    cats = sorted(list(set(s['category'] for s in services if identify_platform(s['category']) == platform and str(s['service']) not in hidden)))
    start_idx, end_idx = page * 15, page * 15 + 15
    markup = types.InlineKeyboardMarkup(row_width=1)
    for cat in cats[start_idx:end_idx]:
        idx = sorted(list(set(s['category'] for s in services))).index(cat)
        markup.add(types.InlineKeyboardButton(f"📁 {cat[:35]}", callback_data=f"CAT|{idx}|0"))
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"PLAT|{platform}|{page-1}"))
    if end_idx < len(cats): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"PLAT|{platform}|{page+1}"))
    if nav: markup.row(*nav)
    bot.edit_message_text(f"📍 **{platform}**\n━━━━━━━━━━━━━━━━━━━━\n📂 **Choose Category:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("CAT|"))
def list_servs(call):
    _, cat_idx, page = call.data.split("|")
    services = get_cached_services()
    cat_name = sorted(list(set(s['category'] for s in services)))[int(cat_idx)]
    hidden = get_settings().get("hidden_services", [])
    filtered = [s for s in services if s['category'] == cat_name and str(s['service']) not in hidden]
    start_idx, end_idx = int(page) * 10, int(page) * 10 + 10
    
    user = users_col.find_one({"_id": call.message.chat.id})
    curr = user.get("currency", "BDT")
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in filtered[start_idx:end_idx]:
        rate = calculate_price(s['rate'], user.get('spent',0), user.get('custom_discount', 0))
        markup.add(types.InlineKeyboardButton(f"ID:{s['service']} | {fmt_curr(rate, curr)} | {clean_service_name(s['name'])}", callback_data=f"INFO|{s['service']}"))
    
    nav = []
    if int(page) > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CAT|{cat_idx}|{int(page)-1}"))
    if end_idx < len(filtered): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CAT|{cat_idx}|{int(page)+1}"))
    if nav: markup.row(*nav)
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"PLAT|{identify_platform(cat_name)}|0"))
    bot.edit_message_text(f"📦 **{cat_name[:30]}**\n━━━━━━━━━━━━━━━━━━━━\nSelect Service:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|"))
def info_card(call):
    sid = call.data.split("|")[1]
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    if not s: return bot.send_message(call.message.chat.id, "❌ Service unavailable.")
    
    user = users_col.find_one({"_id": call.message.chat.id})
    curr = user.get("currency", "BDT")
    rate = calculate_price(s['rate'], user.get('spent',0), user.get('custom_discount', 0))
    avg_time = s.get('time', 'Instant - 24h') if s.get('time') != "" else 'Instant - 24h'

    txt = (f"ℹ️ **SERVICE DETAILS**\n━━━━━━━━━━━━━━━━━━━━\n🏷 **Name:** {clean_service_name(s['name'])}\n🆔 **ID:** `{sid}`\n"
           f"💰 **Price:** `{fmt_curr(rate, curr)}` / 1000\n📉 **Min:** {s.get('min','0')} | 📈 **Max:** {s.get('max','0')}\n"
           f"⏱ **Live Avg Time:** `{avg_time}`⚡️\n━━━━━━━━━━━━━━━━━━━━")
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🛒 Order Now", callback_data=f"ORD|{sid}"), types.InlineKeyboardButton("⭐ Fav", callback_data=f"FAV_ADD|{sid}"))
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ORD|"))
def start_ord(call):
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"step": "awaiting_link", "temp_sid": sid}})
    bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**\n_(Any link format supported)_", parse_mode="Markdown")

# ==========================================
# 5. UNIVERSAL PROFILE, ORDERS & POINTS
# ==========================================
def fetch_orders_page(chat_id, page=0):
    user = users_col.find_one({"_id": chat_id})
    curr = user.get("currency", "BDT") if user else "BDT"
    all_orders = list(orders_col.find({"uid": chat_id}).sort("_id", -1))
    if not all_orders: return "📭 No orders found.", None
    
    start, end = page * 3, page * 3 + 3
    page_orders = all_orders[start:end]
    txt = f"📦 **YOUR ORDERS (Page {page+1}/{math.ceil(len(all_orders)/3)})**\n━━━━━━━━━━━━━━━━━━━━\n"
    markup = types.InlineKeyboardMarkup(row_width=2)
    for o in page_orders:
        st = str(o.get('status', 'pending')).lower()
        st_txt = f"✅ {st.upper()}" if st == 'completed' else f"❌ {st.upper()}" if st in ['canceled', 'refunded', 'fail'] else f"⏳ {st.upper()}"
        txt += f"🆔 `{o['oid']}` | 💰 `{fmt_curr(o['cost'], curr)}`\n🔗 {str(o.get('link', 'N/A'))[:25]}...\n🏷 Status: {st_txt}\n\n"
        row_btns = [types.InlineKeyboardButton(f"🔁 Reorder", callback_data=f"REORDER|{o.get('sid', 0)}")]
        if st in ['completed', 'partial'] and not o.get("is_shadow"):
            row_btns.append(types.InlineKeyboardButton(f"🔄 Refill", callback_data=f"INSTANT_REFILL|{o['oid']}"))
        markup.row(*row_btns)
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"MYORD|{page-1}"))
    if end < len(all_orders): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"MYORD|{page+1}"))
    if nav: markup.row(*nav)
    return txt, markup

@bot.callback_query_handler(func=lambda c: c.data.startswith("INSTANT_REFILL|"))
def process_instant_refill(call):
    oid = call.data.split("|")[1]
    res = api.send_refill(oid)
    if res and 'refill' in res: bot.answer_callback_query(call.id, f"✅ Auto-Refill Triggered! Task ID: {res['refill']}", show_alert=True)
    else: bot.answer_callback_query(call.id, "❌ Refill not available for this order.", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("MYORD|"))
def my_orders_pagination(call):
    page = int(call.data.split("|")[1])
    txt, markup = fetch_orders_page(call.message.chat.id, page)
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data == "REDEEM_POINTS")
def redeem_points(call):
    u = users_col.find_one({"_id": call.message.chat.id})
    pts = u.get("points", 0)
    if pts < 1000: return bot.answer_callback_query(call.id, "❌ Min 1000 Points required to redeem.", show_alert=True)
    reward = pts / 1000.0
    users_col.update_one({"_id": call.message.chat.id}, {"$inc": {"balance": reward}, "$set": {"points": 0}})
    bot.answer_callback_query(call.id, f"✅ Redeemed {pts} Points for ${reward:.2f}!", show_alert=True)
    bot.delete_message(call.message.chat.id, call.message.message_id)

def universal_buttons(message):
    uid = message.chat.id
    users_col.update_one({"_id": uid}, {"$unset": {"step": "", "temp_sid": "", "temp_link": ""}})
    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    u = users_col.find_one({"_id": uid})
    curr = u.get("currency", "BDT") if u else "BDT"

    if message.text == "📦 Orders":
        txt, markup = fetch_orders_page(uid, 0)
        bot.send_message(uid, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
    elif message.text == "💰 Deposit":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_deposit_amt"}})
        bot.send_message(uid, f"💵 **Enter Deposit Amount ({curr}):**", parse_mode="Markdown")
    elif message.text == "👤 Profile":
        tier = u.get('tier_override') if u.get('tier_override') else get_user_tier(u.get('spent', 0))[0]
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(types.InlineKeyboardButton("🟢 BDT", callback_data="SET_CURR|BDT"), types.InlineKeyboardButton("🟠 INR", callback_data="SET_CURR|INR"), types.InlineKeyboardButton("🔵 USD", callback_data="SET_CURR|USD"))
        markup.add(types.InlineKeyboardButton(f"🎁 Redeem Points ({u.get('points', 0)} pts)", callback_data="REDEEM_POINTS"))
        card = f"```text\n╔════════════════════════════════╗\n║  🌟 NEXUS VIP PASSPORT         ║\n╠════════════════════════════════╣\n║  👤 Name: {str(message.from_user.first_name)[:12].ljust(19)}║\n║  🆔 UID: {str(uid).ljust(20)}║\n║  💳 Balance: {fmt_curr(u.get('balance',0), curr).ljust(18)}║\n║  💸 Spent: {fmt_curr(u.get('spent',0), curr).ljust(20)}║\n║  🏆 Points: {str(u.get('points', 0)).ljust(19)}║\n║  👑 Tier: {tier.ljust(19)}║\n╚════════════════════════════════╝\n```"
        bot.send_message(uid, card, reply_markup=markup, parse_mode="Markdown")
    elif message.text == "💬 Live Chat":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_live_chat"}})
        bot.send_message(uid, "💬 **LIVE CHAT SUPPORT**\nSend your message here. Admin will reply directly!", parse_mode="Markdown")

# ==========================================
# 6. ULTIMATE ADMIN DASHBOARD (2-PAGES)
# ==========================================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if str(message.chat.id) != str(ADMIN_ID): return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Net Worth & Stats", callback_data="ADM_STATS"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="ADM_BC"),
        types.InlineKeyboardButton("👻 Ghost Login", callback_data="ADM_GHOST"),
        types.InlineKeyboardButton("📩 Custom Alert", callback_data="ADM_ALERT"),
        types.InlineKeyboardButton("⚙️ Advanced Settings", callback_data="ADM_SETTINGS")
    )
    bot.send_message(message.chat.id, f"👑 **BOSS DASHBOARD**\nUsers: `{users_col.count_documents({})}`\nSelect an action:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ADM_"))
def admin_callbacks(call):
    if str(call.message.chat.id) != str(ADMIN_ID): return
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    
    if call.data == "ADM_HOME":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 Net Worth & Stats", callback_data="ADM_STATS"),
            types.InlineKeyboardButton("📢 Broadcast", callback_data="ADM_BC"),
            types.InlineKeyboardButton("👻 Ghost Login", callback_data="ADM_GHOST"),
            types.InlineKeyboardButton("📩 Custom Alert", callback_data="ADM_ALERT"),
            types.InlineKeyboardButton("⚙️ Advanced Settings", callback_data="ADM_SETTINGS")
        )
        bot.edit_message_text(f"👑 **BOSS DASHBOARD**\nUsers: `{users_col.count_documents({})}`\nSelect an action:", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "ADM_SETTINGS":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("💰 Profit Margin", callback_data="ADM_PROFIT"),
            types.InlineKeyboardButton("🚧 Maint. Mode", callback_data="ADM_MAIN"),
            types.InlineKeyboardButton("🎁 Welcome Bonus", callback_data="ADM_WBONUS"),
            types.InlineKeyboardButton("⚡ Flash Sale", callback_data="ADM_FSALE"),
            types.InlineKeyboardButton("🌟 Best Choice SIDs", callback_data="ADM_BEST"),
            types.InlineKeyboardButton("🔙 Back to Main", callback_data="ADM_HOME")
        )
        bot.edit_message_text("⚙️ **ADVANCED BOT SETTINGS**\nControl automation features here:", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "ADM_STATS":
        bal = sum(u.get('balance', 0) for u in users_col.find())
        spt = sum(u.get('spent', 0) for u in users_col.find())
        bot.send_message(uid, f"📈 **FINANCIAL REPORT**\n\n💰 **Bot Net Worth (User Wallets):** `${bal:.2f}`\n💸 **Total Sales Revenue:** `${spt:.2f}`", parse_mode="Markdown")
    
    elif call.data == "ADM_GHOST":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_ghost_uid"}})
        bot.send_message(uid, "👻 **GHOST LOGIN**\nEnter Target User's ID:")
    elif call.data == "ADM_ALERT":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_alert_uid"}})
        bot.send_message(uid, "📩 **CUSTOM ALERT**\nEnter Target User's ID:")
    elif call.data == "ADM_BC":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_bc"}})
        bot.send_message(uid, "📢 **Enter message for broadcast:**")
    elif call.data == "ADM_PROFIT":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_profit"}})
        bot.send_message(uid, "💹 **Enter New Profit Margin (%):**")
    elif call.data == "ADM_WBONUS":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_wbonus"}})
        bot.send_message(uid, "🎁 **Welcome Bonus**\nEnter bonus amount in $ (e.g. 0.50). Enter 0 to disable:")
    elif call.data == "ADM_FSALE":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_fsale"}})
        bot.send_message(uid, "⚡ **Flash Sale**\nEnter discount percentage (e.g. 10). Enter 0 to disable:")
    elif call.data == "ADM_BEST":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_best"}})
        bot.send_message(uid, "🌟 **Best Choice Services**\nEnter Service IDs separated by comma (e.g. 15, 23, 104):")
    elif call.data == "ADM_MAIN":
        s = get_settings()
        ns = not s.get('maintenance', False)
        config_col.update_one({"_id": "settings"}, {"$set": {"maintenance": ns}})
        global SETTINGS_CACHE
        if SETTINGS_CACHE["data"]: SETTINGS_CACHE["data"]["maintenance"] = ns
        bot.send_message(uid, f"✅ Maintenance Mode is now: {'**ON**' if ns else '**OFF**'}", parse_mode="Markdown")

# ==========================================
# 7. MASTER ROUTER & FINAL ACTIONS
# ==========================================
@bot.message_handler(func=lambda m: True)
def text_router(message):
    uid = message.chat.id
    text = message.text.strip() if message.text else ""
    if text.startswith('/'): return
    
    if str(uid) == str(ADMIN_ID) and message.reply_to_message:
        reply_text = message.reply_to_message.text
        if "ID: " in reply_text:
            try:
                target_uid = int(reply_text.split("ID: ")[1].split("\n")[0].strip().replace("`", ""))
                bot.send_message(target_uid, f"👨‍💻 **ADMIN REPLY:**\n{text}", parse_mode="Markdown")
                return bot.send_message(ADMIN_ID, "✅ Reply sent successfully!")
            except: pass

    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    if text in ["🚀 New Order", "⭐ Favorites", "🔍 Smart Search", "📦 Orders", "💰 Deposit", "🤝 Affiliate", "👤 Profile", "🎟️ Voucher", "🏆 Leaderboard", "💬 Live Chat"]:
        return universal_buttons(message)

    u = users_col.find_one({"_id": uid})
    step = u.get("step") if u else ""

    # --- ADMIN STATES ---
    if str(uid) == str(ADMIN_ID):
        if step == "awaiting_ghost_uid":
            try: target = int(text)
            except: return bot.send_message(uid, "❌ ID must be numbers.")
            tu = users_col.find_one({"_id": target})
            if not tu: return bot.send_message(uid, "❌ User not found.")
            users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
            return bot.send_message(uid, f"👻 **GHOST VIEW - UID: {target}**\nName: {tu.get('name')}\nBal: ${tu.get('balance', 0):.3f}\nSpent: ${tu.get('spent', 0):.3f}\nPoints: {tu.get('points', 0)}")
            
        elif step == "awaiting_alert_uid":
            try:
                target = int(text)
                users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_alert_msg", "temp_uid": target}})
                return bot.send_message(uid, f"✍️ Enter alert msg for `{target}`:", parse_mode="Markdown")
            except: return bot.send_message(uid, "❌ Invalid ID.")
            
        elif step == "awaiting_alert_msg":
            target = u.get("temp_uid")
            users_col.update_one({"_id": uid}, {"$unset": {"step": "", "temp_uid": ""}})
            try:
                bot.send_message(target, f"⚠️ **SYSTEM ALERT**\n━━━━━━━━━━━━━━━━━━━━\n{text}", parse_mode="Markdown")
                return bot.send_message(uid, "✅ Alert Sent!")
            except: return bot.send_message(uid, "❌ Failed to send.")
            
        elif step == "awaiting_wbonus":
            try:
                amt = float(text)
                status = amt > 0
                config_col.update_one({"_id": "settings"}, {"$set": {"welcome_bonus": amt, "welcome_bonus_active": status}})
                users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
                return bot.send_message(uid, f"✅ Welcome Bonus set to ${amt}. Status: {'ON' if status else 'OFF'}")
            except: return bot.send_message(uid, "❌ Invalid number.")
            
        elif step == "awaiting_fsale":
            try:
                disc = float(text)
                status = disc > 0
                config_col.update_one({"_id": "settings"}, {"$set": {"flash_sale_discount": disc, "flash_sale_active": status}})
                users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
                return bot.send_message(uid, f"✅ Flash Sale set to {disc}%. Status: {'ON' if status else 'OFF'}")
            except: return bot.send_message(uid, "❌ Invalid number.")
            
        elif step == "awaiting_best":
            try:
                sids = [int(x.strip()) for x in text.split(",") if x.strip().isdigit()]
                config_col.update_one({"_id": "settings"}, {"$set": {"best_choice_sids": sids}})
                users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
                return bot.send_message(uid, f"✅ Best Choice SIDs updated: {sids}")
            except: return bot.send_message(uid, "❌ Format error. Use comma separated numbers (e.g. 10, 20, 30)")
            
        elif step == "awaiting_profit":
            try:
                v = float(text)
                config_col.update_one({"_id": "settings"}, {"$set": {"profit_margin": v}})
                users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
                return bot.send_message(uid, f"✅ Profit Margin: {v}%")
            except: return bot.send_message(uid, "❌ Invalid number.")
            
        elif step == "awaiting_bc":
            users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
            c = 0
            for usr in users_col.find({"is_fake": {"$ne": True}}):
                try: bot.send_message(usr["_id"], f"📢 **MESSAGE FROM ADMIN**\n━━━━━━━━━━━━━━━━━━━━\n{text}", parse_mode="Markdown"); c+=1
                except: pass
            return bot.send_message(uid, f"✅ Broadcast sent to `{c}` users!")

    # --- USER STATES ---
    if step == "awaiting_link":
        if not re.match(r'^(https?://|t\.me/|@|www\.)[^\s]+$', text, re.IGNORECASE):
            return bot.send_message(uid, "❌ **Invalid Link Format!**")
        existing = orders_col.find_one({"uid": uid, "link": text, "status": "pending"})
        if existing:
            bot.send_message(uid, "⚠️ **WARNING: Order Already Pending for this link!**", parse_mode="Markdown")
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_qty", "temp_link": text}})
        return bot.send_message(uid, "🔢 **Enter Quantity:**", parse_mode="Markdown")

    elif step == "awaiting_qty":
        try:
            qty = int(text)
            sid, link = u.get("temp_sid"), u.get("temp_link")
            services = get_cached_services()
            s = next((x for x in services if str(x['service']) == str(sid)), None)
            if qty < int(s['min']) or qty > int(s['max']):
                return bot.send_message(uid, f"❌ Invalid Qty! Allowed: {s['min']} - {s['max']}")
            rate = calculate_price(s['rate'], u.get('spent', 0), u.get('custom_discount', 0))
            cost = (rate / 1000) * qty
            curr = u.get("currency", "BDT")
            if u.get('balance', 0) < cost: return bot.send_message(uid, f"❌ Low Balance! Need `{fmt_curr(cost, curr)}`")
            users_col.update_one({"_id": uid}, {"$set": {"draft": {"sid": sid, "link": link, "qty": qty, "cost": cost}, "step": ""}})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ CONFIRM", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
            bot.send_message(uid, f"⚠️ **ORDER PREVIEW**\nID: `{sid}`\nLink: {link}\nQty: {qty}\nCost: `{fmt_curr(cost, curr)}`\nConfirm?", reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        except: bot.send_message(uid, "⚠️ Numbers only!")

@bot.callback_query_handler(func=lambda c: c.data == "PLACE_ORD")
def final_ord(call):
    uid = call.message.chat.id
    u = users_col.find_one({"_id": uid})
    draft = u.get('draft')
    if not draft: return bot.answer_callback_query(call.id, "❌ Session expired.")
    res = api.place_order(draft['sid'], draft['link'], draft['qty'])
    if res and 'order' in res:
        points_earned = int(draft['cost'] * 100)
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost'], "points": points_earned}, "$unset": {"draft": ""}})
        orders_col.insert_one({"oid": res['order'], "uid": uid, "sid": draft['sid'], "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], "status": "pending", "date": datetime.now()})
        bot.edit_message_text(f"✅ **Order Placed Successfully!**\n🆔 ID: `{res['order']}`\n🎁 Points Earned: `+{points_earned}`", uid, call.message.message_id, parse_mode="Markdown")
    else: bot.send_message(uid, f"❌ API Error: {res.get('error', 'Timeout')}")

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORD")
def cancel_ord(call):
    users_col.update_one({"_id": call.message.chat.id}, {"$unset": {"draft": "", "step": ""}})
    bot.edit_message_text("🚫 **Order Cancelled.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
