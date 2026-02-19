from telebot import types
from loader import bot, users_col, orders_col
from config import *
import api
from datetime import datetime, timedelta

# ==========================================
# ১. কাস্টম কীবোর্ড (Main Menu)
# ==========================================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🚀 New Order", "👤 Profile")
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
# ২. স্টার্ট কমান্ড এবং ওয়েলকাম মেসেজ
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    name = message.from_user.first_name
    
    # রেফারেল সিস্টেম চেক
    args = message.text.split()
    referrer = None
    if len(args) > 1 and args[1].isdigit():
        ref_id = int(args[1])
        if ref_id != uid: referrer = ref_id

    # নতুন ইউজার ডাটাবেসে সেভ করা
    user = users_col.find_one({"_id": uid})
    if not user:
        users_col.insert_one({
            "_id": uid, "name": name, "balance": 0.0, "spent": 0.0, 
            "ref_by": referrer, "joined": datetime.now(), "last_bonus": None
        })
        # রেফারারকে বোনাস দেওয়া
        if referrer:
            users_col.update_one({"_id": referrer}, {"$inc": {"balance": REF_BONUS}})
            try: bot.send_message(referrer, f"🎊 **New Referral!** {name} joined via your link. You earned ${REF_BONUS}")
            except: pass

    # চ্যানেল সাবস্ক্রিপশন চেক
    if not check_sub(uid):
        markup = types.InlineKeyboardMarkup()
        btn_url = f"https://t.me/{FORCE_SUB_CHANNEL.replace('@','')}"
        markup.add(types.InlineKeyboardButton("✈️ Join Channel", url=btn_url))
        markup.add(types.InlineKeyboardButton("✅ Joined", callback_data="CHECK_SUB"))
        bot.send_message(uid, f"⚠️ **Please join our channel first:**\n{FORCE_SUB_CHANNEL}", reply_markup=markup)
        return

    # মডার্ন ওয়েলকাম মেসেজ
    txt = (
        f"┏━━━━━━━◥◣◆◢◤━━━━━━━┓\n"
        f"   👋 **WELCOME TO NEXUS SMM**\n"
        f"┗━━━━━━━◥◣◆◢◤━━━━━━━┛\n\n"
        f"💠 **Elite Services at Best Rates**\n"
        f"✨ **Fastest Delivery Guarantee**\n"
        f"🎧 **24/7 Human Support**\n\n"
        f"📢 **Join Updates:** {FORCE_SUB_CHANNEL}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **USER ID:** `{uid}`"
    )
    bot.send_message(uid, txt, reply_markup=main_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CHECK_SUB")
def sub_check_callback(call):
    if check_sub(call.message.chat.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ **Verification Successful!**", reply_markup=main_menu())
    else:
        bot.answer_callback_query(call.id, "❌ Not Joined Yet!", show_alert=True)

# ==========================================
# ৩. প্রোফাইল এবং বোনাস সিস্টেম
# ==========================================
@bot.message_handler(func=lambda m: m.text == "👤 Profile")
def profile(message):
    u = users_col.find_one({"_id": message.chat.id})
    if not u: return
    txt = (
        f"👤 **USER ACCOUNT INFO**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Account ID:** `{u['_id']}`\n"
        f"💳 **Available Balance:** `${round(u.get('balance', 0), 3)}`\n"
        f"💸 **Total Spent:** `${round(u.get('spent', 0), 3)}`\n"
        f"🏆 **Account Status:** Verified User ✅\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 **Your Referral Link:**\n`https://t.me/{bot.get_me().username}?start={u['_id']}`"
    )
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🎁 Daily Bonus")
def daily_bonus(message):
    user = users_col.find_one({"_id": message.chat.id})
    last_bonus = user.get('last_bonus')
    
    if last_bonus and datetime.now() < last_bonus + timedelta(days=1):
        bot.send_message(message.chat.id, "⏳ **Please wait!** You can claim your next bonus tomorrow.")
        return
    
    users_col.update_one({"_id": message.chat.id}, {"$inc": {"balance": DAILY_BONUS}, "$set": {"last_bonus": datetime.now()}})
    bot.send_message(message.chat.id, f"🎁 **Congratulations!** You received **${DAILY_BONUS}** daily bonus.")

@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def leaderboard(message):
    top_users = users_col.find().sort("spent", -1).limit(5)
    txt = "🏆 **TOP SPENDERS (ALL TIME)**\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, u in enumerate(top_users):
        txt += f"**{i+1}.** {u['name']} - `${round(u.get('spent',0), 2)}`\n"
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📦 Orders")
def my_orders(message):
    history = orders_col.find({"uid": message.chat.id}).sort("_id", -1).limit(5)
    txt = "📦 **YOUR RECENT ORDERS**\n━━━━━━━━━━━━━━━━━━━━\n"
    if orders_col.count_documents({"uid": message.chat.id}) == 0:
        txt += "No orders found."
    for o in history:
        txt += f"🆔 `{o['oid']}` | 💰 `${round(o['cost'], 3)}` | 🏷 {str(o.get('status','N/A')).upper()}\n"
    bot.send_message(message.chat.id, txt, parse_mode="Markdown")

# ==========================================
# ৪. নিউ অর্ডার সিস্টেম (Dynamic API)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def order_init(message):
    if not check_sub(message.chat.id): return
    msg = bot.send_message(message.chat.id, "🔍 **Loading Categories...**")
    
    services = api.get_services()
    if not services or 'error' in services:
        bot.edit_message_text("❌ **API Connection Error.** Please try again later.", message.chat.id, msg.message_id)
        return

    cats = sorted(list(set(s['category'] for s in services)))
    markup = types.InlineKeyboardMarkup(row_width=1)
    for i, cat in enumerate(cats[:30]): # Limiting to 30 to avoid Telegram button limits
        markup.add(types.InlineKeyboardButton(f"📁 {cat}", callback_data=f"C|{i}"))
    
    bot.edit_message_text("📂 **Select a Service Category:**", message.chat.id, msg.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("C|"))
def list_services(call):
    idx = int(call.data.split("|")[1])
    services = api.get_services()
    cats = sorted(list(set(s['category'] for s in services)))
    
    if idx >= len(cats): return
    cat_name = cats[idx]
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    filtered = [s for s in services if s['category'] == cat_name]
    for s in filtered[:20]: # Show top 20 services in category
        rate = round(float(s['rate']) + (float(s['rate']) * PROFIT_MARGIN / 100), 4)
        markup.add(types.InlineKeyboardButton(f"⚡ ID:{s['service']} | ${rate} | {s['name'][:20]}..", callback_data=f"S|{s['service']}|{rate}"))
    
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="BACK_CATS"))
    bot.edit_message_text(f"📦 **Category:** {cat_name}\nSelect a service:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "BACK_CATS")
def back_to_categories(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    order_init(call.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("S|"))
def service_desc(call):
    _, sid, rate = call.data.split("|")
    txt = (
        f"📦 **SERVICE SELECTED**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔹 **Service ID:** `{sid}`\n"
        f"🔹 **Price:** `${rate}` per 1000\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 **Please enter the target Link:**\n(e.g., Profile link, Post link)"
    )
    msg = bot.send_message(call.message.chat.id, txt, parse_mode="Markdown")
    bot.register_next_step_handler(msg, get_link, sid, rate)

def get_link(message, sid, rate):
    link = message.text
    msg = bot.send_message(message.chat.id, "🔢 **Enter Quantity:**\n(Example: 1000)")
    bot.register_next_step_handler(msg, confirm_order, sid, rate, link)

def confirm_order(message, sid, rate, link):
    try:
        qty = int(message.text)
        cost = round((float(rate) / 1000) * qty, 4)
        user = users_col.find_one({"_id": message.chat.id})
        
        if user['balance'] < cost:
            bot.send_message(message.chat.id, f"❌ **Insufficient Balance!**\nRequired: `${cost}`\nAvailable: `${round(user['balance'],4)}`\n\nPlease Deposit first.", parse_mode="Markdown")
            return

        # Place Order via API
        msg = bot.send_message(message.chat.id, "⏳ **Processing Order...**")
        res = api.place_order(sid, link, qty)
        
        if 'order' in res:
            # Deduct balance and log order
            users_col.update_one({"_id": message.chat.id}, {"$inc": {"balance": -cost, "spent": cost}})
            orders_col.insert_one({
                "oid": res['order'], "uid": message.chat.id, "sid": sid, 
                "cost": cost, "status": "pending", "date": datetime.now()
            })
            
            success_txt = (
                f"✅ **ORDER SUCCESSFUL!**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 **Order ID:** `{res['order']}`\n"
                f"📦 **Service ID:** `{sid}`\n"
                f"🔢 **Quantity:** `{qty}`\n"
                f"💰 **Total Cost:** `${cost}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Track from '📦 Orders' menu."
            )
            bot.edit_message_text(success_txt, message.chat.id, msg.message_id, parse_mode="Markdown")
            
            # Admin notification
            try: bot.send_message(ADMIN_ID, f"🔔 **New Order!**\nUser: {user['name']} (`{message.chat.id}`)\nCost: `${cost}`\nProfit: Yes")
            except: pass
        else:
            bot.edit_message_text(f"❌ **Order Failed:** {res.get('error', 'Unknown Error from Panel')}", message.chat.id, msg.message_id)
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ **Invalid Input!** Quantity must be a number.")
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ **System Error:** {e}")

# ==========================================
# ৫. ডিপোজিট এবং সাপোর্ট
# ==========================================
@bot.message_handler(func=lambda m: m.text == "💰 Deposit")
def deposit(message):
    txt = (
        f"💰 **ADD FUNDS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 **Exchange Rate:** $1 = {EXCHANGE_RATE} BDT\n"
        f"🏦 **bKash/Nagad:** `{PAYMENT_NUMBER}` (Send Money)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Send the money, then click the button below to submit your TrxID."
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 Submit Transaction ID", callback_data="TRX"))
    bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "TRX")
def trx_in(call):
    msg = bot.send_message(call.message.chat.id, "✍️ **Enter your TrxID and Amount (BDT):**\nExample: `TXNJ3HD8D 500`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_trx)

def process_trx(message):
    try:
        bot.send_message(ADMIN_ID, f"🔔 **DEPOSIT REQUEST!**\n━━━━━━━━━━━━\nUser: `{message.chat.id}`\nName: {message.from_user.first_name}\nDetails: `{message.text}`", parse_mode="Markdown")
        bot.send_message(message.chat.id, "✅ **Request Submitted!**\nAdmin will verify and add funds shortly.")
    except:
        bot.send_message(message.chat.id, "⚠️ Could not notify admin. Please contact support.")

@bot.message_handler(func=lambda m: m.text == "🎧 Support")
def support(message):
    bot.send_message(message.chat.id, f"🎧 **CUSTOMER SUPPORT**\n━━━━━━━━━━━━━━━━━━━━\nNeed help? Contact our Admin directly:\n👉 {SUPPORT_USER}")
