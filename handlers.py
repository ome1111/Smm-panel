from telebot import types
from loader import bot, users_col, orders_col, config_col, tickets_col
from config import *
import api
import math
import time
from datetime import datetime, timedelta

# ==========================================
# ১. Core Settings & Cache System
# ==========================================
API_CACHE = {'data': [], 'last_fetch': 0}
CACHE_TTL = 300 

def get_settings():
    s = config_col.find_one({"_id": "settings"})
    if not s:
        s = {"_id": "settings", "channels": [], "profit_margin": 20.0, "maintenance": False, 
             "payments": [], "ref_target": 10, "ref_bonus": 5.0, "dep_commission": 5.0, "hidden_services": []}
        config_col.insert_one(s)
    return s

def check_maintenance(chat_id):
    settings = get_settings()
    if settings.get('maintenance', False) and str(chat_id) != str(ADMIN_ID):
        bot.send_message(chat_id, "🛠 **SYSTEM MAINTENANCE**\n━━━━━━━━━━━━━━━━━━━━\nThe bot is currently being upgraded. Please try again later.", parse_mode="Markdown")
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
# ২. Titan Features (VIP & Link Validator)
# ==========================================
def get_user_tier(spent):
    if spent >= 50: return "🥇 Gold VIP", 5 
    elif spent >= 10: return "🥈 Silver VIP", 2 
    else: return "🥉 Bronze", 0

