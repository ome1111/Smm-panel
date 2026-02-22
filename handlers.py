import sys
import io
import math
import time
import os
import threading
import re
import random
from datetime import datetime

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

# 🔥 SETTINGS RAM CACHE (No Database Delay)
SETTINGS_CACHE = {"data": None, "time": 0}

def get_settings():
    global SETTINGS_CACHE
    if SETTINGS_CACHE["data"] and time.time() - SETTINGS_CACHE["time"] < 30:
        return SETTINGS_CACHE["data"]
    
    s = config_col.find_one({"_id": "settings"})
    if not s:
        s = {
            "_id": "settings", "channels": [], "profit_margin": 20.0, 
            "maintenance": False, "maintenance_msg": "Bot is upgrading.",
            "payments": [], "ref_bonus": 0.05, "dep_commission": 5.0, 
            "welcome_bonus_active": False, "welcome_bonus": 0.0,
            "flash_sale_active": False, "flash_sale_discount": 0.0,
            "reward_top1": 10.0, "reward_top2": 5.0, "reward_top3": 2.0
        }
        config_col.insert_one(s)
    
    SETTINGS_CACHE["data"] = s
    SETTINGS_CACHE["time"] = time.time()
    return s

def check_spam(uid):
    if str(uid) == str(ADMIN_ID): return False 
    current_time = time.time()
    if uid in blocked_users:
        if current_time < blocked_users[uid]: return True
        else: del blocked_users[uid]
    if uid not in user_actions: user_actions[uid] = []
    user_actions[uid].append(current_time)
    user_actions[uid] = [t for t in user_actions[uid] if current_time - t < 3]
    if len(user_actions[uid]) > 5:
        blocked_users[uid] = current_time + 300
        try: bot.send_message(uid, "🛡 **ANTI-SPAM!** You are temporarily blocked.", parse_mode="Markdown")
        except Exception: pass
        return True
    return False

