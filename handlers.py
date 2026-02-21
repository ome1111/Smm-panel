from telebot import types
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col
from config import *
import api
import math
import time
import os
import threading
import re  # 🔥 নতুন অ্যাড করা হয়েছে সার্ভিসের নাম ক্লিন করার জন্য
from datetime import datetime
from google import genai

# ==========================================
# ১. AI & CURRENCY ENGINE SETTINGS
# ==========================================
# ⚠️ আপনার নতুন Google AI API Key এখানে অবশ্যই বসাবেন
GEMINI_API_KEY = "আপনার_নতুন_জেমিনি_কি_এখানে_দিন" 
client = genai.Client(api_key=GEMINI_API_KEY)

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

def update_spy(uid, action_text):
    try: users_col.update_one({"_id": uid}, {"$set": {"last_action": action_text, "last_active": datetime.now()}})
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
        try: bot.send_message(uid, "🛡 **ANTI-SPAM!** You are temporarily blocked for 5 minutes.", parse_mode="Markdown")
        except: pass
        return True
    return False

def get_settings():
    s = config_col.find_one({"_id": "settings"})
    if not s:
        s = {"_id": "settings", "channels": [], "profit_margin": 20.0, "maintenance": False, 
             "payments": [], "ref_target": 10, "ref_bonus": 5.0, "dep_commission": 5.0, "hidden_services": []}
        config_col.insert_one(s)
    return s

def check_maintenance(chat_id):
    if get_settings().get('maintenance', False) and str(chat_id) != str(ADMIN_ID):
        bot.send_message(chat_id, "🛠 **SYSTEM UPDATE**\n━━━━━━━━━━━━━━━━━━━━\nThe bot is undergoing a massive upgrade. Please try again later.", parse_mode="Markdown")
        return True
    return False

# ==========================================
# ২. ZERO-LAG DATABASE CACHE ⚡ 
# ==========================================
def fetch_services_task():
    try:
        res = api.get_services()
        if res and isinstance(res, list): 
            config_col.update_one({"_id": "api_cache"}, {"$set": {"data": res, "time": time.time()}}, upsert=True)
    except: pass

def get_cached_services():
    cache = config_col.find_one({"_id": "api_cache"})
    if not cache or not cache.get('data'):
        threading.Thread(target=fetch_services_task).start()
        return []
    if time.time() - cache.get('time', 0) > 600:
        threading.Thread(target=fetch_services_task).start()
    return cache.get('data', [])

# ==========================================
# ৩. UI LOGIC & SMART SERVICE CLEANER
# ==========================================
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
    n = raw_name
    # 🔥 যে শব্দগুলো হাইড করতে চান তার লিস্ট
    words_to_remove = ["Telegram", "TG", "Instagram", "IG", "Facebook", "FB", "YouTube", "YT", "TikTok", "Twitter", "X", "1xpanel", "1xPanel", "1XPANEL"]
    
    for word in words_to_remove:
        n = re.sub(word, "", n, flags=re.IGNORECASE)
    
    n = n.strip(" -|:._/\\")
    n = n.strip()
    
    badge = " 💎" if "non drop" in raw_name.lower() else " ⚡" if "fast" in raw_name.lower() or "instant" in raw_name.lower() else ""
    return f"{n[:50]}{badge}"  # 🔥 ফুল সার্ভিস নেম শো করার জন্য 50 দেওয়া হয়েছে

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

