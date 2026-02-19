from telebot import types
from loader import bot, users_col, orders_col
from config import *
import api
import math
from datetime import datetime, timedelta

# ==========================================
# ১. মেইন মেনু এবং হেল্পার ফাংশন
# ==========================================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🚀 New Order", "⭐ Favorites")
    markup.add("🔍 Search by ID", "👤 Profile")
    markup.add("💰 Deposit", "📦 Orders")
    markup.add("🎁 Daily Bonus", "🏆 Leaderboard")
    markup.add("🎧 Support", "📚 Tutorial")
    return markup

def check_sub(chat_id):
    if not FORCE_SUB_CHANNEL: return True
    try:
        member = bot.get_chat_member(FORCE_SUB_CHANNEL, chat_id)
        if member.status in ['left', 'kicked']: return False
        return True
    except: return True 

# ==========================================
@bot.message_handler(commands=['test'])
def test_bot(message):
    bot.reply_to(message, "✅ Bot is Alive! The webhook is working. Problem is in Database.")

# ২. ওয়েলকাম ও প্রোফাইল
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    name = message.from_user.first_name
    
    args = message.text.split()
    referrer = None
    if len(args) > 1 and args[1].isdigit():
        ref_id = int(args[1])
        if ref_id != uid: referrer = ref_id

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
# ৩. স্মার্ট অর্ডার সিস্টেম (Pagination + Info Card)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def order_init(message):
    if not check_sub(message.chat.id): return
    msg = bot.send_message(message.chat.id, "🔍 **Analyzing Database...**")
    
    services = api.get_services()
    if not services or 'error' in services:
        bot.edit_message_text("❌ **API Connection Error.**", message.chat.id, msg.message_id)
        return

    cats = sorted(list(set(s['category'] for s in services)))
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for i, cat in enumerate(cats[:10]):
        markup.add(types.InlineKeyboardButton(f"📁 {cat}", callback_data=f"CAT|{i}|0"))
    
    if len(cats) > 10:
        markup.add(types.InlineKeyboardButton("Next Page ➡️", callback_data="CATPAGE|1"))
        
    bot.edit_message_text("📂 **Select Service Category:**", message.chat.id, msg.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("CATPAGE|"))
def cat_pagination(call):
    page = int(call.data.split("|")[1])
    services = api.get_services()
    cats = sorted(list(set(s['category'] for s in services)))
    
    start = page * 10
    end = start + 10
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for i, cat in enumerate(cats[start:end], start=start):
        markup.add(types.InlineKeyboardButton(f"📁 {cat}", callback_data=f"CAT|{i}|0"))
    
    nav_buttons = []
    if page > 0: nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CATPAGE|{page-1}"))
    if end < len(cats): nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CATPAGE|{page+1}"))
    if nav_buttons: markup.row(*nav_buttons)
    
    bot.edit_message_text("📂 **Select Service Category:**", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("CAT|"))
def list_services(call):
    data = call.data.split("|")
    cat_idx = int(data[1])
    page = int(data[2])
    
    services = api.get_services()
    cats = sorted(list(set(s['category'] for s in services)))
    if cat_idx >= len(cats): return
    cat_name = cats[cat_idx]
    
    filtered = [s for s in services if s['category'] == cat_name]
    start = page * 10
    end = start + 10
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in filtered[start:end]:
        rate = round(float(s['rate']) + (float(s['rate']) * PROFIT_MARGIN / 100), 3)
        markup.add(types.InlineKeyboardButton(f"ID:{s['service']} | ${rate} | {s['name'][:25]}", callback_data=f"INFO|{s['service']}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CAT|{cat_idx}|{page-1}"))
    if end < len(filtered): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CAT|{cat_idx}|{page+1}"))
    if nav: markup.row(*nav)
    
    markup.add(types.InlineKeyboardButton("🔙 Back to Categories", callback_data="CATPAGE|0"))
    bot.edit_message_text(f"📦 **Category:** {cat_name}\nPage: {page+1}/{math.ceil(len(filtered)/10)}", call.message.chat.id, call.message.message_id, reply_markup=markup)

