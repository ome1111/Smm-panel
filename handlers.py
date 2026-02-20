from telebot import types
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col
from config import *
import api
import math
import time
import os
from datetime import datetime
import google.generativeai as genai

# ==========================================
# ১. CORE SETTINGS, AI & SPY MODE
# ==========================================
# Gemini AI Setup
GEMINI_API_KEY = "AIzaSyBPqzynaZaa9UQmPm9EvhdrI6TcM-5FqcQ"
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

API_CACHE = {'data': [], 'last_fetch': 0}
CACHE_TTL = 300 
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')

# Anti-Spam Tracking
user_actions = {}
blocked_users = {}

# Live Spy Mode Updater
def update_spy(uid, action_text):
    try:
        users_col.update_one(
            {"_id": uid}, 
            {"$set": {"last_action": action_text, "last_active": datetime.now()}}
        )
    except: pass

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
        try: bot.send_message(uid, "🛡 **ANTI-SPAM TRIGGERED!**\nYou clicked too fast. You are temporarily blocked for 5 minutes.", parse_mode="Markdown")
        except: pass
        return True
    return False

def get_settings():
    s = config_col.find_one({"_id": "settings"})
    if not s:
        s = {"_id": "settings", "channels": [], "profit_margin": 20.0, "maintenance": False, "payments": [], "ref_target": 10, "ref_bonus": 5.0, "dep_commission": 5.0, "hidden_services": [], "fake_orders": 50000, "fake_users": 12000, "cat_ranking": [], "fake_post_channel": ""}
        config_col.insert_one(s)
    return s

def check_maintenance(chat_id):
    settings = get_settings()
    if settings.get('maintenance', False) and str(chat_id) != str(ADMIN_ID):
        bot.send_message(chat_id, "🛠 **SYSTEM UPDATE**\n━━━━━━━━━━━━━━━━━━━━\nThe bot is undergoing a massive upgrade. Please try again later.", parse_mode="Markdown")
        return True
    return False

def get_cached_services():
    global API_CACHE
    if time.time() - API_CACHE['last_fetch'] < CACHE_TTL and API_CACHE['data']: 
        return API_CACHE['data']
    res = api.get_services()
    if res and type(res) == list:
        API_CACHE['data'] = res
        API_CACHE['last_fetch'] = time.time()
    return API_CACHE['data']

# ==========================================
# ২. UTILITIES & TITAN FEATURES
# ==========================================
def get_user_tier(spent):
    if spent >= 50: return "🥇 Gold VIP", 5 
    elif spent >= 10: return "🥈 Silver VIP", 2 
    else: return "🥉 Bronze", 0

def validate_link(platform, link):
    p, l = platform.lower(), link.lower()
    if 'youtube' in p and 'youtu' not in l: return False
    if 'facebook' in p and ('facebook' not in l and 'fb.' not in l): return False
    if 'instagram' in p and 'instagram' not in l: return False
    if 'tiktok' in p and 'tiktok' not in l: return False
    if 'twitter' in p and ('twitter' not in l and 'x.com' not in l): return False
    return True

def identify_platform(cat_name):
    cat = cat_name.lower()
    if 'instagram' in cat or 'ig' in cat: return "📸 Instagram"
    if 'facebook' in cat or 'fb' in cat: return "📘 Facebook"
    if 'youtube' in cat or 'yt' in cat: return "▶️ YouTube"
    if 'tiktok' in cat or 'tt' in cat: return "🎵 TikTok"
    if 'telegram' in cat or 'tg' in cat: return "✈️ Telegram"
    if 'twitter' in cat or ' x ' in cat: return "🐦 Twitter"
    if 'spotify' in cat: return "🎧 Spotify"
    if 'website' in cat or 'traffic' in cat: return "🌍 Web Traffic"
    return "🌐 Other Services"

# ==========================================
# ৩. UI MENUS & FORCE SUB
# ==========================================
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