def check_maintenance(chat_id):
    s = get_settings()
    if s.get('maintenance', False) and str(chat_id) != str(ADMIN_ID):
        msg = s.get('maintenance_msg', "Bot is currently upgrading to serve you better. Please try again later.")
        bot.send_message(chat_id, f"🚧 **SYSTEM MAINTENANCE**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
        return True
    return False

# ==========================================
# 2. PRO-LEVEL CACHE ENGINE & AUTO SYNC
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
        except Exception: 
            pass
        time.sleep(600)

threading.Thread(target=auto_sync_services_cron, daemon=True).start()

# 🔥 AUTO ORDER STATUS SYNC ENGINE (1xpanel Sync)
def auto_sync_orders_cron():
    while True:
        try:
            active_orders = list(orders_col.find({"status": {"$nin": ["completed", "canceled", "refunded", "fail", "partial"]}}))
            for o in active_orders:
                if o.get("is_shadow"): 
                    continue
                
                try:
                    res = api.check_order_status(o['oid'])
                except AttributeError:
                    continue # API code missing warning bypass
                    
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
                            try:
                                bot.send_message(o['uid'], f"💰 **ORDER REFUNDED!**\nOrder `{o['oid']}` canceled. `{cost_str}` added back to your balance.", parse_mode="Markdown")
                            except: pass
        except Exception:
            pass
        time.sleep(120)

threading.Thread(target=auto_sync_orders_cron, daemon=True).start()

def get_cached_services():
    global GLOBAL_SERVICES_CACHE
    if GLOBAL_SERVICES_CACHE: return GLOBAL_SERVICES_CACHE
    cache = config_col.find_one({"_id": "api_cache"})
    if cache and cache.get('data'):
        GLOBAL_SERVICES_CACHE = cache.get('data')
        return GLOBAL_SERVICES_CACHE
    return []

def calculate_price(base_rate, user_spent, user_custom_discount=0.0):
    s = get_settings()
    profit_margin = s.get('profit_margin', 20.0)
    flash_sale = s.get('flash_sale_discount', 0.0) if s.get('flash_sale_active', False) else 0.0
    _, tier_discount = get_user_tier(user_spent)
    total_discount = tier_discount + flash_sale + user_custom_discount
    rate_with_profit = float(base_rate) * (1 + (profit_margin / 100))
    return rate_with_profit * (1 - (total_discount / 100))

def identify_platform(cat_name):
    cat = cat_name.lower()
    if 'instagram' in cat or 'ig' in cat: return "📸 Instagram"
    if 'facebook' in cat or 'fb' in cat: return "📘 Facebook"
    if 'youtube' in cat or 'yt' in cat: return "▶️ YouTube"
    if 'telegram' in cat or 'tg' in cat: return "✈️ Telegram"
    if 'tiktok' in cat: return "🎵 TikTok"
    if 'twitter' in cat or ' x ' in cat: return "🐦 Twitter"
    return "🌐 Other Services"

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
        words = ["Telegram", "TG", "Instagram", "IG", "Facebook", "FB", "YouTube", "YT", "TikTok", "Twitter", 
                 "1xpanel", "Instant", "fast", "NoRefill", "No refill", "Refill", "Stable", "price", "Non drop", "real"]
        for w in words: n = re.sub(r'(?i)\b' + re.escape(w) + r'\b', '', n)
        n = re.sub(r'[-|:._/]+', ' ', n)
        n = " ".join(n.split()).strip()
        return f"{n[:45]} {emojis}".strip() if n else f"Premium Service {emojis}"
    except Exception: return str(raw_name)[:50]

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
        except Exception: return False
    return True

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    update_spy(uid, "Bot Started")
    users_col.update_one({"_id": uid}, {"$unset": {"step": "", "temp_sid": "", "temp_link": ""}})
    bot.clear_step_handler_by_chat_id(uid)
    
    if check_spam(uid) or check_maintenance(uid): return
    
    hour = datetime.now().hour
    greeting = "🌅 Good Morning" if hour < 12 else "☀️ Good Afternoon" if hour < 18 else "🌙 Good Evening"

    args = message.text.split()
    referrer = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid else None

    user = users_col.find_one({"_id": uid})
    if not user:
        users_col.insert_one({"_id": uid, "name": message.from_user.first_name, "balance": 0.0, "spent": 0.0, "currency": "BDT", "ref_by": referrer, "ref_paid": False, "ref_earnings": 0.0, "joined": datetime.now(), "favorites": [], "custom_discount": 0.0, "shadow_banned": False, "tier_override": None, "welcome_paid": False})
        user = users_col.find_one({"_id": uid})
    
    if not check_sub(uid):
        markup = types.InlineKeyboardMarkup()
        for ch in get_settings().get("channels", []): markup.add(types.InlineKeyboardButton(f"📢 Join Channel", url=f"https://t.me/{ch.replace('@','')}"))
        markup.add(types.InlineKeyboardButton("🟢 VERIFY ACCOUNT 🟢", callback_data="CHECK_SUB"))
        bot.send_message(uid, "🛑 **ACCESS RESTRICTED**\nYou must join our official channels to unlock the bot.", reply_markup=markup, parse_mode="Markdown")
        return

    bot.send_message(uid, f"{greeting}, {message.from_user.first_name}! 👋\n**WELCOME TO NEXUS SMM**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **Your ID:** `{uid}`", reply_markup=main_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CHECK_SUB")
def sub_callback(call):
    bot.answer_callback_query(call.id)
    uid = call.message.chat.id
    if check_sub(uid):
        bot.delete_message(uid, call.message.message_id)
        bot.send_message(uid, "✅ **Access Granted! Welcome to the panel.**", reply_markup=main_menu())
        user = users_col.find_one({"_id": uid})
        s = get_settings()
        if s.get('welcome_bonus_active') and not user.get("welcome_paid"):
            w_bonus = s.get('welcome_bonus', 0.0)
            if w_bonus > 0:
                users_col.update_one({"_id": uid}, {"$inc": {"balance": w_bonus}, "$set": {"welcome_paid": True}})
                bot.send_message(uid, f"🎁 **WELCOME BONUS!**\nCongratulations! You received `${w_bonus}` just for joining us.", parse_mode="Markdown")
            else: users_col.update_one({"_id": uid}, {"$set": {"welcome_paid": True}})
        if user and user.get("ref_by") and not user.get("ref_paid"):
            ref_bonus = s.get("ref_bonus", 0.0)
            if ref_bonus > 0:
                users_col.update_one({"_id": user["ref_by"]}, {"$inc": {"balance": ref_bonus, "ref_earnings": ref_bonus}})
                users_col.update_one({"_id": uid}, {"$set": {"ref_paid": True}})
                try: bot.send_message(user["ref_by"], f"🎉 **REFERRAL SUCCESS!**\nUser `{uid}` verified their account. You earned `${ref_bonus}`!", parse_mode="Markdown")
                except: pass
    else: bot.send_message(uid, "❌ You haven't joined all channels. Please join and try again.")

# ==========================================
# 4. SUPER FAST ORDERING ENGINE
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def new_order_start(message):
    update_spy(message.chat.id, "Browsing Platforms")
    users_col.update_one({"_id": message.chat.id}, {"$unset": {"step": "", "temp_sid": "", "temp_link": ""}})
    if check_spam(message.chat.id) or check_maintenance(message.chat.id) or not check_sub(message.chat.id): return
    
    services = get_cached_services()
    if not services: 
        return bot.send_message(message.chat.id, "⏳ **API Syncing...** Please try again in 5 seconds.", parse_mode="Markdown")
        
    hidden = get_settings().get("hidden_services", [])
    platforms = sorted(list(set(identify_platform(s['category']) for s in services if str(s['service']) not in hidden)))
    markup = types.InlineKeyboardMarkup(row_width=2)
    for p in platforms: markup.add(types.InlineKeyboardButton(p, callback_data=f"PLAT|{p}|0"))
    
    s = get_settings()
    banner = f"⚡ **FLASH SALE ACTIVE: {s.get('flash_sale_discount')}% OFF!**\n" if s.get('flash_sale_active') else ""
    bot.send_message(message.chat.id, f"{banner}🔥 **Trending Now:**\n👉 _Telegram Post Views_\n👉 _Instagram Premium Likes_\n━━━━━━━━━━━━━━━━━━━━\n📂 **Select a Platform:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PLAT|"))
def show_cats(call):
    bot.answer_callback_query(call.id)
    _, platform_name, page = call.data.split("|")
    page = int(page)
    services = get_cached_services()
    hidden = get_settings().get("hidden_services", [])
    all_cats = sorted(list(set(s['category'] for s in services if identify_platform(s['category']) == platform_name and str(s['service']) not in hidden)))
    start_idx, end_idx = page * 15, page * 15 + 15
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for cat in all_cats[start_idx:end_idx]:
        idx = sorted(list(set(s['category'] for s in services))).index(cat)
        short_cat = cat.replace(platform_name.split()[1], "").strip()[:35]
        markup.add(types.InlineKeyboardButton(f"📁 {short_cat}", callback_data=f"CAT|{idx}|0"))
        
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"PLAT|{platform_name}|{page-1}"))
    if end_idx < len(all_cats): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"PLAT|{platform_name}|{page+1}"))
    if nav: markup.row(*nav)
    bot.edit_message_text(f"📍 **Home** ➔ **{platform_name}**\n━━━━━━━━━━━━━━━━━━━━\n📂 **Choose Category:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("CAT|"))
def list_servs(call):
    bot.answer_callback_query(call.id)
    _, cat_idx, page = call.data.split("|")
    cat_idx, page = int(cat_idx), int(page)
    services = get_cached_services()
    hidden = get_settings().get("hidden_services", [])
    all_cat_names = sorted(list(set(s['category'] for s in services)))
    cat_name = all_cat_names[cat_idx]
    filtered = [s for s in services if s['category'] == cat_name and str(s['service']) not in hidden]
    start_idx, end_idx = page * 10, page * 10 + 10
    
    user = users_col.find_one({"_id": call.message.chat.id})
    curr = user.get("currency", "BDT")
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for s in filtered[start_idx:end_idx]:
        rate_usd = calculate_price(s['rate'], user.get('spent', 0), user.get('custom_discount', 0))
        markup.add(types.InlineKeyboardButton(f"ID:{s['service']} | {fmt_curr(rate_usd, curr)} | {clean_service_name(s['name'])}", callback_data=f"INFO|{s['service']}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CAT|{cat_idx}|{page-1}"))
    if end_idx < len(filtered): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CAT|{cat_idx}|{page+1}"))
    if nav: markup.row(*nav)
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"PLAT|{identify_platform(cat_name)}|0"))
    bot.edit_message_text(f"📍 **{identify_platform(cat_name)}** ➔ **{cat_name[:20]}**\n━━━━━━━━━━━━━━━━━━━━\n📦 **Select Service:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|") or c.data.startswith("REORDER|"))