# ==========================================
# ৪. ইনফো কার্ড এবং ডাইনামিক অর্ডার কনফার্মেশন
# ==========================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|"))
def show_service_info(call):
    sid = call.data.split("|")[1]
    services = api.get_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    
    if not s:
        bot.answer_callback_query(call.id, "❌ Service not found!", show_alert=True)
        return
        
    rate = round(float(s['rate']) + (float(s['rate']) * PROFIT_MARGIN / 100), 3)
    
    txt = (
        f"ℹ️ **SERVICE INFORMATION**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 **Name:** {s['name']}\n"
        f"🆔 **Service ID:** `{sid}`\n"
        f"💰 **Price:** `${rate}` / 1000\n"
        f"📉 **Min Order:** {s['min']}\n"
        f"📈 **Max Order:** {s['max']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ **Description:**\n{s.get('description', 'No special instructions.')}"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🛒 Order Now", callback_data=f"START_ORD|{sid}"),
        types.InlineKeyboardButton("⭐ Add to Fav", callback_data=f"FAV_ADD|{sid}")
    )
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="CATPAGE|0"))
    
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("START_ORD|"))
def ask_link(call):
    sid = call.data.split("|")[1]
    msg = bot.send_message(call.message.chat.id, "🔗 **Please provide the target Link:**\n*(Make sure the account is public)*", parse_mode="Markdown")
    bot.register_next_step_handler(msg, ask_qty, sid)

def ask_qty(message, sid):
    link = message.text
    msg = bot.send_message(message.chat.id, "🔢 **Enter Quantity:**\n*(Numbers only)*", parse_mode="Markdown")
    bot.register_next_step_handler(msg, order_preview, sid, link)

def order_preview(message, sid, link):
    try:
        qty = int(message.text)
        services = api.get_services()
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
            f"⚠️ **ORDER CONFIRMATION**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Service ID:** `{sid}`\n"
            f"🔗 **Link:** {link}\n"
            f"🔢 **Quantity:** {qty}\n"
            f"💰 **Total Cost:** `${cost}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Do you want to place this order?"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ YES, CONFIRM ORDER", callback_data="CONFIRM_ORDER"))
        markup.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORDER"))
        
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

    except ValueError:
        bot.send_message(message.chat.id, "⚠️ **Invalid Input!** Must be a number.")