def validate_link(platform, link):
    p = platform.lower()
    l = link.lower()
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
# ৩. UI Helpers & Force Sub
# ==========================================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🚀 New Order", "⭐ Favorites")
    markup.add("🔍 Smart Search", "📦 Orders")
    markup.add("💰 Deposit", "🤝 Affiliate")
    markup.add("👤 Profile", "🏆 Leaderboard")
    markup.add("🎧 Support Ticket")
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
    for ch in channels: 
        markup.add(types.InlineKeyboardButton(f"📢 Join {ch}", url=f"https://t.me/{ch.replace('@','')}"))
    markup.add(types.InlineKeyboardButton("🟢 VERIFY ACCOUNT 🟢", callback_data="CHECK_SUB"))
    txt = "🛑 **ACCESS RESTRICTED**\n━━━━━━━━━━━━━━━━━━━━\nJoin our official channels to unlock premium features.\n\n📌 **Step 1:** Join channels.\n📌 **Step 2:** Click Verify.\n━━━━━━━━━━━━━━━━━━━━"
    bot.send_message(chat_id, txt, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CHECK_SUB")
def sub_check_callback(call):
    if check_sub(call.message.chat.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        u = users_col.find_one({"_id": call.message.chat.id})
        
        # Smart Referral Logic
        if u and u.get('ref_by') and not u.get('ref_paid', True):
            users_col.update_one({"_id": call.message.chat.id}, {"$set": {"ref_paid": True}})
            referrer = u['ref_by']
            users_col.update_one({"_id": referrer}, {"$inc": {"balance": REF_BONUS}})
            try: bot.send_message(referrer, f"🎊 **New Referral Verified!** You earned **${REF_BONUS}**!")
            except: pass
            
            # Milestone Bonus Check
            settings = get_settings()
            ref_count = users_col.count_documents({"ref_by": referrer, "ref_paid": True})
            target = settings.get("ref_target", 10)
            bonus = settings.get("ref_bonus", 5.0)
            if ref_count > 0 and ref_count % target == 0:
                users_col.update_one({"_id": referrer}, {"$inc": {"balance": bonus}})
                try: bot.send_message(referrer, f"🏆 **MILESTONE REACHED!**\nYou invited {ref_count} active users and got an extra **${bonus}** bonus!")
                except: pass

        bot.send_message(call.message.chat.id, "✅ **Access Granted! Welcome.**", reply_markup=main_menu())
        txt = f"👋 **WELCOME TO NEXUS SMM**\n━━━━━━━━━━━━━━━━━━━━\n💠 **Elite Services at Best Rates**\n✨ **Fastest Delivery Guarantee**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **USER ID:** `{call.message.chat.id}`"
        bot.send_message(call.message.chat.id, txt, reply_markup=main_menu(), parse_mode="Markdown")
    else: 
        bot.answer_callback_query(call.id, "❌ Verification Failed! Please join ALL channels first.", show_alert=True)

# ==========================================
# ৪. Start Command
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    if check_maintenance(message.chat.id): return
    uid = message.chat.id
    name = message.from_user.first_name
    args = message.text.split()
    referrer = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid else None

    if not users_col.find_one({"_id": uid}):
        users_col.insert_one({
            "_id": uid, "name": name, "balance": 0.0, "spent": 0.0, 
            "ref_by": referrer, "ref_paid": False, "ref_earnings": 0.0, 
            "joined": datetime.now(), "favorites": []
        })

    if not check_sub(uid): return send_force_sub(uid)

    txt = f"👋 **WELCOME TO NEXUS SMM**\n━━━━━━━━━━━━━━━━━━━━\n💠 **Elite Services at Best Rates**\n✨ **Fastest Delivery Guarantee**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **USER ID:** `{uid}`"
    bot.send_message(uid, txt, reply_markup=main_menu(), parse_mode="Markdown")

# ==========================================
# ৫. Category & Service Routing
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def show_platforms(message):
    if check_maintenance(message.chat.id): return
    if not check_sub(message.chat.id): return send_force_sub(message.chat.id)
    
    services = get_cached_services()
    if not services: return bot.send_message(message.chat.id, "❌ API Error. Try again later.")

    hidden = get_settings().get("hidden_services", [])
    platforms = set(identify_platform(s['category']) for s in services if str(s['service']) not in hidden)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btns = [types.InlineKeyboardButton(text=p, callback_data=f"PLAT|{p}|0") for p in sorted(platforms)]
    
    for i in range(0, len(btns), 2):
        if i+1 < len(btns): markup.row(btns[i], btns[i+1])
        else: markup.row(btns[i])
        
    bot.send_message(message.chat.id, "🟢 **Live API Status:** Active\n━━━━━━━━━━━━━━━━━━━━\n📂 **Select a Platform:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PLAT|"))
def show_categories(call):
    if check_maintenance(call.message.chat.id): return
    if not check_sub(call.message.chat.id): return send_force_sub(call.message.chat.id)
    
    data = call.data.split("|")
    platform_name = data[1]
    page = int(data[2]) if len(data) > 2 else 0
    hidden = get_settings().get("hidden_services", [])
    
    all_cats = sorted(list(set(s['category'] for s in get_cached_services() if str(s['service']) not in hidden)))
    plat_cats = [c for c in all_cats if identify_platform(c) == platform_name]
    
    start = page * 15
    end = start + 15
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
    bot.edit_message_text(f"📍 **Menu ➡️ {platform_name}**\nPage: {page+1}/{math.ceil(len(plat_cats)/15)}\n━━━━━━━━━━━━━━━━━━━━\n📂 **Select a Category:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "BACK_TO_PLAT")
def back_to_plat(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    show_platforms(call.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("CAT|"))
def list_services(call):
    data = call.data.split("|")
    cat_idx = int(data[1])
    page = int(data[2])
    
    settings = get_settings()
    services = get_cached_services()
    hidden = settings.get("hidden_services", [])
    
    all_cats = sorted(list(set(s['category'] for s in services if str(s['service']) not in hidden)))
    if cat_idx >= len(all_cats): return
    cat_name = all_cats[cat_idx]
    
    filtered = [s for s in services if s['category'] == cat_name and str(s['service']) not in hidden]
    start = page * 10
    end = start + 10
    
    user = users_col.find_one({"_id": call.message.chat.id})
    _, discount = get_user_tier(user.get('spent', 0))
    global_profit = settings.get("profit_margin", 20.0)
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in filtered[start:end]:
        base_rate = float(s['rate']) + (float(s['rate']) * global_profit / 100)
        final_rate = round(base_rate - (base_rate * discount / 100), 3)
        speed = "⏱ Fast" if "fast" in s['name'].lower() or "instant" in s['name'].lower() else "⏱ Normal"
        markup.add(types.InlineKeyboardButton(f"⚡ ID:{s['service']} | ${final_rate} | {speed} | {s['name'][:20]}", callback_data=f"INFO|{s['service']}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CAT|{cat_idx}|{page-1}"))
    if end < len(filtered): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CAT|{cat_idx}|{page+1}"))
    if nav: markup.row(*nav)
    
    platform_name = identify_platform(cat_name)
    markup.add(types.InlineKeyboardButton(f"🔙 Back to {platform_name}", callback_data=f"PLAT|{platform_name}|0"))
    bot.edit_message_text(f"📍 **{platform_name} ➡️ Category**\n📦 **{cat_name[:30]}...**\nPage: {page+1}/{math.ceil(len(filtered)/10)}", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

# ==========================================
# ৬. Info Card & Ordering
# ==========================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|"))
def show_service_info(call):
    sid = call.data.split("|")[1]
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    
    if not s: return bot.answer_callback_query(call.id, "❌ Service not found or hidden by Admin!", show_alert=True)
        
    user = users_col.find_one({"_id": call.message.chat.id})
    tier_name, discount = get_user_tier(user.get('spent', 0))
    settings = get_settings()
    global_profit = settings.get("profit_margin", 20.0)
    
    base_rate = float(s['rate']) + (float(s['rate']) * global_profit / 100)
    final_rate = round(base_rate - (base_rate * discount / 100), 3)
    avg_speed = "1-6 Hours" if "hours" not in str(s.get('type','')).lower() else "Instant/Fast"
    
    txt = (
        f"ℹ️ **SERVICE INFORMATION**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 **Name:** {s['name']}\n"
        f"🆔 **ID:** `{sid}`\n"
        f"💰 **Your Price:** `${final_rate}` / 1000\n"
        f"⚡ **Avg Speed:** {avg_speed}\n"
        f"✨ **Your VIP Tier:** {tier_name} ({discount}% OFF)\n"
        f"📉 **Min:** {s['min']} | 📈 **Max:** {s['max']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ **Note:** Make sure the link/account is public."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🛒 Order Now", callback_data=f"START_ORD|{sid}"),
        types.InlineKeyboardButton("⭐ Fav", callback_data=f"FAV_ADD|{sid}")
    )
    
    all_cats = sorted(list(set(x['category'] for x in services if str(x['service']) not in settings.get("hidden_services", []))))
    try: cat_idx = all_cats.index(s['category'])
    except: cat_idx = 0
    markup.add(types.InlineKeyboardButton("🔙 Back to Services", callback_data=f"CAT|{cat_idx}|0"))
    
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("START_ORD|"))
def ask_link(call):
    sid = call.data.split("|")[1]
    msg = bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, ask_qty, sid)

def ask_qty(message, sid):
    link = message.text.strip()
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid)), None)
    
    # Smart Link Validator
    if s and not validate_link(identify_platform(s['category']), link):
        bot.send_message(message.chat.id, f"❌ **Link Warning!**\nIt looks like this link is not suitable for {identify_platform(s['category'])}. Please check and try again.", parse_mode="Markdown")
        return
        
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

        user = users_col.find_one({"_id": message.chat.id})
        _, discount = get_user_tier(user.get('spent', 0))
        global_profit = get_settings().get("profit_margin", 20.0)
        
        base_rate = float(s['rate']) + (float(s['rate']) * global_profit / 100)
        final_rate = base_rate - (base_rate * discount / 100)
        cost = round((final_rate / 1000) * qty, 3)
        
        if user['balance'] < cost:
            return bot.send_message(message.chat.id, f"❌ **Insufficient Balance!**\nYou need `${cost}` but have `${round(user['balance'],3)}`.", parse_mode="Markdown")

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
        bot.send_message(message.chat.id, "⚠️ **Invalid Input!** Must be a number.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CONFIRM_ORDER")
