from telebot import types
from loader import bot, users_col, orders_col
from config import *
import api
import math
import time
from datetime import datetime, timedelta

# ==========================================
# ১. API Caching System (রকেট স্পিড লোডিং)
# ==========================================
API_CACHE = {'data': [], 'last_fetch': 0}
CACHE_TTL = 300 # ৫ মিনিট ক্যাশে সেভ থাকবে

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
# ২. Smart Platform Algorithm
# ==========================================
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
# ৩. UI Helpers & Main Menu
# ==========================================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🚀 New Order", "⭐ Favorites")
    markup.add("🔍 Search by ID", "👤 Profile")
    markup.add("💰 Deposit", "📦 Orders")
    markup.add("🎁 Daily Bonus", "🏆 Leaderboard")
    markup.add("🎧 Support")
    return markup

def check_sub(chat_id):
    if not FORCE_SUB_CHANNEL: return True
    try:
        member = bot.get_chat_member(FORCE_SUB_CHANNEL, chat_id)
        if member.status in ['left', 'kicked']: return False
        return True
    except: return True 

# ==========================================
# ৪. Start, Test & Profile
# ==========================================
@bot.message_handler(commands=['test'])
def test_bot(message):
    bot.reply_to(message, "✅ **System is Online!** Webhook and Database connected perfectly.", parse_mode="Markdown")

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    name = message.from_user.first_name
    
    args = message.text.split()
    referrer = None
    if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid:
        referrer = int(args[1])

    user = users_col.find_one({"_id": uid})
    if not user:
        users_col.insert_one({
            "_id": uid, "name": name, "balance": 0.0, "spent": 0.0, 
            "ref_by": referrer, "joined": datetime.now(), "last_bonus": None, "favorites": []
        })
        if referrer:
            users_col.update_one({"_id": referrer}, {"$inc": {"balance": REF_BONUS}})
            try: bot.send_message(referrer, f"🎊 **New Referral!** You earned ${REF_BONUS}")
            except: pass

    if not check_sub(uid):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✈️ Join Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL.replace('@','')}"))
        markup.add(types.InlineKeyboardButton("✅ Joined", callback_data="CHECK_SUB"))
        bot.send_message(uid, f"⚠️ **Please join our channel first:**\n{FORCE_SUB_CHANNEL}", reply_markup=markup)
        return

    txt = (
        f"┏━━━━━━━◥◣◆◢◤━━━━━━━┓\n"
        f"   👋 **WELCOME TO NEXUS SMM**\n"
        f"┗━━━━━━━◥◣◆◢◤━━━━━━━┛\n\n"
        f"💠 **Elite Services at Best Rates**\n"
        f"✨ **Fastest Delivery Guarantee**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **USER ID:** `{uid}`"
    )
    bot.send_message(uid, txt, reply_markup=main_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CHECK_SUB")
def sub_check_callback(call):
    if check_sub(call.message.chat.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ **Verified!**", reply_markup=main_menu())
    else:
        bot.answer_callback_query(call.id, "❌ Not Joined Yet!", show_alert=True)

# ==========================================
# ৫. The 2-Tier Order System (Platform -> Category -> Service)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def show_platforms(message):
    if not check_sub(message.chat.id): return
    services = get_cached_services()
    if not services:
        return bot.send_message(message.chat.id, "❌ **API Error:** Could not fetch services.")

    # প্ল্যাটফর্ম বের করা
    platforms = set()
    for s in services:
        platforms.add(identify_platform(s['category']))
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btns = [types.InlineKeyboardButton(text=p, callback_data=f"PLAT|{p}") for p in sorted(platforms)]
    
    # 2-column grid-এ সাজানো
    for i in range(0, len(btns), 2):
        if i+1 < len(btns): markup.row(btns[i], btns[i+1])
        else: markup.row(btns[i])
        
    txt = "🟢 **Live API Status:** Active\n━━━━━━━━━━━━━━━━━━━━\n📂 **Select a Platform:**"
    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PLAT|"))
def show_categories(call):
    platform_name = call.data.split("|")[1]
    services = get_cached_services()
    
    # সব ইউনিক ক্যাটাগরির গ্লোবাল ইন্ডেক্স লিস্ট (যাতে বাটন লিমিট ক্রস না করে)
    all_cats = sorted(list(set(s['category'] for s in services)))
    
    # এই প্ল্যাটফর্মের আন্ডারে থাকা ক্যাটাগরিগুলো ফিল্টার করা
    plat_cats = [c for c in all_cats if identify_platform(c) == platform_name]
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for cat in plat_cats[:15]: # প্রথম ১৫টি ক্যাটাগরি দেখাবে
        idx = all_cats.index(cat)
        # নাম ছোট করা
        short_cat = cat.replace("Instagram", "").replace("Facebook", "").replace("YouTube", "").strip()
        if len(short_cat) < 3: short_cat = cat
        markup.add(types.InlineKeyboardButton(f"📁 {short_cat[:35]}", callback_data=f"CAT|{idx}|0"))
    
    markup.add(types.InlineKeyboardButton("🔙 Back to Platforms", callback_data="BACK_TO_PLAT"))
    
    bot.edit_message_text(f"📍 **Menu ➡️ {platform_name}**\n━━━━━━━━━━━━━━━━━━━━\n📂 **Select a Category:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "BACK_TO_PLAT")
def back_to_plat(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    show_platforms(call.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("CAT|"))
def list_services(call):
    data = call.data.split("|")
    cat_idx = int(data[1])
    page = int(data[2])
    
    services = get_cached_services()
    all_cats = sorted(list(set(s['category'] for s in services)))
    if cat_idx >= len(all_cats): return
    cat_name = all_cats[cat_idx]
    
    filtered = [s for s in services if s['category'] == cat_name]
    start = page * 10
    end = start + 10
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in filtered[start:end]:
        rate = round(float(s['rate']) + (float(s['rate']) * PROFIT_MARGIN / 100), 3)
        markup.add(types.InlineKeyboardButton(f"⚡ ID:{s['service']} | ${rate} | {s['name'][:25]}", callback_data=f"INFO|{s['service']}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CAT|{cat_idx}|{page-1}"))
    if end < len(filtered): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CAT|{cat_idx}|{page+1}"))
    if nav: markup.row(*nav)
    
    platform_name = identify_platform(cat_name)
    markup.add(types.InlineKeyboardButton(f"🔙 Back to {platform_name}", callback_data=f"PLAT|{platform_name}"))
    
    bot.edit_message_text(f"📍 **{platform_name} ➡️ Category**\n📦 **{cat_name}**\nPage: {page+1}/{math.ceil(len(filtered)/10)}", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

# ==========================================
# ৬. Info Card & Advanced Order Validation
# ==========================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|"))
def show_service_info(call):
    sid = call.data.split("|")[1]
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    
    if not s: return bot.answer_callback_query(call.id, "❌ Service not found!", show_alert=True)
        
    rate = round(float(s['rate']) + (float(s['rate']) * PROFIT_MARGIN / 100), 3)
    plat = identify_platform(s['category'])
    
    txt = (
        f"ℹ️ **SERVICE INFORMATION**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 **Name:** {s['name']}\n"
        f"🆔 **ID:** `{sid}`\n"
        f"💰 **Price:** `${rate}` / 1000\n"
        f"📉 **Min:** {s['min']} | 📈 **Max:** {s['max']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ **Note:** Make sure account is public."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🛒 Order Now", callback_data=f"START_ORD|{sid}"),
        types.InlineKeyboardButton("⭐ Fav", callback_data=f"FAV_ADD|{sid}")
    )
    # ডাইনামিক ব্যাক বাটন
    all_cats = sorted(list(set(x['category'] for x in services)))
    try: cat_idx = all_cats.index(s['category'])
    except: cat_idx = 0
    markup.add(types.InlineKeyboardButton("🔙 Back to Services", callback_data=f"CAT|{cat_idx}|0"))
    
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("START_ORD|"))
def ask_link(call):
    sid = call.data.split("|")[1]
    msg = bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, ask_qty, sid)

def ask_qty(message, sid):
    link = message.text
    msg = bot.send_message(message.chat.id, "🔢 **Enter Quantity (Numbers only):**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, order_preview, sid, link)

def order_preview(message, sid, link):
    try:
        qty = int(message.text)
        services = get_cached_services()
        s = next((x for x in services if str(x['service']) == str(sid)), None)
        
        if not s: return bot.send_message(message.chat.id, "❌ Error finding service.")
        if qty < int(s['min']) or qty > int(s['max']):
            return bot.send_message(message.chat.id, f"❌ Invalid Quantity! Min: {s['min']}, Max: {s['max']}")

        rate = round(float(s['rate']) + (float(s['rate']) * PROFIT_MARGIN / 100), 4)
        cost = round((rate / 1000) * qty, 3)
        
        user = users_col.find_one({"_id": message.chat.id})
        if user['balance'] < cost:
            bot.send_message(message.chat.id, f"❌ **Insufficient Balance!**\nYou need `${cost}` but have `${round(user['balance'],3)}`.")
            return

        users_col.update_one({"_id": message.chat.id}, {"$set": {"draft": {"sid": sid, "link": link, "qty": qty, "cost": cost}}})

        txt = (
            f"⚠️ **CONFIRM YOUR ORDER**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Service ID:** `{sid}`\n"
            f"🔗 **Link:** {link}\n"
            f"🔢 **Quantity:** {qty}\n"
            f"💰 **Total Cost:** `${cost}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Are you sure you want to proceed?"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ YES", callback_data="CONFIRM_ORDER"),
            types.InlineKeyboardButton("❌ NO", callback_data="CANCEL_ORDER")
        )
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

    except ValueError:
        bot.send_message(message.chat.id, "⚠️ **Invalid Input!** Must be a number.")

@bot.callback_query_handler(func=lambda c: c.data == "CONFIRM_ORDER")
def place_final_order(call):
    user = users_col.find_one({"_id": call.message.chat.id})
    draft = user.get('draft')
    
    if not draft: return bot.answer_callback_query(call.id, "❌ Session expired!", show_alert=True)
        
    bot.edit_message_text("⏳ **Placing order to server...**", call.message.chat.id, call.message.message_id)
    res = api.place_order(draft['sid'], draft['link'], draft['qty'])
    
    if 'order' in res:
        users_col.update_one({"_id": call.message.chat.id}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost']}, "$unset": {"draft": ""}})
        orders_col.insert_one({
            "oid": res['order'], "uid": call.message.chat.id, "sid": draft['sid'], 
            "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], 
            "status": "pending", "date": datetime.now()
        })
        bot.edit_message_text(f"✅ **ORDER SUCCESSFUL!**\n🆔 Order ID: `{res['order']}`\n💰 Deducted: `${draft['cost']}`", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        try: bot.send_message(ADMIN_ID, f"🔔 **New Order!**\nUser: `{call.message.chat.id}`\nAmount: `${draft['cost']}`")
        except: pass
    else:
        bot.edit_message_text(f"❌ **Failed:** {res.get('error')}", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORDER")
def cancel_order(call):
    users_col.update_one({"_id": call.message.chat.id}, {"$unset": {"draft": ""}})
    bot.edit_message_text("🚫 **Order Cancelled.**", call.message.chat.id, call.message.message_id)

# ==========================================
# ৭. Search, Favorites & Other Features
# ==========================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("FAV_ADD|"))
def add_to_favorites(call):
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$addToSet": {"favorites": sid}})
    bot.answer_callback_query(call.id, "⭐ Added to Favorites!", show_alert=True)

@bot.message_handler(func=lambda m: m.text == "⭐ Favorites")
def show_favorites(message):
    user = users_col.find_one({"_id": message.chat.id})
    favs = user.get("favorites", [])
    if not favs: return bot.send_message(message.chat.id, "📭 You have no favorite services.")
        
    services = get_cached_services()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for sid in favs:
        s = next((x for x in services if str(x['service']) == str(sid)), None)
        if s:
            rate = round(float(s['rate']) + (float(s['rate']) * PROFIT_MARGIN / 100), 3)
            markup.add(types.InlineKeyboardButton(f"⭐ ID:{s['service']} | ${rate}", callback_data=f"INFO|{s['service']}"))
    bot.send_message(message.chat.id, "⭐ **Your Favorite Services:**", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🔍 Search by ID")
def search_by_id(message):
    msg = bot.send_message(message.chat.id, "🔍 **Enter Service ID:**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_search)

def process_search(message):
    sid = message.text.strip()
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    
    if s:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("ℹ️ View & Order", callback_data=f"INFO|{sid}"))
        bot.send_message(message.chat.id, f"✅ **Service Found:**\n{s['name']}", reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "❌ Service not found.")

@bot.message_handler(func=lambda m: m.text == "👤 Profile")
def profile(message):
    u = users_col.find_one({"_id": message.chat.id})
    if not u: return
    txt = (
        f"👤 **USER ACCOUNT**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **ID:** `{u['_id']}`\n"
        f"💳 **Balance:** `${round(u.get('balance',0), 3)}`\n"
        f"💸 **Total Spent:** `${round(u.get('spent',0), 3)}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 **Ref Link:**\n`t.me/{bot.get_me().username}?start={u['_id']}`"
    )
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🎁 Daily Bonus")
def daily_bonus(message):
    user = users_col.find_one({"_id": message.chat.id})
    last_bonus = user.get('last_bonus')
    if last_bonus and datetime.now() < last_bonus + timedelta(days=1):
        return bot.send_message(message.chat.id, "⏳ Come back tomorrow for next bonus.")
    users_col.update_one({"_id": message.chat.id}, {"$inc": {"balance": DAILY_BONUS}, "$set": {"last_bonus": datetime.now()}})
    bot.send_message(message.chat.id, f"🎁 You claimed **${DAILY_BONUS}** bonus!")

@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def leaderboard(message):
    top_users = users_col.find().sort("spent", -1).limit(5)
    txt = "🏆 **TOP SPENDERS**\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, u in enumerate(top_users):
        txt += f"{i+1}. {u['name']} - `${round(u.get('spent',0), 2)}`\n"
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📦 Orders")
def my_orders(message):
    history = orders_col.find({"uid": message.chat.id}).sort("_id", -1).limit(5)
    txt = "📦 **YOUR RECENT ORDERS**\n━━━━━━━━━━━━━━━━━━━━\n"
    for o in history:
        txt += f"🆔 `{o['oid']}` | 💰 `${round(o['cost'],3)}` | 🏷 {str(o.get('status','N/A')).upper()}\n"
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "💰 Deposit")
def deposit(message):
    txt = f"💰 **DEPOSIT**\n━━━━━━━━━━━━━━━━━━━━\n💵 **Rate:** $1 = {EXCHANGE_RATE} BDT\n🏦 **bKash/Nagad:** `{PAYMENT_NUMBER}`\n━━━━━━━━━━━━━━━━━━━━\nSend money and click below."
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 Submit TrxID", callback_data="TRX"))
    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "TRX")
def trx_in(call):
    msg = bot.send_message(call.message.chat.id, "✍️ **Enter TrxID & Amount (e.g. TX123 500):**")
    bot.register_next_step_handler(msg, process_trx)

def process_trx(message):
    bot.send_message(message.chat.id, "✅ Request Submitted! Admin will add funds soon.")
    try: bot.send_message(ADMIN_ID, f"🔔 **DEPOSIT!**\nUser: `{message.chat.id}`\nMsg: {message.text}")
    except: pass

@bot.message_handler(func=lambda m: m.text == "🎧 Support")
def support(message):
    bot.send_message(message.chat.id, f"🎧 Contact Admin: {SUPPORT_USER}")