@bot.callback_query_handler(func=lambda c: c.data == "CONFIRM_ORDER")
def place_final_order(call):
    user = users_col.find_one({"_id": call.message.chat.id})
    draft = user.get('draft')
    
    if not draft:
        return bot.answer_callback_query(call.id, "❌ Order session expired!", show_alert=True)
        
    bot.edit_message_text("⏳ **Connecting to API...**", call.message.chat.id, call.message.message_id)
    
    res = api.place_order(draft['sid'], draft['link'], draft['qty'])
    
    if 'order' in res:
        users_col.update_one(
            {"_id": call.message.chat.id}, 
            {"$inc": {"balance": -draft['cost'], "spent": draft['cost']}, "$unset": {"draft": ""}}
        )
        orders_col.insert_one({
            "oid": res['order'], "uid": call.message.chat.id, "sid": draft['sid'], 
            "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], 
            "status": "pending", "date": datetime.now()
        })
        
        txt = f"✅ **ORDER SUCCESSFUL!**\n🆔 Order ID: `{res['order']}`\n💰 Cost: `${draft['cost']}`"
        bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        
        try: bot.send_message(ADMIN_ID, f"🔔 **New Sale!**\nUser: `{call.message.chat.id}`\nAmount: `${draft['cost']}`")
        except: pass
    else:
        bot.edit_message_text(f"❌ **API Error:** {res.get('error')}", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORDER")
def cancel_order(call):
    users_col.update_one({"_id": call.message.chat.id}, {"$unset": {"draft": ""}})
    bot.edit_message_text("🚫 **Order Cancelled.**", call.message.chat.id, call.message.message_id)

# ==========================================
# ৫. সার্চ এবং ফেভারিট সিস্টেম
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
    
    if not favs:
        return bot.send_message(message.chat.id, "📭 You haven't added any favorite services yet.")
        
    services = api.get_services()
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for sid in favs:
        s = next((x for x in services if str(x['service']) == str(sid)), None)
        if s:
            rate = round(float(s['rate']) + (float(s['rate']) * PROFIT_MARGIN / 100), 3)
            markup.add(types.InlineKeyboardButton(f"⭐ ID:{s['service']} | ${rate}", callback_data=f"INFO|{s['service']}"))
            
    bot.send_message(message.chat.id, "⭐ **Your Favorite Services:**", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🔍 Search by ID")
def search_by_id(message):
    msg = bot.send_message(message.chat.id, "🔍 **Enter Service ID:**\n*(e.g., 1045)*", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_search)

def process_search(message):
    sid = message.text.strip()
    services = api.get_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    
    if s:
        rate = round(float(s['rate']) + (float(s['rate']) * PROFIT_MARGIN / 100), 3)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("ℹ️ View Details", callback_data=f"INFO|{sid}"))
        bot.send_message(message.chat.id, f"✅ **Service Found:**\n{s['name']}\n💰 `${rate}`", reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "❌ Service ID not found. Please try again.")

# ==========================================
# ৬. অন্যান্য ফিচার (Profile, Deposit, Bonus, Support)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "👤 Profile")
def profile(message):
    u = users_col.find_one({"_id": message.chat.id})
    if not u: return
    txt = (
        f"👤 **USER ACCOUNT INFO**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **ID:** `{u['_id']}`\n"
        f"💳 **Balance:** `${round(u.get('balance',0), 3)}`\n"
        f"💸 **Total Spent:** `${round(u.get('spent',0), 3)}`\n"
        f"🏆 **Status:** Verified User\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 **Referral Link:**\n`t.me/{bot.get_me().username}?start={u['_id']}`"
    )
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🎁 Daily Bonus")
def daily_bonus(message):
    user = users_col.find_one({"_id": message.chat.id})
    last_bonus = user.get('last_bonus')
    
    if last_bonus and datetime.now() < last_bonus + timedelta(days=1):
        bot.send_message(message.chat.id, "⏳ **আগামীকাল আবার আসুন!** আপনি আজকের বোনাস নিয়ে নিয়েছেন।")
        return
    
    users_col.update_one({"_id": message.chat.id}, {"$inc": {"balance": DAILY_BONUS}, "$set": {"last_bonus": datetime.now()}})
    bot.send_message(message.chat.id, f"🎁 **অভিনন্দন!** আপনি **${DAILY_BONUS}** বোনাস পেয়েছেন।")

@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def leaderboard(message):
    top_users = users_col.find().sort("spent", -1).limit(5)
    txt = "🏆 **TOP SPENDERS (ALL TIME)**\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, u in enumerate(top_users):
        txt += f"{i+1}. {u['name']} - `${round(u.get('spent',0), 2)}`\n"
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📦 Orders")
def my_orders(message):
    history = orders_col.find({"uid": message.chat.id}).sort("_id", -1).limit(5)
    txt = "📦 **YOUR RECENT ORDERS**\n━━━━━━━━━━━━━━━━━━━━\n"
    if orders_col.count_documents({"uid": message.chat.id}) == 0:
        txt += "No orders found."
    for o in history:
        txt += f"🆔 `{o['oid']}` | 💰 `${round(o['cost'],3)}` | 🏷 {str(o.get('status','N/A')).upper()}\n"
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "💰 Deposit")
def deposit(message):
    txt = (
        f"💰 **ডিপোজিট করার নিয়ম**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 **রেট:** $1 = {EXCHANGE_RATE} BDT\n"
        f"🏦 **বিকাশ/নগদ:** `{PAYMENT_NUMBER}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"টাকা পাঠিয়ে TrxID এবং Amount দিন।"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 Submit TrxID", callback_data="TRX"))
    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "TRX")
def trx_in(call):
    msg = bot.send_message(call.message.chat.id, "✍️ **TrxID এবং পরিমাণ দিন (যেমন: TX123 500):**")
    bot.register_next_step_handler(msg, process_trx)

def process_trx(message):
    bot.send_message(message.chat.id, "✅ **Request Submitted!** Admin will verify and add funds shortly.")
    try: bot.send_message(ADMIN_ID, f"🔔 **DEPOSIT REQUEST!**\nUser: `{message.chat.id}`\nDetails: {message.text}")
    except: pass

@bot.message_handler(func=lambda m: m.text == "🎧 Support")
def support(message):
    bot.send_message(message.chat.id, f"🎧 **সাপোর্ট দরকার?**\nআমাদের এডমিনের সাথে যোগাযোগ করুন: {SUPPORT_USER}")