def send_force_sub(chat_id):
    channels = get_settings().get("channels", [])
    markup = types.InlineKeyboardMarkup(row_width=1)
    for ch in channels: markup.add(types.InlineKeyboardButton(f"📢 Join {ch}", url=f"https://t.me/{ch.replace('@','')}"))
    markup.add(types.InlineKeyboardButton("🟢 VERIFY ACCOUNT 🟢", callback_data="CHECK_SUB"))
    txt = "🛑 **ACCESS RESTRICTED**\n━━━━━━━━━━━━━━━━━━━━\nJoin our official channels to unlock premium features."
    bot.send_message(chat_id, txt, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CHECK_SUB")
def sub_check_callback(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    if check_sub(call.message.chat.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        u = users_col.find_one({"_id": call.message.chat.id})
        
        if u and u.get('ref_by') and not u.get('ref_paid', True):
            users_col.update_one({"_id": call.message.chat.id}, {"$set": {"ref_paid": True}})
            referrer = u['ref_by']
            users_col.update_one({"_id": referrer}, {"$inc": {"balance": REF_BONUS}})
            try: bot.send_message(referrer, f"🎊 **New Referral Verified!** You earned **${REF_BONUS}**!")
            except: pass
            
            settings = get_settings()
            ref_count = users_col.count_documents({"ref_by": referrer, "ref_paid": True})
            if ref_count > 0 and ref_count % settings.get("ref_target", 10) == 0:
                bonus = settings.get("ref_bonus", 5.0)
                users_col.update_one({"_id": referrer}, {"$inc": {"balance": bonus}})
                try: bot.send_message(referrer, f"🏆 **MILESTONE REACHED!**\nYou got an extra **${bonus}** bonus for active referrals!")
                except: pass

        bot.send_message(call.message.chat.id, "✅ **Access Granted!**", reply_markup=main_menu())
    else: 
        bot.answer_callback_query(call.id, "❌ Join ALL channels first!", show_alert=True)

# ==========================================
# ৪. START COMMAND & GLOBAL STATS
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    update_spy(message.chat.id, "Clicked /start")
    if check_spam(message.chat.id) or check_maintenance(message.chat.id): return
    uid = message.chat.id
    name = message.from_user.first_name
    args = message.text.split()
    referrer = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid else None

    if not users_col.find_one({"_id": uid}):
        users_col.insert_one({"_id": uid, "name": name, "balance": 0.0, "spent": 0.0, "ref_by": referrer, "ref_paid": False, "ref_earnings": 0.0, "joined": datetime.now(), "favorites": [], "last_active": datetime.now(), "last_action": "Registered"})

    if not check_sub(uid): return send_force_sub(uid)

    settings = get_settings()
    fake_users = settings.get('fake_users', 12000)
    fake_orders = settings.get('fake_orders', 50000)

    txt = f"👋 **WELCOME TO NEXUS SMM**\n━━━━━━━━━━━━━━━━━━━━\n💠 **Best Social Media Services**\n🚀 **Super Fast Delivery**\n━━━━━━━━━━━━━━━━━━━━\n📊 **Global Stats:**\n👥 Active Users: {fake_users}+\n📦 Orders Processed: {fake_orders}+\n━━━━━━━━━━━━━━━━━━━━\n🆔 **Your ID:** `{uid}`"
    bot.send_message(uid, txt, reply_markup=main_menu(), parse_mode="Markdown")

# ==========================================
# ৫. ORDERING SYSTEM & CUSTOM EMOJIS
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def show_platforms(message):
    update_spy(message.chat.id, "Browsing Platforms")
    if check_spam(message.chat.id) or check_maintenance(message.chat.id): return
    if not check_sub(message.chat.id): return send_force_sub(message.chat.id)
    
    load_msg = bot.send_message(message.chat.id, "📡 **Connecting to NEXUS Core...**\n`[■□□□□□□□□□] 10%`", parse_mode="Markdown")
    time.sleep(0.3)
    bot.edit_message_text("🔐 **Fetching API Services...**\n`[■■■■■□□□□□] 50%`", message.chat.id, load_msg.message_id, parse_mode="Markdown")
    time.sleep(0.3)
    bot.edit_message_text("🚀 **System Ready!**\n`[■■■■■■■■■□] 90%`", message.chat.id, load_msg.message_id, parse_mode="Markdown")
    time.sleep(0.2)

    services = get_cached_services()
    if not services: 
        return bot.edit_message_text("❌ **API Maintenance. Try later.**", message.chat.id, load_msg.message_id, parse_mode="Markdown")

    hidden = get_settings().get("hidden_services", [])
    platforms = set(identify_platform(s['category']) for s in services if str(s['service']) not in hidden)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btns = [types.InlineKeyboardButton(text=p, callback_data=f"PLAT|{p}|0") for p in sorted(platforms)]
    for i in range(0, len(btns), 2):
        if i+1 < len(btns): markup.row(btns[i], btns[i+1])
        else: markup.row(btns[i])
        
    bot.edit_message_text("🟢 **Live API Status:** Active\n━━━━━━━━━━━━━━━━━━━━\n📂 **Select a Platform:**", message.chat.id, load_msg.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PLAT|"))
def show_categories(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    data = call.data.split("|")
    platform_name, page = data[1], int(data[2]) if len(data) > 2 else 0
    update_spy(call.message.chat.id, f"Viewing: {platform_name}")
    hidden = get_settings().get("hidden_services", [])
    
    all_cats = sorted(list(set(s['category'] for s in get_cached_services() if str(s['service']) not in hidden)))
    plat_cats = [c for c in all_cats if identify_platform(c) == platform_name]
    
    # Smart Ranking
    plat_cats.sort(key=lambda x: (0 if 'Telegram' in x else 1 if 'Instagram' in x else 2 if 'YouTube' in x else 3, x))
    
    start, end = page * 15, page * 15 + 15
    markup = types.InlineKeyboardMarkup(row_width=1)
    for cat in plat_cats[start:end]:
        idx = all_cats.index(cat)
        short_cat = cat.replace("Instagram", "").replace("Facebook", "").replace("YouTube", "").replace("Telegram", "").strip()
        if len(short_cat) < 3: short_cat = cat
        markup.add(types.InlineKeyboardButton(f"📁 {short_cat[:35]}", callback_data=f"CAT|{idx}|0"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"PLAT|{platform_name}|{page-1}"))
    if end < len(plat_cats): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"PLAT|{platform_name}|{page+1}"))
    if nav: markup.row(*nav)
    markup.add(types.InlineKeyboardButton("🔙 Back to Platforms", callback_data="BACK_TO_PLAT"))
    bot.edit_message_text(f"📍 **{platform_name}**\nPage: {page+1}/{math.ceil(len(plat_cats)/15)}\n━━━━━━━━━━━━━━━━━━━━\n📂 **Select Category:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "BACK_TO_PLAT")
def back_to_plat(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    message = call.message
    message.text = "🚀 New Order"
    show_platforms(message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("CAT|"))
def list_services(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    data = call.data.split("|")
    cat_idx, page = int(data[1]), int(data[2])
    settings, services = get_settings(), get_cached_services()
    hidden = settings.get("hidden_services", [])
    
    all_cats = sorted(list(set(s['category'] for s in services if str(s['service']) not in hidden)))
    if cat_idx >= len(all_cats): return
    cat_name = all_cats[cat_idx]
    
    filtered = [s for s in services if s['category'] == cat_name and str(s['service']) not in hidden]
    start, end = page * 10, page * 10 + 10
    
    user = users_col.find_one({"_id": call.message.chat.id})
    _, discount = get_user_tier(user.get('spent', 0))
    global_profit = settings.get("profit_margin", 20.0)
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in filtered[start:end]:
        base_rate = float(s['rate']) + (float(s['rate']) * global_profit / 100)
        final_rate = round(base_rate - (base_rate * discount / 100), 3)
        
        # Custom Service Emojis Based on Speed/Name
        speed_emoji = "⚡"
        if "instant" in s['name'].lower() or "fast" in s['name'].lower(): speed_emoji = "🚀"
        elif "slow" in s['name'].lower(): speed_emoji = "🐢"
        elif "drip" in s['name'].lower(): speed_emoji = "💧"

        markup.add(types.InlineKeyboardButton(f"{speed_emoji} ID:{s['service']} | ${final_rate} | {s['name'][:18]}", callback_data=f"INFO|{s['service']}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CAT|{cat_idx}|{page-1}"))
    if end < len(filtered): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CAT|{cat_idx}|{page+1}"))
    if nav: markup.row(*nav)
    
    platform_name = identify_platform(cat_name)
    markup.add(types.InlineKeyboardButton(f"🔙 Back to {platform_name}", callback_data=f"PLAT|{platform_name}|0"))
    bot.edit_message_text(f"📍 **{platform_name}**\n📦 **{cat_name[:30]}...**\nPage: {page+1}/{math.ceil(len(filtered)/10)}", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|"))
def show_service_info(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    sid = call.data.split("|")[1]
    update_spy(call.message.chat.id, f"Checking ID: {sid}")
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    
    if not s: return bot.answer_callback_query(call.id, "❌ Service not found!", show_alert=True)
        
    user = users_col.find_one({"_id": call.message.chat.id})
    tier_name, discount = get_user_tier(user.get('spent', 0))
    global_profit = get_settings().get("profit_margin", 20.0)
    
    base_rate = float(s['rate']) + (float(s['rate']) * global_profit / 100)
    final_rate = round(base_rate - (base_rate * discount / 100), 3)
    avg_speed = "1-6 Hours" if "hours" not in str(s.get('type','')).lower() else "Instant/Fast"
    
    txt = f"ℹ️ **SERVICE INFORMATION**\n━━━━━━━━━━━━━━━━━━━━\n🏷 **Name:** {s['name']}\n🆔 **ID:** `{sid}`\n💰 **Your Price:** `${final_rate}` / 1000\n⚡ **Avg Speed:** {avg_speed}\n✨ **VIP Status:** {tier_name} ({discount}% OFF)\n📉 **Min:** {s['min']} | 📈 **Max:** {s['max']}\n━━━━━━━━━━━━━━━━━━━━\n⚠️ *Make sure link is public!*"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🛒 Order Now", callback_data=f"START_ORD|{sid}"), types.InlineKeyboardButton("⭐ Fav", callback_data=f"FAV_ADD|{sid}"))
    all_cats = sorted(list(set(x['category'] for x in services if str(x['service']) not in get_settings().get("hidden_services", []))))
    try: cat_idx = all_cats.index(s['category'])
    except: cat_idx = 0
    markup.add(types.InlineKeyboardButton("🔙 Back to Services", callback_data=f"CAT|{cat_idx}|0"))
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("START_ORD|"))
def ask_link(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    sid = call.data.split("|")[1]
    msg = bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, ask_qty, sid)

def ask_qty(message, sid):
    link = message.text.strip()
    msg = bot.send_message(message.chat.id, "🔢 **Enter Quantity (Numbers only):**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, order_preview, sid, link)

def order_preview(message, sid, link):
    try:
        qty = int(message.text)
        s = next((x for x in get_cached_services() if str(x['service']) == str(sid)), None)
        if not s or qty < int(s['min']) or qty > int(s['max']):
            return bot.send_message(message.chat.id, f"❌ Invalid Quantity! Min: {s['min']}, Max: {s['max']}")

        user = users_col.find_one({"_id": message.chat.id})
        _, discount = get_user_tier(user.get('spent', 0))
        global_profit = get_settings().get("profit_margin", 20.0)
        
        base_rate = float(s['rate']) + (float(s['rate']) * global_profit / 100)
        final_rate = base_rate - (base_rate * discount / 100)
        cost = round((final_rate / 1000) * qty, 3)
        
        if user['balance'] < cost: return bot.send_message(message.chat.id, f"❌ **Insufficient Balance!**\nNeed `${cost}`, but you have `${round(user['balance'],3)}`.")

        users_col.update_one({"_id": message.chat.id}, {"$set": {"draft": {"sid": sid, "link": link, "qty": qty, "cost": cost}}})
        txt = f"⚠️ **ORDER PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **ID:** `{sid}`\n🔗 **Link:** {link}\n🔢 **Qty:** {qty}\n💰 **Cost:** `${cost}`\n━━━━━━━━━━━━━━━━━━━━\nProceed?"
        markup = types.InlineKeyboardMarkup(row_width=2).add(types.InlineKeyboardButton("✅ CONFIRM", callback_data="CONFIRM_ORDER"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORDER"))
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
    except ValueError: bot.send_message(message.chat.id, "⚠️ **Numbers only!**")

@bot.callback_query_handler(func=lambda c: c.data == "CONFIRM_ORDER")
def place_final_order(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    user = users_col.find_one({"_id": call.message.chat.id})
    draft = user.get('draft')
    if not draft: return bot.answer_callback_query(call.id, "❌ Session expired!", show_alert=True)
        
    update_spy(call.message.chat.id, f"Purchased ID {draft['sid']}")
    
    # Simulated Delays for High-Value Orders
    if draft['cost'] > 5.0:
        bot.edit_message_text("⏳ **Verifying large transaction...**\n`[■■□□□□□□□□] 20%`", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        time.sleep(1.5)
        bot.edit_message_text("🔐 **Securing connection...**\n`[■■■■■■□□□□] 60%`", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        time.sleep(1.5)
    else:
        bot.edit_message_text("📡 **Connecting to NEXUS Core...**\n`[■□□□□□□□□□] 10%`", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        time.sleep(0.3)
        bot.edit_message_text("🔐 **Encrypting Order Data...**\n`[■■■■■□□□□□] 50%`", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        time.sleep(0.3)

    bot.edit_message_text("🚀 **Sending to Main Server...**\n`[■■■■■■■■■□] 90%`", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    time.sleep(0.2)

    res = api.place_order(draft['sid'], draft['link'], draft['qty'])
    
    if 'order' in res:
        users_col.update_one({"_id": call.message.chat.id}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost']}, "$unset": {"draft": ""}})
        orders_col.insert_one({"oid": res['order'], "uid": call.message.chat.id, "sid": draft['sid'], "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], "status": "pending", "retries": 0, "date": datetime.now()})
        
        success_txt = f"> ✅ **ORDER SUCCESSFUL!**\n> ━━━━━━━━━━━━━━━━━━━━\n> 🆔 **Order ID:** `{res['order']}`\n> 💰 **Deducted:** `${draft['cost']}`\n> 📌 _Track in '📦 Orders' menu._"
        bot.edit_message_text(success_txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        
        # Real Order Auto Post to Channel
        ch = get_settings().get("fake_post_channel")
        if ch:
            try: bot.send_message(ch, f"🟢 **REAL ORDER PLACED!**\n━━━━━━━━━━━━━━━━━━━━\n👤 **User ID:** `***{str(call.message.chat.id)[-4:]}`\n📦 **Quantity:** {draft['qty']}\n💰 **Amount:** `${draft['cost']}`\n⚡ **Status:** Processing\n━━━━━━━━━━━━━━━━━━━━\n🚀 _Join NEXUS SMM Today!_", parse_mode="Markdown")
            except: pass
            
        try: bot.send_message(ADMIN_ID, f"🔔 **NEW ORDER!**\nUser: `{call.message.chat.id}`\nService ID: `{draft['sid']}`\nCost: `${draft['cost']}`")
        except: pass
    else: 
        bot.edit_message_text(f"❌ **Failed:** {res.get('error')}", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORDER")
def cancel_order(call):
    users_col.update_one({"_id": call.message.chat.id}, {"$unset": {"draft": ""}})
    bot.edit_message_text("🚫 **Order Cancelled.**", call.message.chat.id, call.message.message_id)

# ==========================================
# ৬. DEPOSIT FLOW
# ==========================================
def deposit_ask_amount(message):
    try:
        amount = float(message.text)
        if amount <= 0: return bot.send_message(message.chat.id, "❌ Amount must be greater than 0.")
        
        payments = get_settings().get("payments", [])
        if not payments: return bot.send_message(message.chat.id, "❌ No payment methods available right now.")
        
        txt = f"💰 **DEPOSIT REQUEST: ${amount}**\n━━━━━━━━━━━━━━━━━━━━\nSelect a Payment Gateway below:"
        markup = types.InlineKeyboardMarkup(row_width=1)
        for p in payments:
            bdt_amount = round(amount * float(p['rate']), 2)
            markup.add(types.InlineKeyboardButton(f"🏦 {p['name']} (Pay {bdt_amount} BDT)", callback_data=f"PAY|{amount}|{p['name']}"))
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Invalid amount. Use numbers only.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PAY|"))
def deposit_show_details(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    _, amt, method_name = call.data.split("|")
    amt = float(amt)
    payments = get_settings().get("payments", [])
    method = next((x for x in payments if x['name'] == method_name), None)
    
    if not method: return bot.answer_callback_query(call.id, "❌ Method unavailable!", show_alert=True)
    
    bdt_amount = round(amt * float(method['rate']), 2)
    txt = f"🏦 **{method_name} DEPOSIT**\n━━━━━━━━━━━━━━━━━━━━\n💵 **Amount to Pay:** `{bdt_amount} BDT`\n👉 **Send to:** `{method['details']}`\n━━━━━━━━━━━━━━━━━━━━\nAfter sending the money, reply to this message with your **TrxID** or **Screenshot Link**."
    
    msg = bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_deposit_trx, amt, method_name)

def process_deposit_trx(message, amt, method_name):
    tid = message.text.strip()
    bot.send_message(message.chat.id, "✅ **Request Submitted!**\nAdmin will verify your TrxID and approve the deposit shortly.", parse_mode="Markdown")
    
    admin_txt = f"🔔 **NEW DEPOSIT REQUEST**\n━━━━━━━━━━━━━━━━━━━━\n👤 User: `{message.chat.id}`\n🏦 Method: **{method_name}**\n💰 Amount: **${amt}**\n🧾 TrxID: `{tid}`\n━━━━━━━━━━━━━━━━━━━━"
    markup = types.InlineKeyboardMarkup(row_width=2)
    app_url = BASE_URL.rstrip('/')
    markup.add(types.InlineKeyboardButton("✅ APPROVE", url=f"{app_url}/approve_dep/{message.chat.id}/{amt}/{tid}"), types.InlineKeyboardButton("❌ REJECT", url=f"{app_url}/reject_dep/{message.chat.id}/{tid}"))
    try: bot.send_message(ADMIN_ID, admin_txt, reply_markup=markup, parse_mode="Markdown")
    except: pass

# ==========================================
# ৭. VOUCHER SYSTEM
# ==========================================
def process_voucher(message):
    code = message.text.strip().upper()
    voucher = vouchers_col.find_one({"code": code})
    
    if not voucher: return bot.send_message(message.chat.id, "❌ Invalid Voucher Code.")
    if len(voucher.get('used_by', [])) >= voucher['limit']: return bot.send_message(message.chat.id, "❌ Voucher Limit Reached!")
    if message.chat.id in voucher.get('used_by', []): return bot.send_message(message.chat.id, "❌ You have already claimed this voucher.")
    
    vouchers_col.update_one({"code": code}, {"$push": {"used_by": message.chat.id}})
    users_col.update_one({"_id": message.chat.id}, {"$inc": {"balance": voucher['amount']}})
    
    msg = f"> 🧾 **NEXUS VOUCHER RECEIPT**\n> ━━━━━━━━━━━━━━━━━━━━\n> ✅ **Status:** CLAIMED\n> 🎁 **Code:** `{code}`\n> 💰 **Reward Added:** `${voucher['amount']}`\n> \n> _Enjoy your free funds!_"
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

# ==========================================
# ৮. UNIVERSAL BUTTONS, CURRENCY & VIP CARD
# ==========================================
def fetch_orders_page(chat_id, page=0):
    all_orders = list(orders_col.find({"uid": chat_id}).sort("_id", -1))
    if not all_orders: return "📭 No orders found.", None
    
    start, end = page * 5, page * 5 + 5
    page_orders = all_orders[start:end]
    txt = f"📦 **YOUR ORDERS (Page {page+1}/{math.ceil(len(all_orders)/5)})**\n━━━━━━━━━━━━━━━━━━━━\n"
    
    for o in page_orders:
        current_status = str(o.get('status', 'pending')).lower()
        if current_status in ['pending', 'processing', 'in progress']:
            try:
                res = api.get_order_status(o['oid'])
                if res and 'status' in res:
                    current_status = str(res['status']).lower()
                    orders_col.update_one({"oid": o['oid']}, {"$set": {"status": current_status}})
            except: pass
            
        status_text = f"✅ {current_status.upper()}" if current_status == 'completed' else f"❌ {current_status.upper()}" if current_status in ['canceled', 'refunded', 'error', 'fail'] else f"⏳ {current_status.upper()}"
        txt += f"🆔 `{o['oid']}` | 💰 `${round(o['cost'],3)}`\n🔗 {str(o.get('link', 'N/A'))[:25]}...\n🏷 Status: {status_text}\n\n"
        
    markup = types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"MYORD|{page-1}"))
    if end < len(all_orders): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"MYORD|{page+1}"))
    if nav: markup.row(*nav)
    markup.add(types.InlineKeyboardButton("🔄 Request Refill", callback_data="ASK_REFILL"))
    return txt, markup

@bot.callback_query_handler(func=lambda c: c.data.startswith("MYORD|"))
def my_orders_pagination(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    page = int(call.data.split("|")[1])
    bot.answer_callback_query(call.id, "⏳ Syncing Live Status...")
    txt, markup = fetch_orders_page(call.message.chat.id, page)
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("CURR|"))
def convert_currency(call):
    curr = call.data.split("|")[1]
    u = users_col.find_one({"_id": call.message.chat.id})
    bal = float(u.get('balance', 0))
    if curr == "BDT": 
        bot.answer_callback_query(call.id, f"৳ Your Wallet: {round(bal * 120, 2)} BDT", show_alert=True)
    elif curr == "INR": 
        bot.answer_callback_query(call.id, f"₹ Your Wallet: {round(bal * 83, 2)} INR", show_alert=True)

@bot.message_handler(func=lambda m: m.text in ["⭐ Favorites", "👤 Profile", "🏆 Leaderboard", "📦 Orders", "💰 Deposit", "🎧 Support Ticket", "🔍 Smart Search", "🤝 Affiliate", "🎟️ Voucher"])
def universal_buttons(message):
    update_spy(message.chat.id, f"Clicked {message.text}")
    if check_spam(message.chat.id) or check_maintenance(message.chat.id): return
    if not check_sub(message.chat.id): return send_force_sub(message.chat.id)
    
    if message.text == "👤 Profile":
        u = users_col.find_one({"_id": message.chat.id})
        tier, _ = get_user_tier(u.get('spent', 0))
        name_str = (message.from_user.first_name or "User")[:12]
        uid_str = str(u['_id'])
        bal_str = f"${round(u.get('balance',0), 3)}"
        spent_str = f"${round(u.get('spent',0), 3)}"
        
        card = (
            f"```text\n"
            f"╔════════════════════════════════╗\n"
            f"║  🌟 NEXUS TITAN VIP CARD       ║\n"
            f"╠════════════════════════════════╣\n"
            f"║  👤 Name: {name_str.ljust(19)}║\n"
            f"║  🆔 UID: {uid_str.ljust(20)}║\n"
            f"║  💳 Balance: {bal_str.ljust(16)}║\n"
            f"║  💸 Spent: {spent_str.ljust(18)}║\n"
            f"║  👑 Tier: {tier.ljust(19)}║\n"
            f"╚════════════════════════════════╝\n"
            f"```"
        )
        # Local Currency Option
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("🇧🇩 Show in BDT", callback_data="CURR|BDT"), types.InlineKeyboardButton("🇮🇳 Show in INR", callback_data="CURR|INR"))
        bot.send_message(message.chat.id, card, reply_markup=markup, parse_mode="Markdown")
        
    elif message.text == "📦 Orders":
        bot.send_chat_action(message.chat.id, 'typing')
        txt, markup = fetch_orders_page(message.chat.id, 0)
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        
    elif message.text == "💰 Deposit":
        msg = bot.send_message(message.chat.id, "💵 **Enter Deposit Amount (USD):**\n(e.g., 5, 10, 50)", parse_mode="Markdown")
        bot.register_next_step_handler(msg, deposit_ask_amount)
        
    elif message.text == "🎟️ Voucher":
        msg = bot.send_message(message.chat.id, "🎁 **Enter your Promo Voucher Code:**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_voucher)
        
    elif message.text == "🤝 Affiliate":
        u = users_col.find_one({"_id": message.chat.id})
        ref_link = f"https://t.me/{bot.get_me().username}?start={message.chat.id}"
        total_joined = users_col.count_documents({"ref_by": message.chat.id})
        earnings = round(u.get('ref_earnings', 0.0), 3)
        txt = f"🤝 **AFFILIATE DASHBOARD**\n━━━━━━━━━━━━━━━━━━━━\n🔗 **Your Link:**\n`{ref_link}`\n\n👥 **Total Invites:** {total_joined}\n💰 **Earned:** `${earnings}`\n━━━━━━━━━━━━━━━━━━━━\n🎁 Get Bonus & Commission!"
        bot.send_message(message.chat.id, txt, parse_mode="Markdown", disable_web_page_preview=True)
        
    elif message.text == "🏆 Leaderboard":
        top = users_col.find().sort("spent", -1).limit(5)
        txt = "🏆 **TOP 5 SPENDERS**\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, u in enumerate(top): txt += f"{i+1}. {u['name']} - `${round(u.get('spent',0), 2)}`\n"
        bot.send_message(message.chat.id, txt, parse_mode="Markdown")
        
    elif message.text == "🔍 Smart Search":
        msg = bot.send_message(message.chat.id, "🔍 **Smart Search**\nEnter Service ID or Keyword:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_smart_search)
        
    elif message.text == "🎧 Support Ticket":
        msg = bot.send_message(message.chat.id, "🎧 **Describe your issue clearly:**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m: [tickets_col.insert_one({"uid": m.chat.id, "msg": m.text, "status": "open", "date": datetime.now()}), bot.send_message(m.chat.id, "✅ Ticket Submitted!", parse_mode="Markdown")])
        
    elif message.text == "⭐ Favorites":
        user = users_col.find_one({"_id": message.chat.id})
        favs = user.get("favorites", [])
        if not favs: return bot.send_message(message.chat.id, "📭 You have no favorite services.")
        services = get_cached_services()
        _, discount = get_user_tier(user.get('spent', 0))
        markup = types.InlineKeyboardMarkup(row_width=1)
        for sid in favs:
            s = next((x for x in services if str(x['service']) == str(sid)), None)
            if s: markup.add(types.InlineKeyboardButton(f"⭐ ID:{s['service']} | {s['name'][:25]}", callback_data=f"INFO|{s['service']}"))
        bot.send_message(message.chat.id, "⭐ **Your Favorites:**", reply_markup=markup, parse_mode="Markdown")

def process_smart_search(message):
    query = message.text.strip().lower()
    services, hidden = get_cached_services(), get_settings().get("hidden_services", [])
    if query.isdigit():
        s = next((x for x in services if str(x['service']) == query and query not in hidden), None)
        if s: return bot.send_message(message.chat.id, f"✅ **Found:** {s['name']}", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("ℹ️ Order Now", callback_data=f"INFO|{query}")), parse_mode="Markdown")
    results = [s for s in services if str(s['service']) not in hidden and (query in s['name'].lower() or query in s['category'].lower())][:10]
    if not results: return bot.send_message(message.chat.id, "❌ No related services found.")
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in results: markup.add(types.InlineKeyboardButton(f"⚡ ID:{s['service']} | {s['name'][:25]}", callback_data=f"INFO|{s['service']}"))
    bot.send_message(message.chat.id, f"🔍 **Top Results:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("FAV_ADD|"))
def add_to_favorites(call):
    if check_spam(call.message.chat.id): return bot.answer_callback_query(call.id)
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$addToSet": {"favorites": sid}})
    bot.answer_callback_query(call.id, "⭐ Added to Favorites!", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data == "ASK_REFILL")
def ask_refill(call):
    msg = bot.send_message(call.message.chat.id, "🔄 **Enter Order ID to refill:**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: [bot.send_message(m.chat.id, "✅ Refill Requested!"), bot.send_message(ADMIN_ID, f"🔄 **REFILL:** Order `{m.text}` by `{m.chat.id}`")])

# ==========================================
# ৯. GEMINI AI ASSISTANT & SMART KEYWORDS
# ==========================================
@bot.callback_query_handler(func=lambda c: c.data == "TALK_HUMAN")
def talk_to_human(call):
    msg = bot.send_message(call.message.chat.id, "✍️ **Write your message for the Live Admin:**")
    bot.register_next_step_handler(msg, lambda m: [tickets_col.insert_one({"uid": m.chat.id, "msg": m.text, "status": "open", "date": datetime.now()}), bot.send_message(m.chat.id, "✅ Sent to Admin! They will reply soon.", parse_mode="Markdown")])

@bot.message_handler(func=lambda m: m.text not in ["🚀 New Order", "⭐ Favorites", "🔍 Smart Search", "📦 Orders", "💰 Deposit", "🤝 Affiliate", "👤 Profile", "🎟️ Voucher", "🏆 Leaderboard", "🎧 Support Ticket"])
def ai_smart_assistant(message):
    update_spy(message.chat.id, f"Typed: {message.text[:20]}")
    text = message.text.lower()
    
    # 9.1 Smart Keyword Detection for Buying Direct Orders
    if any(word in text for word in ["buy", "need", "want", "views", "likes", "followers", "subscribers"]):
        services = get_cached_services()
        hidden = get_settings().get("hidden_services", [])
        keywords = [word for word in text.split() if word not in ["buy", "need", "want", "some", "the", "a", "for", "my"]]
        
        results = []
        for s in services:
            if str(s['service']) in hidden: continue
            if any(k in s['name'].lower() for k in keywords): results.append(s)
            if len(results) >= 5: break
            
        if results:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for s in results: markup.add(types.InlineKeyboardButton(f"⚡ {s['name'][:25]}", callback_data=f"INFO|{s['service']}"))
            return bot.send_message(message.chat.id, "🤖 **Nexus AI:** I detected you want to buy something! Here are matching services:", reply_markup=markup, parse_mode="Markdown")

    # 9.2 Gemini AI Support Integration
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        system_prompt = "You are Nexus AI, a polite and professional support assistant for the NEXUS SMM Panel. Your job is to help users. To deposit: users must click the '💰 Deposit' button. To order: click '🚀 New Order'. If an order is canceled, they get an auto-refund. Do not invent fake service prices. Keep answers short and human-like. Answer this user: "
        prompt = system_prompt + message.text
        
        response = model.generate_content(prompt)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🗣 Transfer to Live Admin", callback_data="TALK_HUMAN"))
        bot.send_message(message.chat.id, f"🤖 **Nexus AI:**\n━━━━━━━━━━━━━━━━━━━━\n{response.text}", reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
        # Error Tracker
        error_msg = str(e)
        print(f"GEMINI ERROR: {error_msg}")
        bot.send_message(message.chat.id, f"⚠️ **AI Error Found:**\n`{error_msg[:200]}`\n\n_Admin, please check this error._", parse_mode="Markdown")