# ==========================================
# ৪. BOT REGISTRATION & VERIFICATION
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    update_spy(message.chat.id, "Bot Started")
    if check_spam(message.chat.id) or check_maintenance(message.chat.id): return
    uid = message.chat.id
    
    args = message.text.split()
    referrer = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid else None

    if not users_col.find_one({"_id": uid}):
        users_col.insert_one({"_id": uid, "name": message.from_user.first_name, "balance": 0.0, "spent": 0.0, "currency": "BDT", "ref_by": referrer, "ref_paid": False, "ref_earnings": 0.0, "joined": datetime.now(), "favorites": []})
    
    if not check_sub(uid):
        markup = types.InlineKeyboardMarkup()
        for ch in get_settings().get("channels", []): markup.add(types.InlineKeyboardButton(f"📢 Join {ch}", url=f"https://t.me/{ch.replace('@','')}"))
        markup.add(types.InlineKeyboardButton("🟢 VERIFY ACCOUNT 🟢", callback_data="CHECK_SUB"))
        return bot.send_message(uid, "🛑 **ACCESS RESTRICTED**\nJoin our official channels to unlock features.", reply_markup=markup, parse_mode="Markdown")

    bot.send_message(uid, f"👋 **WELCOME TO NEXUS SMM**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **Your ID:** `{uid}`", reply_markup=main_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CHECK_SUB")
def sub_callback(call):
    bot.answer_callback_query(call.id)
    if check_sub(call.message.chat.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ **Access Granted!**", reply_markup=main_menu())
    else: bot.send_message(call.message.chat.id, "❌ **Please join all channels first!**")

# ==========================================
# ৫. FAST ORDERING SYSTEM
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def new_order_start(message):
    update_spy(message.chat.id, "Browsing Platforms")
    if check_spam(message.chat.id) or check_maintenance(message.chat.id) or not check_sub(message.chat.id): return
    
    services = get_cached_services()
    if not services: 
        return bot.send_message(message.chat.id, "⏳ **API Syncing...** Server is fetching data. Please try again in 1 minute.", parse_mode="Markdown")

    hidden = get_settings().get("hidden_services", [])
    platforms = sorted(list(set(identify_platform(s['category']) for s in services if str(s['service']) not in hidden)))
    markup = types.InlineKeyboardMarkup(row_width=2)
    for p in platforms: markup.add(types.InlineKeyboardButton(p, callback_data=f"PLAT|{p}|0"))
    
    bot.send_message(message.chat.id, "🔥 **Trending Now:**\n👉 _Telegram Post Views_\n👉 _Instagram Premium Likes_\n━━━━━━━━━━━━━━━━━━━━\n📂 **Select a Platform:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PLAT|"))
def show_cats(call):
    bot.answer_callback_query(call.id)
    data = call.data.split("|")
    platform_name, page = data[1], int(data[2])
    update_spy(call.message.chat.id, f"Viewing {platform_name}")
    
    services = get_cached_services()
    hidden = get_settings().get("hidden_services", [])
    all_cats = sorted(list(set(s['category'] for s in services if identify_platform(s['category']) == platform_name and str(s['service']) not in hidden)))
    
    start_idx, end_idx = page * 15, page * 15 + 15
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for cat in all_cats[start_idx:end_idx]:
        full_cats = sorted(list(set(s['category'] for s in services)))
        idx = full_cats.index(cat)
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
    data = call.data.split("|")
    cat_idx, page = int(data[1]), int(data[2])
    
    services = get_cached_services()
    hidden = get_settings().get("hidden_services", [])
    all_cat_names = sorted(list(set(s['category'] for s in services)))
    if cat_idx >= len(all_cat_names): return
    cat_name = all_cat_names[cat_idx]
    
    filtered = [s for s in services if s['category'] == cat_name and str(s['service']) not in hidden]
    start_idx, end_idx = page * 10, page * 10 + 10
    
    user = users_col.find_one({"_id": call.message.chat.id})
    curr = user.get("currency", "BDT")
    _, discount = get_user_tier(user.get('spent', 0))
    profit = get_settings().get('profit_margin', 20.0)

    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in filtered[start_idx:end_idx]:
        rate_usd = (float(s['rate']) * (1 + profit/100)) * (1 - discount/100)
        rate_str = fmt_curr(rate_usd, curr)
        fancy_name = clean_service_name(s['name'])
        markup.add(types.InlineKeyboardButton(f"ID:{s['service']} | {rate_str} | {fancy_name}", callback_data=f"INFO|{s['service']}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CAT|{cat_idx}|{page-1}"))
    if end_idx < len(filtered): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CAT|{cat_idx}|{page+1}"))
    if nav: markup.row(*nav)
    
    plat = identify_platform(cat_name)
    markup.add(types.InlineKeyboardButton("🔙 Back to Categories", callback_data=f"PLAT|{plat}|0"))
    bot.edit_message_text(f"📍 **{plat}** ➔ **{cat_name[:20]}**\n━━━━━━━━━━━━━━━━━━━━\n📦 **Select Service:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|"))