def info_card(call):
    bot.answer_callback_query(call.id)
    sid = call.data.split("|")[1]
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    if not s: return bot.send_message(call.message.chat.id, "❌ Service currently unavailable.")
    
    user = users_col.find_one({"_id": call.message.chat.id})
    curr = user.get("currency", "BDT")
    rate_usd = calculate_price(s['rate'], user.get('spent', 0), user.get('custom_discount', 0))
    
    txt = f"ℹ️ **SERVICE DETAILS**\n━━━━━━━━━━━━━━━━━━━━\n🏷 **Name:** {clean_service_name(s['name'])}\n🆔 **ID:** `{sid}`\n💰 **Price:** `{fmt_curr(rate_usd, curr)}` / 1000\n📉 **Min:** {s.get('min','0')} | 📈 **Max:** {s.get('max','0')}\n━━━━━━━━━━━━━━━━━━━━"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🛒 Order Now", callback_data=f"ORD|{sid}"), types.InlineKeyboardButton("⭐ Fav", callback_data=f"FAV_ADD|{sid}"))
    try: cat_idx = sorted(list(set(x['category'] for x in services))).index(s['category'])
    except: cat_idx = 0
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"CAT|{cat_idx}|0"))
    
    if call.message.text and "YOUR ORDERS" in call.message.text: bot.send_message(call.message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")
    else: bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ORD|"))
def start_ord(call):
    bot.answer_callback_query(call.id)
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"step": "awaiting_link", "temp_sid": sid}})
    bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**\n_(Reply with your link)_", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "PLACE_ORD")