def place_final_order(call):
    user = users_col.find_one({"_id": call.message.chat.id})
    draft = user.get('draft')
    
    if not draft: return bot.answer_callback_query(call.id, "❌ Session expired!", show_alert=True)
        
    bot.edit_message_text("⏳ **Placing order to main server...**", call.message.chat.id, call.message.message_id)
    res = api.place_order(draft['sid'], draft['link'], draft['qty'])
    
    if 'order' in res:
        users_col.update_one({"_id": call.message.chat.id}, {
            "$inc": {"balance": -draft['cost'], "spent": draft['cost']}, 
            "$unset": {"draft": ""}
        })
        orders_col.insert_one({
            "oid": res['order'], "uid": call.message.chat.id, "sid": draft['sid'], 
            "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], 
            "status": "pending", "date": datetime.now()
        })
        bot.edit_message_text(f"✅ **ORDER SUCCESSFUL!**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Order ID: `{res['order']}`\n💰 Deducted: `${draft['cost']}`\n📌 Track in '📦 Orders' menu.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        
        # Notify Admin
        try: bot.send_message(ADMIN_ID, f"🔔 **NEW ORDER PLACED!**\nUser: `{call.message.chat.id}`\nService ID: `{draft['sid']}`\nAmount: `${draft['cost']}`")
        except: pass
    else:
        bot.edit_message_text(f"❌ **Failed:** {res.get('error')}", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORDER")
def cancel_order(call):
    users_col.update_one({"_id": call.message.chat.id}, {"$unset": {"draft": ""}})
    bot.edit_message_text("🚫 **Order Cancelled.**", call.message.chat.id, call.message.message_id)

# ==========================================
# ৭. Affiliate Dashboard
# ==========================================
def show_affiliate_dashboard(chat_id):
    u = users_col.find_one({"_id": chat_id})
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={chat_id}"
    
    total_joined = users_col.count_documents({"ref_by": chat_id})
    active_deposits = users_col.count_documents({"ref_by": chat_id, "spent": {"$gt": 0}})
    earnings = round(u.get('ref_earnings', 0.0), 3)
    settings = get_settings()
    
    txt = (
        f"🤝 **AFFILIATE DASHBOARD**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 **Your Ref Link:**\n`{ref_link}`\n\n"
        f"👥 **Total Joined:** {total_joined} Users\n"
        f"💸 **Active/Deposited:** {active_deposits} Users\n"
        f"💰 **Total Earned:** `${earnings}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 **Commission:** {settings.get('dep_commission', 5.0)}% on deposits + ${settings.get('ref_bonus', 5.0)} Milestone Bonus!"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={ref_link}&text=Join%20the%20best%20SMM%20Panel!"))
    bot.send_message(chat_id, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

# ==========================================
# ৮. Universal Features (Orders Auto-Sync, Search, Profile)
# ==========================================
def fetch_orders_page(chat_id, page=0):
    all_orders = list(orders_col.find({"uid": chat_id}).sort("_id", -1))
    if not all_orders: return "📭 No orders found.", None
    
    start = page * 5
    end = start + 5
    page_orders = all_orders[start:end]
    txt = f"📦 **YOUR ORDERS (Page {page+1}/{math.ceil(len(all_orders)/5)})**\n━━━━━━━━━━━━━━━━━━━━\n"
    
    for o in page_orders:
        current_status = str(o.get('status', 'pending')).lower()
        
        # Auto-Sync Live Status
        if current_status in ['pending', 'processing', 'in progress']:
            try:
                res = api.get_order_status(o['oid'])
                if res and 'status' in res:
                    current_status = str(res['status']).lower()
                    orders_col.update_one({"oid": o['oid']}, {"$set": {"status": current_status}})
            except: pass
            
        status_text = f"✅ {current_status.upper()}" if current_status == 'completed' else f"❌ {current_status.upper()}" if current_status in ['canceled', 'refunded'] else f"⏳ {current_status.upper()}"
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
    page = int(call.data.split("|")[1])
    bot.answer_callback_query(call.id, "⏳ Syncing Live Status...")
    txt, markup = fetch_orders_page(call.message.chat.id, page)
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("FAV_ADD|"))
def add_to_favorites(call):
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$addToSet": {"favorites": sid}})
    bot.answer_callback_query(call.id, "⭐ Added to Favorites!", show_alert=True)

@bot.message_handler(func=lambda m: m.text in ["⭐ Favorites", "👤 Profile", "🏆 Leaderboard", "📦 Orders", "💰 Deposit", "🎧 Support Ticket", "🔍 Smart Search", "🤝 Affiliate"])
def universal_buttons(message):
    if check_maintenance(message.chat.id): return
    if not check_sub(message.chat.id): return send_force_sub(message.chat.id)
    
    if message.text == "🤝 Affiliate": 
        show_affiliate_dashboard(message.chat.id)
    
    elif message.text == "👤 Profile":
        u = users_col.find_one({"_id": message.chat.id})
        tier, _ = get_user_tier(u.get('spent', 0))
        bot.send_message(message.chat.id, f"👤 **PROFILE ACCOUNT**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **ID:** `{u['_id']}`\n💳 **Balance:** `${round(u.get('balance',0), 3)}`\n💸 **Total Spent:** `${round(u.get('spent',0), 3)}`\n👑 **VIP Tier:** {tier}\n━━━━━━━━━━━━━━━━━━━━", parse_mode="Markdown")
        
    elif message.text == "📦 Orders":
        bot.send_chat_action(message.chat.id, 'typing')
        txt, markup = fetch_orders_page(message.chat.id, 0)
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        
    elif message.text == "🔍 Smart Search":
        msg = bot.send_message(message.chat.id, "🔍 **Smart Search**\nEnter Service ID or Text (e.g. 'Facebook Like'):", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_smart_search)
        
    elif message.text == "💰 Deposit":
        payments = get_settings().get("payments", [])
        if not payments:
            return bot.send_message(message.chat.id, "❌ No payment methods available right now.", parse_mode="Markdown")
            
        txt = "💰 **DEPOSIT FUNDS**\n━━━━━━━━━━━━━━━━━━━━\n"
        for p in payments: 
            txt += f"🏦 **{p['name']}**\n👉 Details: `{p['details']}`\n💵 Rate: $1 = {p['rate']} BDT\n\n"
        txt += "━━━━━━━━━━━━━━━━━━━━\nSend money to the details above, then submit your TrxID."
        
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📤 Submit TrxID", callback_data="TRX"))
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")
        
    elif message.text == "🎧 Support Ticket":
        msg = bot.send_message(message.chat.id, "🎧 **Describe your issue clearly:**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_ticket)
        
    elif message.text == "🏆 Leaderboard":
        top = users_col.find().sort("spent", -1).limit(5)
        txt = "🏆 **TOP 5 SPENDERS**\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, u in enumerate(top): 
            tier, _ = get_user_tier(u.get('spent', 0))
            txt += f"{i+1}. {u['name']} - `${round(u.get('spent',0), 2)}` ({tier})\n"
        bot.send_message(message.chat.id, txt, parse_mode="Markdown")
        
    elif message.text == "⭐ Favorites":
        user = users_col.find_one({"_id": message.chat.id})
        favs = user.get("favorites", [])
        if not favs: return bot.send_message(message.chat.id, "📭 You have no favorite services.", parse_mode="Markdown")
        
        services = get_cached_services()
        _, discount = get_user_tier(user.get('spent', 0))
        global_profit = get_settings().get("profit_margin", 20.0)
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        for sid in favs:
            s = next((x for x in services if str(x['service']) == str(sid)), None)
            if s: 
                base = float(s['rate']) + (float(s['rate']) * global_profit / 100)
                final = round(base - (base * discount / 100), 3)
                markup.add(types.InlineKeyboardButton(f"⭐ ID:{s['service']} | ${final}", callback_data=f"INFO|{s['service']}"))
        bot.send_message(message.chat.id, "⭐ **Your Favorite Services:**", reply_markup=markup, parse_mode="Markdown")

# ==========================================
# ৯. Form Inputs (Search, Deposit, Tickets, Refill)
# ==========================================
def process_ticket(message):
    tickets_col.insert_one({"uid": message.chat.id, "msg": message.text, "status": "open", "date": datetime.now()})
    bot.send_message(message.chat.id, "✅ **Ticket Submitted!** Admin will reply to you soon.", parse_mode="Markdown")
    try: bot.send_message(ADMIN_ID, f"🔔 **NEW SUPPORT TICKET!**\nUser: `{message.chat.id}`\nMsg: {message.text}")
    except: pass

def process_smart_search(message):
    query = message.text.strip().lower()
    services = get_cached_services()
    hidden = get_settings().get("hidden_services", [])
    
    # Check by exact ID
    if query.isdigit():
        s = next((x for x in services if str(x['service']) == query and query not in hidden), None)
        if s: 
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("ℹ️ Order Now", callback_data=f"INFO|{query}"))
            return bot.send_message(message.chat.id, f"✅ **Service Found:**\n{s['name']}", reply_markup=markup, parse_mode="Markdown")
    
    # Check by Keyword
    results = [s for s in services if str(s['service']) not in hidden and (query in s['name'].lower() or query in s['category'].lower())][:10]
    if not results: return bot.send_message(message.chat.id, "❌ No related services found.", parse_mode="Markdown")
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in results: 
        markup.add(types.InlineKeyboardButton(f"⚡ ID:{s['service']} | {s['name'][:25]}", callback_data=f"INFO|{s['service']}"))
    bot.send_message(message.chat.id, f"🔍 **Top Results for '{query}':**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "TRX")
def trx_in(call): 
    msg = bot.send_message(call.message.chat.id, "✍️ **Enter TrxID & Amount (e.g. TX123 500 BDT):**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: [
        bot.send_message(m.chat.id, "✅ Request Submitted! Admin will verify soon.", parse_mode="Markdown"), 
        bot.send_message(ADMIN_ID, f"🔔 **DEPOSIT ALERT!**\nUser: `{m.chat.id}`\nMsg: {m.text}")
    ])

@bot.callback_query_handler(func=lambda c: c.data == "ASK_REFILL")
def ask_refill(call):
    msg = bot.send_message(call.message.chat.id, "🔄 **Enter the Order ID you want to refill:**\n(Note: Must be a refillable service)", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_refill)

def process_refill(message):
    oid = message.text.strip()
    bot.send_message(message.chat.id, f"✅ **Refill Requested for Order #{oid}.**\nAdmin will process it if the service has a refill guarantee.", parse_mode="Markdown")
    try: bot.send_message(ADMIN_ID, f"🔄 **REFILL REQUEST**\nUser: `{message.chat.id}`\nOrder ID: `{oid}`")
    except: pass