def info_card(call):
    bot.answer_callback_query(call.id)
    sid = call.data.split("|")[1]
    update_spy(call.message.chat.id, f"Checking ID: {sid}")
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    
    if not s: return bot.send_message(call.message.chat.id, "❌ Service currently unavailable.")

    user = users_col.find_one({"_id": call.message.chat.id})
    curr = user.get("currency", "BDT")
    _, discount = get_user_tier(user.get('spent', 0))
    profit = get_settings().get('profit_margin', 20.0)
    
    rate_usd = (float(s['rate']) * (1 + profit/100)) * (1 - discount/100)
    rate_str = fmt_curr(rate_usd, curr)
    
    speed = "🚀 Speed: 10K - 50K / Day" if "fast" in s['name'].lower() or "instant" in s['name'].lower() else "🐢 Speed: 1K - 5K / Day"
    start_time = "⏱️ Start Time: 0-30 Minutes" if "instant" in s['name'].lower() else "⏱️ Start Time: 1-6 Hours"

    txt = (f"ℹ️ **SERVICE DETAILS**\n━━━━━━━━━━━━━━━━━━━━\n🏷 **Name:** {clean_service_name(s['name'])}\n🆔 **ID:** `{sid}`\n💰 **Price:** `{rate_str}` per 1000\n📉 **Min:** {s['min']} | 📈 **Max:** {s['max']}\n\n{start_time}\n{speed}\n━━━━━━━━━━━━━━━━━━━━\n⚠️ *Make sure your account/post is public!*")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🛒 Order Now", callback_data=f"ORD|{sid}"), types.InlineKeyboardButton("⭐ Fav", callback_data=f"FAV_ADD|{sid}"))
    
    all_cats = sorted(list(set(x['category'] for x in services)))
    try: cat_idx = all_cats.index(s['category'])
    except: cat_idx = 0
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"CAT|{cat_idx}|0"))
    
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ORD|"))
def start_ord(call):
    bot.answer_callback_query(call.id)
    sid = call.data.split("|")[1]
    msg = bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**\n_(e.g., https://t.me/yourchannel)_", parse_mode="Markdown")
    bot.register_next_step_handler(msg, get_qty, sid)

def get_qty(message, sid):
    link = message.text.strip()
    msg = bot.send_message(message.chat.id, "🔢 **Enter Quantity (Numbers only):**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, confirm_ord, sid, link)

def confirm_ord(message, sid, link):
    try:
        qty = int(message.text)
        services = get_cached_services()
        s = next((x for x in services if str(x['service']) == str(sid)), None)
        if not s or qty < int(s['min']) or qty > int(s['max']): 
            return bot.send_message(message.chat.id, f"❌ Invalid Quantity! Allowed: {s['min']} - {s['max']}")

        user = users_col.find_one({"_id": message.chat.id})
        curr = user.get("currency", "BDT")
        _, discount = get_user_tier(user.get('spent', 0))
        profit = get_settings().get('profit_margin', 20.0)
        
        rate_usd = (float(s['rate']) * (1 + profit/100)) * (1 - discount/100)
        cost_usd = (rate_usd / 1000) * qty
        
        curr_bal_usd = user['balance']
        after_bal_usd = curr_bal_usd - cost_usd
        
        if curr_bal_usd < cost_usd:
            return bot.send_message(message.chat.id, f"❌ **Insufficient Balance!**\nNeed `{fmt_curr(cost_usd, curr)}`, you have `{fmt_curr(curr_bal_usd, curr)}`.", parse_mode="Markdown")

        users_col.update_one({"_id": message.chat.id}, {"$set": {"draft": {"sid": sid, "link": link, "qty": qty, "cost": cost_usd}}})
        
        txt = f"⚠️ **ORDER PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **Service ID:** `{sid}`\n🔗 **Link:** {link}\n🔢 **Quantity:** {qty}\n━━━━━━━━━━━━━━━━━━━━\n💵 **Current Wallet:** `{fmt_curr(curr_bal_usd, curr)}`\n🛒 **Order Cost:** `- {fmt_curr(cost_usd, curr)}`\n🟢 **Balance After:** `{fmt_curr(after_bal_usd, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm your order?"
        
        markup = types.InlineKeyboardMarkup(row_width=2).add(types.InlineKeyboardButton("✅ CONFIRM", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
    except ValueError: 
        bot.send_message(message.chat.id, "⚠️ **Numbers only! Please start again.**")

@bot.callback_query_handler(func=lambda c: c.data == "PLACE_ORD")
def final_ord(call):
    bot.answer_callback_query(call.id)
    user = users_col.find_one({"_id": call.message.chat.id})
    curr = user.get("currency", "BDT")
    draft = user.get('draft')
    
    if not draft or user['balance'] < draft['cost']: return bot.send_message(call.message.chat.id, "❌ Session expired or insufficient balance.")
    update_spy(call.message.chat.id, f"Processing ID {draft['sid']}")
    
    bot.edit_message_text(f"⏳ **Processing Secure Payment...**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

    res = api.place_order(draft['sid'], draft['link'], draft['qty'])
    if res and 'order' in res:
        users_col.update_one({"_id": call.message.chat.id}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost']}, "$unset": {"draft": ""}})
        orders_col.insert_one({"oid": res['order'], "uid": call.message.chat.id, "sid": draft['sid'], "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], "status": "pending", "date": datetime.now()})
        
        success_txt = f"🎉 **ORDER PLACED SUCCESSFULLY!**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **Order ID:** `{res['order']}`\n💸 **Paid:** `{fmt_curr(draft['cost'], curr)}`\n\n_Track status in '📦 Orders' menu._"
        bot.edit_message_text(success_txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        
        ch = get_settings().get("fake_post_channel")
        if ch:
            try: bot.send_message(ch, f"🟢 **REAL ORDER PLACED!**\n👤 **User:** `***{str(call.message.chat.id)[-4:]}`\n📦 **Quantity:** {draft['qty']}\n💰 **Amount:** `{fmt_curr(draft['cost'], curr)}`", parse_mode="Markdown")
            except: pass
    else:
        err_msg = res.get('error') if res and 'error' in res else "API Connection Timeout. Main Server is down."
        bot.edit_message_text(f"❌ **Error:** {err_msg}\n_Your money is safe._", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORD")
def cancel_ord(call):
    bot.answer_callback_query(call.id)
    users_col.update_one({"_id": call.message.chat.id}, {"$unset": {"draft": ""}})
    bot.edit_message_text("🚫 **Order Cancelled by user.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

# ==========================================
# ৬. PROFILE & CURRENCY SELECTOR
# ==========================================
@bot.message_handler(func=lambda m: m.text == "👤 Profile")
def profile(message):
    update_spy(message.chat.id, "Viewing Profile")
    if check_spam(message.chat.id) or check_maintenance(message.chat.id) or not check_sub(message.chat.id): return
    u = users_col.find_one({"_id": message.chat.id})
    curr = u.get("currency", "BDT")
    tier, _ = get_user_tier(u.get('spent', 0))
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("🟢 BDT" if curr=="BDT" else "BDT", callback_data="SET_CURR|BDT"),
        types.InlineKeyboardButton("🟠 INR" if curr=="INR" else "INR", callback_data="SET_CURR|INR"),
        types.InlineKeyboardButton("🔵 USD" if curr=="USD" else "USD", callback_data="SET_CURR|USD")
    )
    
    card = (f"```text\n╔════════════════════════════════╗\n"
            f"║  🌟 NEXUS VIP PASSPORT         ║\n"
            f"╠════════════════════════════════╣\n"
            f"║  👤 Name: {str(message.from_user.first_name)[:12].ljust(19)}║\n"
            f"║  🆔 UID: {str(u['_id']).ljust(20)}║\n"
            f"║  💳 Balance: {fmt_curr(u.get('balance',0), curr).ljust(18)}║\n"
            f"║  💸 Spent: {fmt_curr(u.get('spent',0), curr).ljust(20)}║\n"
            f"║  👑 Tier: {tier.ljust(19)}║\n"
            f"╚════════════════════════════════╝\n```\n"
            f"⚙️ **Click below to change your App Currency:**")
    bot.send_message(message.chat.id, card, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("SET_CURR|"))
def set_curr(call):
    bot.answer_callback_query(call.id)
    new_curr = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"currency": new_curr}})
    bot.edit_message_text(f"✅ **App Currency updated to {new_curr}!**\n\n_Check '🚀 New Order' or '👤 Profile' again to see updated prices._", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

# ==========================================
# ৭. UNIVERSAL FEATURES (ORDERS, SEARCH, DEPOSIT, AFFILIATE, TICKETS, FAV)
# ==========================================
def fetch_orders_page(chat_id, page=0):
    user = users_col.find_one({"_id": chat_id})
    curr = user.get("currency", "BDT") if user else "BDT"
    
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
        txt += f"🆔 `{o['oid']}` | 💰 `{fmt_curr(o['cost'], curr)}`\n🔗 {str(o.get('link', 'N/A'))[:25]}...\n🏷 Status: {status_text}\n\n"
        
    markup = types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"MYORD|{page-1}"))
    if end < len(all_orders): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"MYORD|{page+1}"))
    if nav: markup.row(*nav)
    markup.add(types.InlineKeyboardButton("🔄 Request Refill", callback_data="ASK_REFILL"))
    return txt, markup

@bot.callback_query_handler(func=lambda c: c.data.startswith("MYORD|"))
def my_orders_pagination(call):
    bot.answer_callback_query(call.id, "⏳ Syncing Status...")
    page = int(call.data.split("|")[1])
    txt, markup = fetch_orders_page(call.message.chat.id, page)
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

def process_voucher(message):
    code = message.text.strip().upper()
    voucher = vouchers_col.find_one({"code": code})
    if not voucher: return bot.send_message(message.chat.id, "❌ Invalid Voucher.")
    if len(voucher.get('used_by', [])) >= voucher['limit']: return bot.send_message(message.chat.id, "❌ Limit Reached!")
    if message.chat.id in voucher.get('used_by', []): return bot.send_message(message.chat.id, "❌ Already claimed.")
    
    vouchers_col.update_one({"code": code}, {"$push": {"used_by": message.chat.id}})
    users_col.update_one({"_id": message.chat.id}, {"$inc": {"balance": voucher['amount']}})
    
    user = users_col.find_one({"_id": message.chat.id})
    curr = user.get("currency", "BDT")
    msg = f"> 🧾 **VOUCHER RECEIPT**\n> ━━━━━━━━━━━━━━━━━━━━\n> ✅ **Status:** CLAIMED\n> 🎁 **Code:** `{code}`\n> 💰 **Reward:** `{fmt_curr(voucher['amount'], curr)}` added."
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

def process_smart_search(message):
    query = message.text.strip().lower()
    services, hidden = get_cached_services(), get_settings().get("hidden_services", [])
    if query.isdigit():
        s = next((x for x in services if str(x['service']) == query and query not in hidden), None)
        if s: return bot.send_message(message.chat.id, f"✅ **Found:** {s['name']}", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("ℹ️ Order Now", callback_data=f"INFO|{query}")), parse_mode="Markdown")
    results = [s for s in services if str(s['service']) not in hidden and (query in s['name'].lower() or query in s['category'].lower())][:10]
    if not results: return bot.send_message(message.chat.id, "❌ No related services found.")
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in results: markup.add(types.InlineKeyboardButton(f"⚡ ID:{s['service']} | {clean_service_name(s['name'])[:25]}", callback_data=f"INFO|{s['service']}"))
    bot.send_message(message.chat.id, f"🔍 **Top Results:**", reply_markup=markup, parse_mode="Markdown")

def process_amt(message, curr_code):
    try:
        amt_local = float(message.text)
        rate = CURRENCY_RATES.get(curr_code, 1)
        amt_usd = amt_local / rate
        payments = get_settings().get("payments", [])
        markup = types.InlineKeyboardMarkup()
        for p in payments: 
            pay_amt = round(amt_usd * float(p['rate']), 2)
            markup.add(types.InlineKeyboardButton(f"🏦 {p['name']} (Pay {pay_amt} BDT)", callback_data=f"PAY|{amt_usd}|{p['name']}"))
        bot.send_message(message.chat.id, "💳 **Select Gateway:**", reply_markup=markup, parse_mode="Markdown")
    except: bot.send_message(message.chat.id, "⚠️ Invalid amount.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PAY|"))
def pay_details(call):
    bot.answer_callback_query(call.id)
    _, amt, method = call.data.split("|")
    bot.edit_message_text(f"🏦 **{method} Payment**\nSend money and reply with **TrxID**.", call.message.chat.id, call.message.message_id)
    bot.register_next_step_handler(call.message, process_deposit_trx, amt, method)

def process_deposit_trx(message, amt, method_name):
    tid = message.text.strip()
    bot.send_message(message.chat.id, "✅ **Request Submitted!**\nAdmin will verify your TrxID.", parse_mode="Markdown")
    admin_txt = f"🔔 **NEW DEPOSIT**\n👤 User: `{message.chat.id}`\n🏦 Method: **{method_name}**\n💰 Amt: **${round(float(amt), 2)}** (USD)\n🧾 TrxID: `{tid}`"
    markup = types.InlineKeyboardMarkup(row_width=2)
    app_url = BASE_URL.rstrip('/')
    markup.add(types.InlineKeyboardButton("✅ APPROVE", url=f"{app_url}/approve_dep/{message.chat.id}/{amt}/{tid}"), types.InlineKeyboardButton("❌ REJECT", url=f"{app_url}/reject_dep/{message.chat.id}/{tid}"))
    try: bot.send_message(ADMIN_ID, admin_txt, reply_markup=markup, parse_mode="Markdown")
    except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("FAV_ADD|"))
def add_to_favorites(call):
    bot.answer_callback_query(call.id, "⭐ Added to Favorites!", show_alert=True)
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$addToSet": {"favorites": sid}})

@bot.callback_query_handler(func=lambda c: c.data == "ASK_REFILL")
def ask_refill(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🔄 **Enter Order ID to refill:**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: [bot.send_message(m.chat.id, "✅ Refill Requested!"), bot.send_message(ADMIN_ID, f"🔄 **REFILL:** Order `{m.text}` by `{m.chat.id}`")])

@bot.message_handler(func=lambda m: m.text in ["⭐ Favorites", "🏆 Leaderboard", "📦 Orders", "💰 Deposit", "🎧 Support Ticket", "🔍 Smart Search", "🤝 Affiliate", "🎟️ Voucher"])
def universal_buttons(message):
    update_spy(message.chat.id, f"Clicked {message.text}")
    if check_spam(message.chat.id) or check_maintenance(message.chat.id) or not check_sub(message.chat.id): return
    
    u = users_col.find_one({"_id": message.chat.id})
    curr = u.get("currency", "BDT") if u else "BDT"

    if message.text == "📦 Orders":
        txt, markup = fetch_orders_page(message.chat.id, 0)
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        
    elif message.text == "💰 Deposit":
        msg = bot.send_message(message.chat.id, f"💵 **Enter Deposit Amount ({curr}):**\n_(e.g. 100, 500)_", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_amt, curr)
        
    elif message.text == "🎟️ Voucher":
        msg = bot.send_message(message.chat.id, "🎁 **Enter Promo Code:**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_voucher)
        
    elif message.text == "🤝 Affiliate":
        ref_link = f"https://t.me/{bot.get_me().username}?start={message.chat.id}"
        total_joined = users_col.count_documents({"ref_by": message.chat.id})
        txt = f"🤝 **AFFILIATE DASHBOARD**\n━━━━━━━━━━━━━━━━━━━━\n🔗 **Your Link:**\n`{ref_link}`\n\n👥 **Total Invites:** {total_joined}\n💰 **Earned:** `{fmt_curr(u.get('ref_earnings', 0.0), curr)}`"
        bot.send_message(message.chat.id, txt, parse_mode="Markdown", disable_web_page_preview=True)
        
    elif message.text == "🏆 Leaderboard":
        top = users_col.find().sort("spent", -1).limit(5)
        txt = "🏆 **TOP 5 SPENDERS**\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, t_user in enumerate(top): txt += f"{i+1}. {t_user['name']} - `{fmt_curr(t_user.get('spent',0), curr)}`\n"
        bot.send_message(message.chat.id, txt, parse_mode="Markdown")
        
    elif message.text == "🔍 Smart Search":
        msg = bot.send_message(message.chat.id, "🔍 **Smart Search**\nEnter Service ID or Keyword:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_smart_search)
        
    elif message.text == "🎧 Support Ticket":
        msg = bot.send_message(message.chat.id, "🎧 **Describe your issue clearly:**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m: [tickets_col.insert_one({"uid": m.chat.id, "msg": m.text, "status": "open", "date": datetime.now()}), bot.send_message(m.chat.id, "✅ Ticket Sent!", parse_mode="Markdown")])
        
    elif message.text == "⭐ Favorites":
        favs = u.get("favorites", [])
        if not favs: return bot.send_message(message.chat.id, "📭 You have no favorites.")
        services, markup = get_cached_services(), types.InlineKeyboardMarkup(row_width=1)
        for sid in favs:
            s = next((x for x in services if str(x['service']) == str(sid)), None)
            if s: markup.add(types.InlineKeyboardButton(f"⭐ ID:{s['service']} | {clean_service_name(s['name'])[:25]}", callback_data=f"INFO|{s['service']}"))
        bot.send_message(message.chat.id, "⭐ **Your Favorites:**", reply_markup=markup, parse_mode="Markdown")

# ==========================================
# ৮. AI HANDLER (GEMINI 2.0 FLASH) 🤖
# ==========================================
@bot.callback_query_handler(func=lambda c: c.data == "TALK_HUMAN")
def talk_to_human(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "✍️ **Write your message for Admin:**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: [tickets_col.insert_one({"uid": m.chat.id, "msg": m.text, "status": "open", "date": datetime.now()}), bot.send_message(m.chat.id, "✅ Ticket Sent!")])

@bot.message_handler(func=lambda m: True)
def ai_chat(message):
    update_spy(message.chat.id, "Chatting with AI")
    if check_spam(message.chat.id) or check_maintenance(message.chat.id) or not check_sub(message.chat.id): return
    
    text = message.text.lower()
    if any(word in text for word in ["buy", "need", "followers", "likes", "views"]):
        services = get_cached_services()
        results = [s for s in services if any(k in s['name'].lower() for k in text.split())][:5]
        if results:
            markup = types.InlineKeyboardMarkup()
            for s in results: markup.add(types.InlineKeyboardButton(f"⚡ {clean_service_name(s['name'])[:25]}", callback_data=f"INFO|{s['service']}"))
            return bot.send_message(message.chat.id, "🤖 **Nexus AI:** I found these premium services for you:", reply_markup=markup, parse_mode="Markdown")

    bot.send_chat_action(message.chat.id, 'typing')
    try:
        prompt = f"Role: Nexus SMM Support. User asks: {message.text}. Rule: Be short, friendly and native Bengali/English."
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🗣 Contact Admin", callback_data="TALK_HUMAN"))
        bot.send_message(message.chat.id, f"🤖 **Nexus AI:**\n━━━━━━━━━━━━━━━━━━━━\n{response.text}", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ **AI Error:** `{str(e)[:100]}`", parse_mode="Markdown")