def final_ord(call):
    bot.answer_callback_query(call.id)
    uid = call.message.chat.id
    user = users_col.find_one({"_id": uid})
    curr = user.get("currency", "BDT")
    draft = user.get('draft')
    
    if not draft or user.get('balance', 0) < draft['cost']: 
        return bot.edit_message_text("❌ Session expired or low balance.", uid, call.message.message_id)

    bot.edit_message_text("🛒 **Processing Order...**", uid, call.message.message_id, parse_mode="Markdown")

    services = get_cached_services()
    srv = next((x for x in services if str(x['service']) == str(draft['sid'])), None)
    srv_name = clean_service_name(srv['name']) if srv else f"ID: {draft['sid']}"
    
    masked_id = f"***{str(uid)[-4:]}"
    short_srv = srv_name[:22] + ".." if len(srv_name) > 22 else srv_name
    qty_int = int(draft['qty'])
    cost_str = fmt_curr(draft['cost'], curr)
    
    channel_post = f"```text\n╔════ 🟢 𝗡𝗘𝗪 𝗢𝗥𝗗𝗘𝗥 ════╗\n║ 👤 𝗜𝗗: {masked_id}\n║ 🚀 𝗦𝗲𝗿𝘃𝗶𝗰𝗲: {short_srv}\n║ 📦 𝗤𝘁𝘆: {qty_int}\n║ 💵 𝗖𝗼𝘀𝘁: {cost_str}\n╚════════════════════╝\n```"
    s = get_settings()
    proof_ch = s.get('proof_channel', '')

    if user.get('shadow_banned'):
        fake_oid = random.randint(100000, 999999)
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost']}, "$unset": {"draft": ""}})
        orders_col.insert_one({"oid": fake_oid, "uid": uid, "sid": draft['sid'], "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], "status": "pending", "date": datetime.now(), "is_shadow": True})
        
        receipt = f"🧾 **OFFICIAL INVOICE**\n━━━━━━━━━━━━━━━━━━━━\n✅ **Status:** Order Placed Successfully\n🆔 **Order ID:** `{fake_oid}`\n🔗 **Link:** {draft['link']}\n🔢 **Quantity:** {draft['qty']}\n💳 **Paid:** `{cost_str}`\n━━━━━━━━━━━━━━━━━━━━"
        bot.edit_message_text(receipt, uid, call.message.message_id, parse_mode="Markdown", disable_web_page_preview=True)
        if proof_ch:
            try: bot.send_message(proof_ch, channel_post, parse_mode="Markdown")
            except: pass
        return

    res = api.place_order(draft['sid'], draft['link'], draft['qty'])
    if res and 'order' in res:
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost']}, "$unset": {"draft": ""}})
        orders_col.insert_one({"oid": res['order'], "uid": uid, "sid": draft['sid'], "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], "status": "pending", "date": datetime.now()})
        
        receipt = f"🧾 **OFFICIAL INVOICE**\n━━━━━━━━━━━━━━━━━━━━\n✅ **Status:** Order Placed Successfully\n🆔 **Order ID:** `{res['order']}`\n🔗 **Link:** {draft['link']}\n🔢 **Quantity:** {draft['qty']}\n💳 **Paid:** `{cost_str}`\n━━━━━━━━━━━━━━━━━━━━"
        bot.edit_message_text(receipt, uid, call.message.message_id, parse_mode="Markdown", disable_web_page_preview=True)
        if proof_ch:
            try: bot.send_message(proof_ch, channel_post, parse_mode="Markdown")
            except: pass
    else:
        bot.edit_message_text(f"❌ **Error:** {res.get('error', 'API Timeout')}", uid, call.message.message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORD")
def cancel_ord(call):
    bot.answer_callback_query(call.id)
    users_col.update_one({"_id": call.message.chat.id}, {"$unset": {"draft": "", "step": "", "temp_sid": "", "temp_link": ""}})
    bot.edit_message_text("🚫 **Order Cancelled.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

# ==========================================
# 5. PROFILE, ORDERS & PAYMENTS
# ==========================================
@bot.message_handler(func=lambda m: m.text == "👤 Profile")
def profile(message):
    update_spy(message.chat.id, "Viewing Profile")
    users_col.update_one({"_id": message.chat.id}, {"$unset": {"step": "", "temp_sid": "", "temp_link": ""}})
    if check_spam(message.chat.id) or check_maintenance(message.chat.id) or not check_sub(message.chat.id): return
    
    u = users_col.find_one({"_id": message.chat.id})
    curr = u.get("currency", "BDT")
    tier = u.get('tier_override') if u.get('tier_override') else get_user_tier(u.get('spent', 0))[0]
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(types.InlineKeyboardButton("🟢 BDT", callback_data="SET_CURR|BDT"), types.InlineKeyboardButton("🟠 INR", callback_data="SET_CURR|INR"), types.InlineKeyboardButton("🔵 USD", callback_data="SET_CURR|USD"))
    
    card = f"```text\n╔════════════════════════════════╗\n║  🌟 NEXUS VIP PASSPORT         ║\n╠════════════════════════════════╣\n║  👤 Name: {str(message.from_user.first_name)[:12].ljust(19)}║\n║  🆔 UID: {str(u['_id']).ljust(20)}║\n║  💳 Balance: {fmt_curr(u.get('balance',0), curr).ljust(18)}║\n║  💸 Spent: {fmt_curr(u.get('spent',0), curr).ljust(20)}║\n║  👑 Tier: {tier.ljust(19)}║\n╚════════════════════════════════╝\n```"
    if u.get('custom_discount', 0) > 0: card += f"\n🎁 **Special Discount Applied:** `{u.get('custom_discount')}% OFF`"
    bot.send_message(message.chat.id, card, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("SET_CURR|"))
def set_curr(call):
    bot.answer_callback_query(call.id)
    new_curr = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"currency": new_curr}})
    bot.edit_message_text(f"✅ **App Currency updated to {new_curr}!**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

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
        markup.add(types.InlineKeyboardButton(f"🔁 Reorder ID: {o.get('sid', 'N/A')}", callback_data=f"REORDER|{o.get('sid', 0)}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"MYORD|{page-1}"))
    if end < len(all_orders): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"MYORD|{page+1}"))
    if nav: markup.row(*nav)
    users_col.update_one({"_id": chat_id}, {"$set": {"step": "awaiting_refill"}})
    markup.add(types.InlineKeyboardButton("🔄 Request Refill", callback_data="ASK_REFILL"))
    return txt, markup

@bot.callback_query_handler(func=lambda c: c.data.startswith("MYORD|"))
def my_orders_pagination(call):
    bot.answer_callback_query(call.id)
    page = int(call.data.split("|")[1])
    txt, markup = fetch_orders_page(call.message.chat.id, page)
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data == "ASK_REFILL")
def ask_refill(call):
    bot.answer_callback_query(call.id)
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"step": "awaiting_refill"}})
    bot.send_message(call.message.chat.id, "🔄 **Enter Order ID to request a refill:**", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PAY|"))
def pay_details(call):
    bot.answer_callback_query(call.id)
    _, amt_usd, method = call.data.split("|")
    amt_usd = float(amt_usd)
    s = get_settings()
    pay_data = next((p for p in s.get('payments', []) if p['name'] == method), None)
    address = pay_data.get('address', 'Contact Admin') if pay_data else 'Contact Admin'
    rate = pay_data.get('rate', 120) if pay_data else 120
    is_crypto = any(x in method.lower() for x in ['usdt', 'binance', 'crypto', 'btc', 'pm', 'perfect', 'payeer'])
    display_amt = f"${amt_usd:.2f}" if is_crypto else f"{round(amt_usd * float(rate), 2)} Local Currency"
    txt = f"🏦 **{method} Payment Details**\n━━━━━━━━━━━━━━━━━━━━\n💵 **Amount to Send:** `{display_amt}`\n📍 **Account / Address:** `{address}`\n━━━━━━━━━━━━━━━━━━━━\n⚠️ Send the exact amount to the address above, then reply to this message with your **TrxID / Transaction ID**:"
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"step": "awaiting_trx", "temp_dep_amt": amt_usd, "temp_dep_method": method}})
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("FAV_ADD|"))
def add_to_favorites(call):
    bot.answer_callback_query(call.id, "⭐ Added to Favorites!", show_alert=True)
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$addToSet": {"favorites": sid}})

# ==========================================
# 6. UNIVERSAL BUTTONS
# ==========================================
def universal_buttons(message):
    update_spy(message.chat.id, f"Clicked {message.text}")
    users_col.update_one({"_id": message.chat.id}, {"$unset": {"step": "", "temp_sid": "", "temp_link": ""}})
    if check_spam(message.chat.id) or check_maintenance(message.chat.id) or not check_sub(message.chat.id): return
    u = users_col.find_one({"_id": message.chat.id})
    curr = u.get("currency", "BDT") if u else "BDT"

    if message.text == "📦 Orders":
        txt, markup = fetch_orders_page(message.chat.id, 0)
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
    elif message.text == "💰 Deposit":
        users_col.update_one({"_id": message.chat.id}, {"$set": {"step": "awaiting_deposit_amt"}})
        bot.send_message(message.chat.id, f"💵 **Enter Deposit Amount ({curr}):**\n_(e.g. 100)_", parse_mode="Markdown")
    elif message.text == "🎟️ Voucher":
        users_col.update_one({"_id": message.chat.id}, {"$set": {"step": "awaiting_voucher"}})
        bot.send_message(message.chat.id, "🎁 **Enter Promo Code:**", parse_mode="Markdown")
    elif message.text == "🤝 Affiliate":
        ref_link = f"https://t.me/{bot.get_me().username}?start={message.chat.id}"
        s = get_settings()
        bot.send_message(message.chat.id, f"🤝 **AFFILIATE DASHBOARD**\n━━━━━━━━━━━━━━━━━━━━\n🔗 **Your Link:** `{ref_link}`\n💰 **Monthly Earned:** `{fmt_curr(u.get('ref_earnings', 0.0), curr)}`\n👥 **Total Joined:** `{users_col.count_documents({'ref_by': message.chat.id, 'ref_paid': True})}`\n\n_Earn ${s.get('ref_bonus', 0.0)} when they verify + {s.get('dep_commission', 0.0)}% on all deposits!_", parse_mode="Markdown", disable_web_page_preview=True)
    elif message.text == "🏆 Leaderboard":
        s = get_settings()
        r1, r2, r3 = s.get('reward_top1', 10.0), s.get('reward_top2', 5.0), s.get('reward_top3', 2.0)
        
        # 🔥 FAKE USERS NOW INCLUDED IN LEADERBOARD
        top_spenders = list(users_col.find({"spent": {"$gt": 0}}).sort("spent", -1).limit(5))
        txt = "🏆 **MONTHLY TOP SPENDERS**\n━━━━━━━━━━━━━━━━━━━━\n"
        if not top_spenders: txt += "No spenders this month yet!\n"
        else:
            for i, tu in enumerate(top_spenders):
                rt = f" 🎁 Reward: ${[r1, r2, r3][i]}" if i < 3 else ""
                txt += f"{i+1}. {tu.get('name', 'N/A')} - Spent: `{fmt_curr(tu.get('spent', 0), curr)}`{rt}\n"
                
        # 🔥 FAKE USERS NOW INCLUDED IN LEADERBOARD
        top_refs = list(users_col.find({"ref_earnings": {"$gt": 0}}).sort("ref_earnings", -1).limit(5))
        txt += "\n👥 **MONTHLY TOP AFFILIATES**\n━━━━━━━━━━━━━━━━━━━━\n"
        if not top_refs: txt += "No affiliates this month yet!\n"
        else:
            for i, tu in enumerate(top_refs):
                rt = f" 🎁 Reward: ${[r1, r2, r3][i]}" if i < 3 else ""
                txt += f"{i+1}. {tu.get('name', 'N/A')} - Earned: `{fmt_curr(tu.get('ref_earnings', 0), curr)}`{rt}\n"
        bot.send_message(message.chat.id, txt + "\n_Note: Leaderboard resets monthly! Top 3 users get wallet cash._", parse_mode="Markdown")
        
    elif message.text == "🔍 Smart Search":
        users_col.update_one({"_id": message.chat.id}, {"$set": {"step": "awaiting_search"}})
        bot.send_message(message.chat.id, "🔍 **Smart Search**\nEnter Keyword or Service ID:", parse_mode="Markdown")
    elif message.text == "🎧 Support Ticket":
        users_col.update_one({"_id": message.chat.id}, {"$set": {"step": "awaiting_ticket"}})
        bot.send_message(message.chat.id, "🎧 **Describe your issue:**", parse_mode="Markdown")
    elif message.text == "⭐ Favorites":
        favs = u.get("favorites", [])
        if not favs: return bot.send_message(message.chat.id, "📭 You have no favorites.")
        services = get_cached_services()
        markup = types.InlineKeyboardMarkup(row_width=1)
        for sid in favs:
            s = next((x for x in services if str(x['service']) == str(sid)), None)
            if s: markup.add(types.InlineKeyboardButton(f"⭐ ID:{s['service']} | {clean_service_name(s['name'])[:25]}", callback_data=f"INFO|{s['service']}"))
        bot.send_message(message.chat.id, "⭐ **Your Favorites:**", reply_markup=markup, parse_mode="Markdown")

# ==========================================
# 7. GOD MODE ADMIN COMMANDS
# ==========================================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if str(message.chat.id) != str(ADMIN_ID): return bot.reply_to(message, "❌ Access Denied. Boss only!")
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Stats", callback_data="ADM_STATS"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="ADM_BC"),
        types.InlineKeyboardButton("💰 Profit", callback_data="ADM_PROFIT"),
        types.InlineKeyboardButton("🚧 Maintenance", callback_data="ADM_MAIN")
    )
    bot.send_message(message.chat.id, f"👑 **WELCOME BOSS!**\n━━━━━━━━━━━━━━━━━━━━\nUsers: `{users_col.count_documents({})}`\nOrders: `{orders_col.count_documents({})}`\nSelect an action:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ADM_"))
def admin_callbacks(call):
    if str(call.message.chat.id) != str(ADMIN_ID): return
    uid = call.message.chat.id
    if call.data == "ADM_STATS":
        bot.answer_callback_query(call.id)
        bal = sum(u.get('balance', 0) for u in users_col.find())
        spt = sum(u.get('spent', 0) for u in users_col.find())
        bot.send_message(uid, f"📈 **FINANCIAL REPORT**\n💰 User Balances: `${bal:.2f}`\n💸 Total Revenue: `${spt:.2f}`", parse_mode="Markdown")
    elif call.data == "ADM_BC":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_bc"}})
        bot.send_message(uid, "📢 **Enter message for all users:**", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    elif call.data == "ADM_MAIN":
        s = get_settings()
        ns = not s.get('maintenance', False)
        config_col.update_one({"_id": "settings"}, {"$set": {"maintenance": ns}})
        global SETTINGS_CACHE
        if SETTINGS_CACHE["data"]: SETTINGS_CACHE["data"]["maintenance"] = ns
        bot.answer_callback_query(call.id, f"Maintenance: {'ON' if ns else 'OFF'}", show_alert=True)
    elif call.data == "ADM_PROFIT":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_profit"}})
        bot.send_message(uid, "💹 **Enter New Profit Margin (%):**", parse_mode="Markdown")
        bot.answer_callback_query(call.id)

# ==========================================
# 8. MASTER ROUTER
# ==========================================
@bot.message_handler(func=lambda m: True)
def text_router(message):
    uid = message.chat.id
    text = message.text.strip() if message.text else ""
    if text.startswith('/'): return
    update_spy(uid, f"Clicked {text}" if len(text) < 20 else "Typing...")
    
    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    if text in ["⭐ Favorites", "🏆 Leaderboard", "📦 Orders", "💰 Deposit", "🎧 Support Ticket", "🔍 Smart Search", "🤝 Affiliate", "🎟️ Voucher"]:
        return universal_buttons(message)
    
    u = users_col.find_one({"_id": uid})
    if not u: return
    step = u.get("step")
    
    if str(uid) == str(ADMIN_ID):
        if step == "awaiting_bc":
            users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
            c = 0
            for usr in users_col.find({"is_fake": {"$ne": True}}):
                try: bot.send_message(usr["_id"], f"📢 **MESSAGE FROM ADMIN**\n━━━━━━━━━━━━━━━━━━━━\n{text}", parse_mode="Markdown"); c+=1
                except: pass
            return bot.send_message(uid, f"✅ Broadcast sent to `{c}` users!")
        elif step == "awaiting_profit":
            try:
                v = float(text)
                config_col.update_one({"_id": "settings"}, {"$set": {"profit_margin": v}})
                global SETTINGS_CACHE
                if SETTINGS_CACHE["data"]: SETTINGS_CACHE["data"]["profit_margin"] = v
                users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
                return bot.send_message(uid, f"✅ **Profit Margin set to {v}%**")
            except: return bot.send_message(uid, "❌ Enter a valid number!")

    if not step:
        return bot.send_message(uid, "❌ **Unknown Command.** Please select from menu:", reply_markup=main_menu(), parse_mode="Markdown")
    
    if step == "awaiting_link":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_qty", "temp_link": text}})
        return bot.send_message(uid, "🔢 **Enter Quantity (Numbers only):**", parse_mode="Markdown")
        
    elif step == "awaiting_qty":
        try: qty = int(text)
        except ValueError: return bot.send_message(uid, "⚠️ **Numbers only! Enter valid quantity:**", parse_mode="Markdown")
            
        sid = u.get("temp_sid")
        link = u.get("temp_link")
        users_col.update_one({"_id": uid}, {"$unset": {"step": "", "temp_sid": "", "temp_link": ""}})
        
        if not sid or not link: return bot.send_message(uid, "❌ Session expired. Please order again.")
            
        services = get_cached_services()
        s = next((x for x in services if str(x['service']) == str(sid)), None)
        if not s: return bot.send_message(uid, "❌ Service not found.")
            
        try: s_min, s_max = int(s.get('min', 0)), int(s.get('max', 99999999))
        except: s_min, s_max = 0, 99999999
            
        if qty < s_min or qty > s_max: return bot.send_message(uid, f"❌ Invalid Quantity! Allowed: {s_min} - {s_max}")

        curr = u.get("currency", "BDT")
        rate_usd = calculate_price(s['rate'], u.get('spent', 0), u.get('custom_discount', 0))
        cost_usd = (rate_usd / 1000) * qty
        
        if u.get('balance', 0) < cost_usd: return bot.send_message(uid, f"❌ **Insufficient Balance!** Need `{fmt_curr(cost_usd, curr)}`.", parse_mode="Markdown")

        users_col.update_one({"_id": uid}, {"$set": {"draft": {"sid": sid, "link": link, "qty": qty, "cost": cost_usd}}})
        txt = f"⚠️ **ORDER PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Service ID: `{sid}`\n🔗 Link: {link}\n🔢 Quantity: {qty}\n💰 Order Cost: `{fmt_curr(cost_usd, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm your order?"
        markup = types.InlineKeyboardMarkup(row_width=2).add(types.InlineKeyboardButton("✅ CONFIRM", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
        return bot.send_message(uid, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

    elif step == "awaiting_deposit_amt":
        try:
            amt = float(text)
            curr_code = u.get("currency", "BDT")
            amt_usd = amt / CURRENCY_RATES.get(curr_code, 1)
            payments = get_settings().get("payments", [])
            markup = types.InlineKeyboardMarkup(row_width=1)
            for p in payments: 
                is_crypto = any(x in p['name'].lower() for x in ['usdt', 'binance', 'crypto', 'btc', 'pm'])
                display_amt = f"${amt_usd:.2f}" if is_crypto else f"{round(amt_usd * float(p['rate']), 2)} {curr_code}"
                markup.add(types.InlineKeyboardButton(f"🏦 {p['name']} (Pay {display_amt})", callback_data=f"PAY|{amt_usd}|{p['name']}"))
            users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
            return bot.send_message(uid, "💳 **Select Gateway:**", reply_markup=markup, parse_mode="Markdown")
        except ValueError: return bot.send_message(uid, "⚠️ Invalid amount. Numbers only.")

    elif step == "awaiting_trx":
        tid = text
        amt = u.get("temp_dep_amt", 0.0)
        method_name = u.get("temp_dep_method", "Unknown")
        users_col.update_one({"_id": uid}, {"$unset": {"step": "", "temp_dep_amt": "", "temp_dep_method": ""}})
        
        bot.send_message(uid, "✅ **Request Submitted!**\nAdmin will verify your TrxID shortly.", parse_mode="Markdown")
        admin_txt = f"🔔 **NEW DEPOSIT**\n👤 User: `{uid}`\n🏦 Method: **{method_name}**\n💰 Amt: **${round(float(amt), 2)}**\n🧾 TrxID: `{tid}`"
        markup = types.InlineKeyboardMarkup(row_width=2)
        app_url = BASE_URL.rstrip('/')
        markup.add(types.InlineKeyboardButton("✅ APPROVE", url=f"{app_url}/approve_dep/{uid}/{amt}/{tid}"), types.InlineKeyboardButton("❌ REJECT", url=f"{app_url}/reject_dep/{uid}/{tid}"))
        try: bot.send_message(ADMIN_ID, admin_txt, reply_markup=markup, parse_mode="Markdown")
        except: pass

    elif step == "awaiting_refill":
        users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
        bot.send_message(uid, "✅ Refill Requested! Admin will check it.")
        return bot.send_message(ADMIN_ID, f"🔄 **REFILL REQUEST:**\nOrder ID: `{text}`\nBy User: `{uid}`")
        
    elif step == "awaiting_ticket":
        users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
        tickets_col.insert_one({"uid": uid, "msg": text, "status": "open", "date": datetime.now()})
        return bot.send_message(uid, "✅ **Ticket Sent Successfully!** Admin will reply soon.", parse_mode="Markdown")
        
    elif step == "awaiting_voucher":
        users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
        code = text.upper()
        voucher = vouchers_col.find_one({"code": code})
        if not voucher: return bot.send_message(uid, "❌ Invalid Voucher Code.")
        if len(voucher.get('used_by', [])) >= voucher['limit']: return bot.send_message(uid, "❌ Voucher Limit Reached!")
        if uid in voucher.get('used_by', []): return bot.send_message(uid, "❌ You have already claimed this voucher.")
        vouchers_col.update_one({"code": code}, {"$push": {"used_by": uid}})
        users_col.update_one({"_id": uid}, {"$inc": {"balance": voucher['amount']}})
        curr = u.get("currency", "BDT")
        return bot.send_message(uid, f"✅ **VOUCHER CLAIMED**\nReward: `{fmt_curr(voucher['amount'], curr)}` added to your wallet.", parse_mode="Markdown")
        
    elif step == "awaiting_search":
        users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
        query = text.lower()
        services = get_cached_services()
        hidden = get_settings().get("hidden_services", [])
        
        if query.isdigit():
            s = next((x for x in services if str(x['service']) == query and query not in hidden), None)
            if s: 
                markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("ℹ️ Order Now", callback_data=f"INFO|{query}"))
                return bot.send_message(uid, f"✅ **Found:** {clean_service_name(s['name'])}", reply_markup=markup, parse_mode="Markdown")
                
        results = [s for s in services if str(s['service']) not in hidden and (query in s['name'].lower() or query in s['category'].lower())][:10]
        if not results: return bot.send_message(uid, "❌ No related services found.")
        markup = types.InlineKeyboardMarkup(row_width=1)
        for s in results: markup.add(types.InlineKeyboardButton(f"⚡ ID:{s['service']} | {clean_service_name(s['name'])[:25]}", callback_data=f"INFO|{s['service']}"))
        return bot.send_message(uid, f"🔍 **Top Results:**", reply_markup=markup, parse_mode="Markdown")
