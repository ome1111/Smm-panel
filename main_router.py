import re
import math
import random
import json
import threading
from datetime import datetime, timedelta
from telebot import types
from bson.objectid import ObjectId

# 🔥 redis_client ও providers_col ইম্পোর্ট করা হলো
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, providers_col, redis_client
from config import *
import api
from utils import *

# ==========================================
# 🔥 REDIS SESSION MANAGER (Super Fast)
# ==========================================
def get_user_session(uid):
    data = redis_client.get(f"session_{uid}")
    return json.loads(data) if data else {}

def update_user_session(uid, updates):
    session = get_user_session(uid)
    session.update(updates)
    redis_client.setex(f"session_{uid}", 3600, json.dumps(session))

def clear_user_session(uid):
    redis_client.delete(f"session_{uid}")

# ==========================================
# 3. FORCE SUB, REFERRAL & START LOGIC
# ==========================================
def process_new_user_bonuses(uid):
    user = get_cached_user(uid) 
    if not user: return
    s = get_settings()
    
    if s.get('welcome_bonus_active') and not user.get("welcome_paid"):
        w_bonus = float(s.get('welcome_bonus', 0.0))
        if w_bonus > 0:
            users_col.update_one({"_id": uid}, {"$inc": {"balance": w_bonus}, "$set": {"welcome_paid": True}})
            clear_cached_user(uid) 
            try: bot.send_message(uid, f"🎁 **WELCOME BONUS!**\nCongratulations! You received `${w_bonus}` just for verifying your account.", parse_mode="Markdown")
            except: pass
        else:
            users_col.update_one({"_id": uid}, {"$set": {"welcome_paid": True}})
            clear_cached_user(uid)
            
    if user.get("ref_by") and not user.get("ref_paid"):
        ref_bonus = float(s.get("ref_bonus", 0.0))
        users_col.update_one({"_id": uid}, {"$set": {"ref_paid": True}}) 
        clear_cached_user(uid)
        
        if ref_bonus > 0:
            users_col.update_one({"_id": user["ref_by"]}, {"$inc": {"balance": ref_bonus, "ref_earnings": ref_bonus}})
            clear_cached_user(user["ref_by"])
            try: bot.send_message(user["ref_by"], f"🎉 **REFERRAL SUCCESS!**\nUser `{uid}` joined the channel and verified! You earned `${ref_bonus}`!", parse_mode="Markdown")
            except: pass

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    user = get_cached_user(uid)
    args = message.text.split()
    referrer = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid else None

    if not user:
        users_col.insert_one({"_id": uid, "name": message.from_user.first_name, "balance": 0.0, "spent": 0.0, "points": 0, "currency": "BDT", "ref_by": referrer, "ref_paid": False, "ref_earnings": 0.0, "joined": datetime.now(), "favorites": [], "custom_discount": 0.0, "shadow_banned": False, "tier_override": None, "welcome_paid": False})
        user = users_col.find_one({"_id": uid})
        clear_cached_user(uid)
        
    users_col.update_one({"_id": uid}, {"$set": {"last_active": datetime.now()}})
    clear_user_session(uid)
    
    if check_spam(uid) or check_maintenance(uid): return
    
    hour = datetime.now().hour
    greeting = "🌅 Good Morning" if hour < 12 else "☀️ Good Afternoon" if hour < 18 else "🌙 Good Evening"
    
    if not check_sub(uid):
        markup = types.InlineKeyboardMarkup()
        for ch in get_settings().get("channels", []): markup.add(types.InlineKeyboardButton(f"📢 Join Channel", url=f"https://t.me/{ch.replace('@','')}"))
        markup.add(types.InlineKeyboardButton("🟢 VERIFY ACCOUNT 🟢", callback_data="CHECK_SUB"))
        return bot.send_message(uid, "🛑 **ACCESS RESTRICTED**\nYou must join our official channels to unlock the bot.", reply_markup=markup, parse_mode="Markdown")

    process_new_user_bonuses(uid)

    welcome_text = f"""{greeting}, {message.from_user.first_name}! ⚡️

🚀 **𝗪𝗘𝗟𝗖𝗢𝗠𝗘 𝗧𝗢 𝗡𝗘𝗫𝗨𝗦 𝗦𝗠𝗠**
_"Your Ultimate Social Growth Engine"_
━━━━━━━━━━━━━━━━━━━━━
👤 **𝗨𝘀𝗲𝗿:** {message.from_user.first_name}
🆔 **𝗦𝘆𝘀𝘁𝗲𝗺 𝗜𝗗:** `{uid}`
👑 **𝗦𝘁𝗮𝘁𝘂𝘀:** Connected 🟢
💡 _Pro Tip: Paste any profile/post link directly here to Quick-Order!_
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
        process_new_user_bonuses(uid)
    else: bot.send_message(uid, "❌ You haven't joined all channels.")

# ==========================================
# 4. ORDERING ENGINE (🔥 DYNAMIC MENUS & 1XPANEL FIXED)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def new_order_start(message):
    uid = message.chat.id
    clear_user_session(uid)
    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    best_sids = get_settings().get("best_choice_sids", [])
    if best_sids: markup.add(types.InlineKeyboardButton("🌟 ADMIN BEST CHOICE 🌟", callback_data="SHOW_BEST_CHOICE|0"))

    # 🔥 ১. প্রথমে Custom Menus দেখাবে (যদি থাকে)
    custom_menus_doc = config_col.find_one({"_id": "custom_menus"})
    custom_menus = custom_menus_doc.get("menus", []) if custom_menus_doc else []

    if custom_menus:
        for menu in custom_menus:
            markup.add(types.InlineKeyboardButton(f"🚀 {menu['name']}", callback_data=f"CUSTOM_MENU|{menu['id']}"))

    # 🔥 ২. এরপর 1xPanel (Main Panel) এর অটোমেটিক ক্যাটাগরিগুলো দেখাবে
    services = get_cached_services()
    if not services and not custom_menus: 
        return bot.send_message(uid, "⏳ **API Syncing...** Try again in 5 seconds.")
        
    if services:
        hidden = get_settings().get("hidden_services", [])
        platforms = sorted(list(set(identify_platform(s['category']) for s in services if str(s['service']) not in hidden)))
        for p in platforms: 
            markup.add(types.InlineKeyboardButton(p, callback_data=f"PLAT|{p}|0"))
            
    bot.send_message(uid, "📂 **Select a Service Category:**\n_💡 Pro Tip: Just paste any link in the chat to auto-detect platform!_", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("CUSTOM_MENU|"))
def show_custom_menu_services(call):
    bot.answer_callback_query(call.id)
    menu_id = call.data.split("|")[1]
    
    custom_menus_doc = config_col.find_one({"_id": "custom_menus"})
    menus = custom_menus_doc.get("menus", []) if custom_menus_doc else []
    selected_menu = next((m for m in menus if m['id'] == menu_id), None)
    
    if not selected_menu: return bot.send_message(call.message.chat.id, "❌ Menu not found or deleted by admin.")
    
    services = get_cached_services()
    user = get_cached_user(call.message.chat.id)
    curr = user.get("currency", "BDT")
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for srv in selected_menu.get("services", []):
        actual_srv = next((x for x in services if str(x['service']) == str(srv['service_id']) and str(x.get('provider_id', 'MAIN')) == str(srv['provider_id'])), None)
        
        if actual_srv:
            if srv.get('custom_rate') and float(srv['custom_rate']) > 0:
                rate = calculate_price(float(srv['custom_rate']), user.get('spent',0), user.get('custom_discount', 0), 0)
            else:
                rate = calculate_price(actual_srv['rate'], user.get('spent',0), user.get('custom_discount', 0), actual_srv.get('provider_margin', 0.0))
                
            markup.add(types.InlineKeyboardButton(f"⚡ {fmt_curr(rate, curr)} | {srv['custom_name']}", callback_data=f"INFO|{srv['service_id']}|{srv['provider_id']}"))

    markup.add(types.InlineKeyboardButton("🔙 Back to Menu", callback_data="NEW_ORDER_BACK"))
    bot.edit_message_text(f"🚀 **{selected_menu['name']}**\n━━━━━━━━━━━━━━━━━━━━\nSelect a Service:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("SHOW_BEST_CHOICE"))
def show_best_choices(call):
    bot.answer_callback_query(call.id)
    parts = call.data.split("|")
    page = int(parts[1]) if len(parts) > 1 else 0
    
    services = get_cached_services()
    best_sids = get_settings().get("best_choice_sids", [])
    user = get_cached_user(call.message.chat.id)
    curr = user.get("currency", "BDT")
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    start_idx, end_idx = page * 10, page * 10 + 10
    
    for tsid in best_sids[start_idx:end_idx]:
        srv = next((x for x in services if str(x['service']) == str(tsid).strip()), None)
        if srv:
            rate = calculate_price(srv['rate'], user.get('spent', 0), user.get('custom_discount', 0), srv.get('provider_margin', 0.0))
            markup.add(types.InlineKeyboardButton(f"ID:{srv['service']} | {fmt_curr(rate, curr)} | {clean_service_name(srv['name'])}", callback_data=f"INFO|{tsid}|{srv.get('provider_id','MAIN')}"))
            
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"SHOW_BEST_CHOICE|{page-1}"))
    if end_idx < len(best_sids): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"SHOW_BEST_CHOICE|{page+1}"))
    if nav: markup.row(*nav)
    
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
    markup.add(types.InlineKeyboardButton("🔙 Main Menu", callback_data="NEW_ORDER_BACK"))
    bot.edit_message_text(f"📍 **{platform}**\n━━━━━━━━━━━━━━━━━━━━\n📂 **Choose Category:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("CAT|"))
def list_servs(call):
    _, cat_idx, page = call.data.split("|")
    services = get_cached_services()
    cat_name = sorted(list(set(s['category'] for s in services)))[int(cat_idx)]
    hidden = get_settings().get("hidden_services", [])
    filtered = [s for s in services if s['category'] == cat_name and str(s['service']) not in hidden]
    start_idx, end_idx = int(page) * 10, int(page) * 10 + 10
    
    user = get_cached_user(call.message.chat.id)
    curr = user.get("currency", "BDT")
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in filtered[start_idx:end_idx]:
        rate = calculate_price(s['rate'], user.get('spent',0), user.get('custom_discount', 0), s.get('provider_margin', 0.0))
        markup.add(types.InlineKeyboardButton(f"ID:{s['service']} | {fmt_curr(rate, curr)} | {clean_service_name(s['name'])}", callback_data=f"INFO|{s['service']}|{s.get('provider_id','MAIN')}"))
    
    nav = []
    if int(page) > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CAT|{cat_idx}|{int(page)-1}"))
    if end_idx < len(filtered): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CAT|{cat_idx}|{int(page)+1}"))
    if nav: markup.row(*nav)
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"PLAT|{identify_platform(cat_name)}|0"))
    try: bot.edit_message_text(f"📦 **{cat_name[:30]}**\n━━━━━━━━━━━━━━━━━━━━\nSelect Service:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except: bot.send_message(call.message.chat.id, f"📦 **{cat_name[:30]}**\n━━━━━━━━━━━━━━━━━━━━\nSelect Service:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|"))
def info_card(call):
    parts = call.data.split("|")
    sid = parts[1]
    provider_id = parts[2] if len(parts) > 2 else "MAIN"
    
    services = get_cached_services()
    s = next((x for x in services if str(x['service']) == str(sid) and str(x.get('provider_id', 'MAIN')) == provider_id), None)
    if not s:
        s = next((x for x in services if str(x['service']) == str(sid)), None)
        
    if not s: return bot.send_message(call.message.chat.id, "❌ Service unavailable.")
    
    user = get_cached_user(call.message.chat.id)
    curr = user.get("currency", "BDT")
    
    rate = calculate_price(s['rate'], user.get('spent',0), user.get('custom_discount', 0), s.get('provider_margin', 0.0))
    avg_time = s.get('time', 'Instant - 24h') if s.get('time') != "" else 'Instant - 24h'

    display_name = clean_service_name(s['name'])
    custom_menus_doc = config_col.find_one({"_id": "custom_menus"})
    if custom_menus_doc:
        for menu in custom_menus_doc.get("menus", []):
            for srv_map in menu.get("services", []):
                if str(srv_map.get('service_id')) == str(sid) and str(srv_map.get('provider_id')) == provider_id:
                    display_name = srv_map.get('custom_name', display_name)
                    if srv_map.get('custom_rate'): rate = calculate_price(float(srv_map['custom_rate']), user.get('spent',0), user.get('custom_discount', 0), 0)

    txt = (f"ℹ️ **SERVICE DETAILS**\n━━━━━━━━━━━━━━━━━━━━\n🏷 **Name:** {display_name}\n🆔 **ID:** `{sid}`\n"
           f"💰 **Price:** `{fmt_curr(rate, curr)}` / 1000\n📉 **Min:** {s.get('min','0')} | 📈 **Max:** {s.get('max','0')}\n"
           f"⏱ **Live Avg Time:** `{avg_time}`⚡️\n━━━━━━━━━━━━━━━━━━━━")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🚀 Normal Order", callback_data=f"TYPE|{sid}|normal|{provider_id}"))
    if str(s.get('dripfeed', 'False')).lower() == 'true':
        markup.add(types.InlineKeyboardButton("💧 Drip-Feed", callback_data=f"TYPE|{sid}|drip|{provider_id}"))
    markup.add(types.InlineKeyboardButton("🔄 Auto-Subscription", callback_data=f"TYPE|{sid}|sub|{provider_id}"))
    
    markup.add(types.InlineKeyboardButton("⭐ Fav", callback_data=f"FAV_ADD|{sid}"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Menus", callback_data="NEW_ORDER_BACK"))
    
    if call.message.text and ("YOUR ORDERS" in call.message.text or "Found:" in call.message.text or "Top Results:" in call.message.text): 
        bot.send_message(call.message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")
    else: 
        bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("TYPE|"))
def order_type_router(call):
    parts = call.data.split("|")
    sid = parts[1]
    o_type = parts[2]
    provider_id = parts[3] if len(parts) > 3 else "MAIN"
    
    session = get_user_session(call.message.chat.id)
    magic_link = session.get("temp_link", "")
    
    if o_type == "normal":
        if magic_link:
            update_user_session(call.message.chat.id, {"step": "awaiting_qty", "temp_sid": sid, "order_type": "normal", "temp_pid": provider_id})
            bot.send_message(call.message.chat.id, f"🎯 **Link Detected:** {magic_link}\n🔢 **Enter Quantity (Numbers only):**", parse_mode="Markdown")
        else:
            update_user_session(call.message.chat.id, {"step": "awaiting_link", "temp_sid": sid, "order_type": "normal", "temp_pid": provider_id})
            bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**\n_(Example: https://t.me/yourchannel)_", parse_mode="Markdown")
            
    elif o_type == "drip":
        update_user_session(call.message.chat.id, {"step": "awaiting_link", "temp_sid": sid, "order_type": "drip", "temp_pid": provider_id})
        bot.send_message(call.message.chat.id, "💧 **DRIP-FEED ORDER**\n🔗 **Paste the Target Link:**", parse_mode="Markdown")
        
    elif o_type == "sub":
        update_user_session(call.message.chat.id, {"step": "awaiting_sub_user", "temp_sid": sid, "order_type": "sub", "temp_pid": provider_id})
        bot.send_message(call.message.chat.id, "🔄 **AUTO-SUBSCRIPTION WIZARD**\n👤 **Enter Target Username:**\n_(e.g., @cristiano or cristiano)_", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ORD|"))
def start_ord(call):
    sid = call.data.split("|")[1]
    update_user_session(call.message.chat.id, {"step": "awaiting_link", "temp_sid": sid, "order_type": "normal", "temp_pid": "MAIN"})
    bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**\n_(Example: https://t.me/yourchannel)_", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("REORDER|"))
def reorder_callback(call):
    sid = call.data.split("|")[1]
    update_user_session(call.message.chat.id, {"step": "awaiting_link", "temp_sid": sid, "order_type": "normal", "temp_pid": "MAIN"})
    bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link for Reorder:**\n_(Example: https://t.me/yourchannel)_", parse_mode="Markdown")

# ==========================================
# 5. UNIVERSAL BUTTONS & PROFILE
# ==========================================
def fetch_orders_page(chat_id, page=0, filter_type="all"):
    user = get_cached_user(chat_id)
    curr = user.get("currency", "BDT") if user else "BDT"
    
    query = {"uid": chat_id}
    if filter_type == "subs": query["is_sub"] = True
    
    all_orders = list(orders_col.find(query).sort("_id", -1))
    if not all_orders: return "📭 No orders found." if filter_type == "all" else "📭 No active subscriptions found.", None
    
    start, end = page * 3, page * 3 + 3
    page_orders = all_orders[start:end]
    title = "📦 **YOUR ORDERS**" if filter_type == "all" else "🔄 **ACTIVE SUBSCRIPTIONS**"
    txt = f"{title} (Page {page+1}/{math.ceil(len(all_orders)/3)})\n━━━━━━━━━━━━━━━━━━━━\n"
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if filter_type == "all":
        markup.add(types.InlineKeyboardButton("🔄 View Active Subs", callback_data="MYORD|0|subs"))
        
    for o in page_orders:
        st = str(o.get('status', 'pending')).lower()
        st_emoji = "⏳"
        if st == "completed": st_emoji = "✅"
        elif st in ["canceled", "refunded", "fail"]: st_emoji = "❌"
        elif st in ["in progress", "processing"]: st_emoji = "🔄"
        elif st == "partial": st_emoji = "⚠️"
        
        remains = o.get('remains', o.get('qty', 0))
        qty = o.get('qty', 0)
        p_bar, delivered = generate_progress_bar(remains, qty)
        
        txt += f"🆔 `{o['oid']}` | 💰 `{fmt_curr(o['cost'], curr)}`\n"
        if o.get("is_sub"):
            txt += f"👤 Target: {str(o.get('username', 'N/A'))}\n"
            txt += f"📸 Posts: {o.get('posts', 0)} | Qty/Post: {qty}\n"
        else:
            txt += f"🔗 {str(o.get('link', 'N/A'))[:25]}...\n"
            
        txt += f"🏷 Status: {st_emoji} {st.upper()}\n"
        if st in ['in progress', 'processing', 'pending'] and not o.get("is_sub"):
            txt += f"📊 Progress: `{p_bar}`\n✅ Delivered: {delivered} / {qty}\n"
        txt += "\n"
        
        row_btns = [types.InlineKeyboardButton(f"🔁 Reorder", callback_data=f"REORDER|{o.get('sid', 0)}")]
        if st in ['completed', 'partial'] and not o.get("is_shadow") and not o.get("is_sub"):
            row_btns.append(types.InlineKeyboardButton(f"🔄 Refill", callback_data=f"INSTANT_REFILL|{o['oid']}"))
        markup.row(*row_btns)
            
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"MYORD|{page-1}|{filter_type}"))
    if end < len(all_orders): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"MYORD|{page+1}|{filter_type}"))
    if filter_type == "subs": nav.append(types.InlineKeyboardButton("🔙 All Orders", callback_data="MYORD|0|all"))
    if nav: markup.row(*nav)
    return txt, markup

@bot.callback_query_handler(func=lambda c: c.data.startswith("INSTANT_REFILL|"))
def process_instant_refill(call):
    oid = call.data.split("|")[1]
    try:
        if str(oid).isdigit(): oid_val = int(oid)
        else: oid_val = oid
        o = orders_col.find_one({"oid": oid_val})
        
        api_url, api_key = API_URL, API_KEY
        if o and o.get("provider_id") and o.get("provider_id") != "MAIN":
            provider = providers_col.find_one({"_id": ObjectId(o.get("provider_id"))})
            if provider:
                api_url = provider.get("api_url")
                api_key = provider.get("api_key")
                
        res = api.send_refill(api_url, api_key, oid)
        if res and 'refill' in res: bot.answer_callback_query(call.id, f"✅ Auto-Refill Triggered! Task ID: {res['refill']}", show_alert=True)
        else: bot.answer_callback_query(call.id, "❌ Refill not available or requested too early.", show_alert=True)
    except Exception:
        bot.answer_callback_query(call.id, "❌ Error connecting to provider API.", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("MYORD|"))
def my_orders_pagination(call):
    parts = call.data.split("|")
    page = int(parts[1])
    filter_type = parts[2] if len(parts) > 2 else "all"
    txt, markup = fetch_orders_page(call.message.chat.id, page, filter_type)
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data == "REDEEM_POINTS")
def redeem_points(call):
    u = get_cached_user(call.message.chat.id)
    pts = u.get("points", 0)
    s = get_settings()
    rate = s.get("points_to_usd_rate", 1000)
    if pts < rate: return bot.answer_callback_query(call.id, f"❌ Minimum {rate} Points required to redeem.", show_alert=True)
    reward = pts / float(rate)
    users_col.update_one({"_id": call.message.chat.id}, {"$inc": {"balance": reward}, "$set": {"points": 0}})
    clear_cached_user(call.message.chat.id)
    bot.answer_callback_query(call.id, f"✅ Redeemed {pts} Points for ${reward:.2f}!", show_alert=True)
    bot.delete_message(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("FAV_ADD|"))
def add_to_favorites(call):
    bot.answer_callback_query(call.id, "⭐ Added to Favorites!", show_alert=True)
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$addToSet": {"favorites": sid}})
    clear_cached_user(call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("SET_CURR|"))
def set_currency_callback(call):
    curr = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"currency": curr}})
    clear_cached_user(call.message.chat.id)
    bot.answer_callback_query(call.id, f"✅ Currency updated to {curr}")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    call.message.text = "👤 Profile"
    universal_buttons(call.message)

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
    
    update_user_session(call.message.chat.id, {"step": "awaiting_trx", "temp_dep_amt": amt_usd, "temp_dep_method": method})
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PAY_CRYPTO|"))
def pay_crypto_details(call):
    bot.answer_callback_query(call.id, "Generating secure payment link... Please wait.", show_alert=False)
    _, amt_usd, method = call.data.split("|")
    amt_usd = float(amt_usd)
    uid = call.message.chat.id
    s = get_settings()
    
    pay_url = None
    if method == "Cryptomus":
        order_id = f"{uid}_{random.randint(100000, 999999)}"
        pay_url = create_cryptomus_payment(amt_usd, order_id, s.get('cryptomus_merchant'), s.get('cryptomus_api'))
    elif method == "CoinPayments":
        pay_url = create_coinpayments_payment(amt_usd, uid, s.get('coinpayments_pub'), s.get('coinpayments_priv'))
        
    if pay_url:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"💳 PAY ${amt_usd:.2f} NOW", url=pay_url))
        txt = f"🔗 **{method} Secure Checkout**\n━━━━━━━━━━━━━━━━━━━━\n💵 **Amount to Send:** `${amt_usd:.2f}`\n\nClick the button below to complete your transaction on the secure gateway. Your balance will be added automatically once confirmed by the network!"
        bot.edit_message_text(txt, uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.edit_message_text(f"❌ Failed to generate {method} invoice. Please check API keys or contact Admin.", uid, call.message.message_id)

def universal_buttons(message):
    uid = message.chat.id
    clear_user_session(uid)
    
    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    u = get_cached_user(uid)
    curr = u.get("currency", "BDT") if u else "BDT"

    if message.text == "📦 Orders":
        txt, markup = fetch_orders_page(uid, 0, "all")
        bot.send_message(uid, txt, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
    
    elif message.text == "💰 Deposit":
        update_user_session(uid, {"step": "awaiting_deposit_amt"})
        bot.send_message(uid, f"💵 **Enter Deposit Amount ({curr}):**\n_(e.g. 100)_", parse_mode="Markdown")
    
    elif message.text == "👤 Profile":
        tier = u.get('tier_override') if u.get('tier_override') else get_user_tier(u.get('spent', 0))[0]
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(types.InlineKeyboardButton("🟢 BDT", callback_data="SET_CURR|BDT"), types.InlineKeyboardButton("🟠 INR", callback_data="SET_CURR|INR"), types.InlineKeyboardButton("🔵 USD", callback_data="SET_CURR|USD"))
        markup.add(types.InlineKeyboardButton(f"🎁 Redeem Points ({u.get('points', 0)} pts)", callback_data="REDEEM_POINTS"))
        card = f"```text\n╔════════════════════════════════╗\n║  🌟 NEXUS VIP PASSPORT         ║\n╠════════════════════════════════╣\n║  👤 Name: {str(message.from_user.first_name)[:12].ljust(19)}║\n║  🆔 UID: {str(uid).ljust(20)}║\n║  💳 Balance: {fmt_curr(u.get('balance',0), curr).ljust(18)}║\n║  💸 Spent: {fmt_curr(u.get('spent',0), curr).ljust(20)}║\n║  🏆 Points: {str(u.get('points', 0)).ljust(19)}║\n║  👑 Tier: {tier.ljust(19)}║\n╚════════════════════════════════╝\n```"
        bot.send_message(uid, card, reply_markup=markup, parse_mode="Markdown")
        
    elif message.text == "🏆 Leaderboard":
        s = get_settings()
        r1, r2, r3 = s.get('reward_top1', 10.0), s.get('reward_top2', 5.0), s.get('reward_top3', 2.0)
        
        txt = "🏆 **NEXUS HALL OF FAME** 🏆\n━━━━━━━━━━━━━━━━━━━━\n"
        medals = ['🥇', '🥈', '🥉', '🏅', '🏅']
        
        txt += "💎 **TOP SPENDERS:**\n"
        top_spenders = list(users_col.find({"spent": {"$gt": 0}}).sort("spent", -1).limit(5))
        if not top_spenders: txt += "_No spenders yet!_\n"
        else:
            for i, tu in enumerate(top_spenders):
                rt = f" (+${[r1, r2, r3][i]})" if i < 3 else ""
                txt += f"{medals[i]} {tu.get('name', 'N/A')[:10]} - `{fmt_curr(tu.get('spent', 0), curr)}`{rt}\n"

        txt += "\n👥 **TOP AFFILIATES (By Earnings):**\n"
        top_refs = list(users_col.find({"ref_earnings": {"$gt": 0}}).sort("ref_earnings", -1).limit(5))
        if not top_refs: txt += "_No affiliates yet!_\n"
        else:
            for i, tu in enumerate(top_refs):
                txt += f"{medals[i]} {tu.get('name', 'N/A')[:10]} - `{fmt_curr(tu.get('ref_earnings', 0), curr)}`\n"

        bot.send_message(uid, txt + "\n_Be in the Top 3 to earn real wallet cash!_", parse_mode="Markdown")

    elif message.text == "⭐ Favorites":
        favs = u.get("favorites", [])
        if not favs: return bot.send_message(uid, "📭 **Your vault is empty!**\nAdd services to favorites to see them here.", parse_mode="Markdown")
        services = get_cached_services()
        markup = types.InlineKeyboardMarkup(row_width=1)
        for sid in favs:
            s = next((x for x in services if str(x['service']) == str(sid)), None)
            if s: markup.add(types.InlineKeyboardButton(f"⭐ ID:{s['service']} | {clean_service_name(s['name'])[:25]}", callback_data=f"INFO|{s['service']}|{s.get('provider_id','MAIN')}"))
        bot.send_message(uid, "⭐ **YOUR SAVED SERVICES:**", reply_markup=markup, parse_mode="Markdown")

    elif message.text == "🤝 Affiliate":
        ref_link = f"https://t.me/{bot.get_me().username}?start={uid}"
        s = get_settings()
        bot.send_message(uid, f"🤝 **AFFILIATE NETWORK**\n━━━━━━━━━━━━━━━━━━━━\n🔗 **Your Unique Link:**\n`{ref_link}`\n\n💰 **Monthly Earned:** `{fmt_curr(u.get('ref_earnings', 0.0), curr)}`\n👥 **Total Verified Invites:** `{users_col.count_documents({'ref_by': uid, 'ref_paid': True})}`\n\n_💡 Earn ${s.get('ref_bonus', 0.0)} instantly when they verify + {s.get('dep_commission', 0.0)}% lifetime commission!_", parse_mode="Markdown", disable_web_page_preview=True)

    elif message.text == "🎟️ Voucher":
        update_user_session(uid, {"step": "awaiting_voucher"})
        bot.send_message(uid, "🎁 **REDEEM VOUCHER**\nEnter your secret promo code below:", parse_mode="Markdown")

    elif message.text == "🔍 Smart Search":
        update_user_session(uid, {"step": "awaiting_search"})
        bot.send_message(uid, "🔍 **SMART SEARCH**\nEnter Service ID or Keyword (e.g., 'Instagram'):", parse_mode="Markdown")
        
    elif message.text == "💬 Live Chat":
        update_user_session(uid, {"step": "awaiting_ticket"})
        bot.send_message(uid, "💬 **LIVE SUPPORT**\nSend your message here. You can also send Screenshots or Photos! Our Admins will reply directly.", parse_mode="Markdown")
        
    elif message.text == "📝 Bulk Order":
        update_user_session(uid, {"step": "awaiting_bulk_order"})
        bot.send_message(uid, "📝 **BULK ORDER PROCESSING**\nSend your orders in this exact format (One order per line):\n`ServiceID | Link | Quantity`\n\n**Example:**\n`102 | https://ig.com/p/1 | 1000`\n`55 | https://fb.com/p/2 | 500`", parse_mode="Markdown")

def send_media_to_admin(msg_obj, admin_text):
    try:
        if msg_obj.photo: bot.send_photo(ADMIN_ID, msg_obj.photo[-1].file_id, caption=admin_text, parse_mode="Markdown")
        elif msg_obj.document: bot.send_document(ADMIN_ID, msg_obj.document.file_id, caption=admin_text, parse_mode="Markdown")
        else: bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
    except: pass

# ==========================================
# 7. MASTER ROUTER (Smart Errors & Ordering)
# ==========================================
@bot.message_handler(content_types=['text', 'photo', 'document'])
def universal_router(message):
    uid = message.chat.id
    text = message.text.strip() if message.text else message.caption.strip() if message.caption else "📸 [Media/Screenshot attached]"
    
    if text.startswith('/'): return
    
    if str(uid) == str(ADMIN_ID) and message.reply_to_message:
        reply_text = message.reply_to_message.text or message.reply_to_message.caption
        if reply_text and ("🆔 ID: " in reply_text or "ID: " in reply_text):
            try:
                if "🆔 ID: " in reply_text: target_uid = int(reply_text.split("🆔 ID: ")[1].split("\n")[0].strip().replace("`", ""))
                else: target_uid = int(reply_text.split("ID: ")[1].split("\n")[0].strip().replace("`", ""))
                    
                bot.send_message(target_uid, f"👨‍💻 **ADMIN REPLY:**\n━━━━━━━━━━━━━━━━━━━━\n{text}", parse_mode="Markdown")
                tickets_col.update_many({"uid": target_uid, "status": "open"}, {"$set": {"status": "closed", "reply": text}})
                return bot.send_message(ADMIN_ID, f"✅ Reply sent successfully to user `{target_uid}`!")
            except: pass

    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    if text in ["🚀 New Order", "⭐ Favorites", "🔍 Smart Search", "📦 Orders", "💰 Deposit", "📝 Bulk Order", "🤝 Affiliate", "👤 Profile", "🎟️ Voucher", "🏆 Leaderboard", "💬 Live Chat"]:
        return universal_buttons(message)

    u = get_cached_user(uid)
    session_data = get_user_session(uid)
    step = session_data.get("step", "")

    if step == "" and re.match(r'^(https?://|t\.me/|@|www\.)[^\s]+$', text, re.IGNORECASE):
        platform = detect_platform_from_link(text)
        if platform:
            services = get_cached_services()
            hidden = get_settings().get("hidden_services", [])
            cats = sorted(list(set(s['category'] for s in services if identify_platform(s['category']) == platform and str(s['service']) not in hidden)))
            if cats:
                update_user_session(uid, {"temp_link": text})
                markup = types.InlineKeyboardMarkup(row_width=1)
                for cat in cats[:15]:
                    idx = sorted(list(set(s['category'] for s in services))).index(cat)
                    markup.add(types.InlineKeyboardButton(f"📁 {cat[:35]}", callback_data=f"CAT|{idx}|0"))
                return bot.send_message(uid, f"✨ **Magic Link Detected!**\n📍 Platform: **{platform}**\n📂 Choose Category for your link:", reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

    # --- ADMIN STATES ---
    if str(uid) == str(ADMIN_ID):
        if step == "awaiting_ghost_uid":
            try: target = int(text)
            except: return bot.send_message(uid, "❌ ID must be numbers.")
            tu = get_cached_user(target)
            if not tu: return bot.send_message(uid, "❌ User not found.")
            clear_user_session(uid)
            return bot.send_message(uid, f"👻 **GHOST VIEW - UID: {target}**\nName: {tu.get('name')}\nBal: ${tu.get('balance', 0):.3f}\nSpent: ${tu.get('spent', 0):.3f}\nPoints: {tu.get('points', 0)}")
            
        elif step == "awaiting_alert_uid":
            try:
                target = int(text)
                update_user_session(uid, {"step": "awaiting_alert_msg", "temp_uid": target})
                return bot.send_message(uid, f"✍️ Enter alert msg for `{target}`:", parse_mode="Markdown")
            except: return bot.send_message(uid, "❌ Invalid ID.")
            
        elif step == "awaiting_alert_msg":
            target = session_data.get("temp_uid")
            clear_user_session(uid)
            try:
                bot.send_message(target, f"⚠️ **SYSTEM ALERT**\n━━━━━━━━━━━━━━━━━━━━\n{text}", parse_mode="Markdown")
                return bot.send_message(uid, "✅ Alert Sent!")
            except: return bot.send_message(uid, "❌ Failed to send.")
            
        elif step == "awaiting_wbonus":
            try:
                amt = float(text)
                status = amt > 0
                config_col.update_one({"_id": "settings"}, {"$set": {"welcome_bonus": amt, "welcome_bonus_active": status}})
                clear_user_session(uid)
                return bot.send_message(uid, f"✅ Welcome Bonus set to ${amt}. Status: {'ON' if status else 'OFF'}")
            except: return bot.send_message(uid, "❌ Invalid number.")
            
        elif step == "awaiting_fsale":
            try:
                disc = float(text)
                status = disc > 0
                config_col.update_one({"_id": "settings"}, {"$set": {"flash_sale_discount": disc, "flash_sale_active": status}})
                clear_user_session(uid)
                return bot.send_message(uid, f"✅ Flash Sale set to {disc}%. Status: {'ON' if status else 'OFF'}")
            except: return bot.send_message(uid, "❌ Invalid number.")
            
        elif step == "awaiting_best":
            try:
                sids = [int(x.strip()) for x in text.split(",") if x.strip().isdigit()]
                config_col.update_one({"_id": "settings"}, {"$set": {"best_choice_sids": sids}})
                clear_user_session(uid)
                return bot.send_message(uid, f"✅ Best Choice SIDs updated: {sids}")
            except: return bot.send_message(uid, "❌ Format error.")
            
        elif step == "awaiting_profit":
            try:
                v = float(text)
                config_col.update_one({"_id": "settings"}, {"$set": {"profit_margin": v}})
                clear_user_session(uid)
                return bot.send_message(uid, f"✅ Profit Margin: {v}%")
            except: return bot.send_message(uid, "❌ Invalid number.")
            
        elif step == "awaiting_bc":
            clear_user_session(uid)
            c = 0
            for usr in users_col.find({"is_fake": {"$ne": True}}):
                try: bot.send_message(usr["_id"], f"📢 **MESSAGE FROM ADMIN**\n━━━━━━━━━━━━━━━━━━━━\n{text}", parse_mode="Markdown"); c+=1
                except: pass
            return bot.send_message(uid, f"✅ Broadcast sent to `{c}` users!")

        elif step == "awaiting_points_cfg":
            try:
                p_usd, p_rate = text.split(",")
                config_col.update_one({"_id": "settings"}, {"$set": {"points_per_usd": int(p_usd.strip()), "points_to_usd_rate": int(p_rate.strip())}})
                clear_user_session(uid)
                return bot.send_message(uid, "✅ Points System Updated!")
            except: return bot.send_message(uid, "❌ Format error. Use comma (e.g. 100, 1000)")

    # --- AUTO PAYMENT CLAIM LOGIC ---
    if step == "awaiting_trx":
        method_name = str(session_data.get("temp_dep_method", "Manual")).lower()
        is_local_auto = any(x in method_name for x in ['bkash', 'nagad', 'rocket', 'upay', 'bdt'])

        if is_local_auto:
            user_trx = text.upper().strip()
            trx_data = config_col.find_one({"_id": "transactions", "valid_list.trx": user_trx})
            
            if not trx_data:
                return bot.send_message(uid, "❌ **INVALID TRX ID!**\nআপনার ট্রানজেকশন আইডিটি পাওয়া যায়নি। অনুগ্রহ করে সঠিক আইডি দিন।", parse_mode="Markdown")

            entry = next((x for x in trx_data['valid_list'] if x['trx'] == user_trx), None)
            if entry['status'] == "used":
                return bot.send_message(uid, "⚠️ **ALREADY USED!**\nএই ট্রানজেকশন আইডিটি ব্যবহার করা হয়ে গেছে।", parse_mode="Markdown")

            s = get_settings()
            bdt_rate = 120.0
            for p in s.get('payments', []):
                if any(x in p['name'].lower() for x in ['bkash', 'nagad', 'rocket', 'upay', 'bdt']):
                    bdt_rate = float(p.get('rate', 120.0))
                    break
                    
            usd_to_add = entry['amt'] / bdt_rate
            
            config_col.update_one({"_id": "transactions", "valid_list.trx": user_trx}, {"$set": {"valid_list.$.status": "used", "valid_list.$.user": uid}})
            users_col.update_one({"_id": uid}, {"$inc": {"balance": usd_to_add}})
            clear_cached_user(uid)
            clear_user_session(uid)
            
            if u and u.get("ref_by"):
                comm = usd_to_add * (float(s.get("dep_commission", 5.0)) / 100)
                if comm > 0:
                    users_col.update_one({"_id": u["ref_by"]}, {"$inc": {"balance": comm, "ref_earnings": comm}})
                    clear_cached_user(u["ref_by"])
                    try: bot.send_message(u["ref_by"], f"💸 **COMMISSION EARNED!**\nYour referral made an Auto Deposit. You earned `${comm:.3f}`!", parse_mode="Markdown")
                    except: pass
                    
            bot.send_message(uid, f"✅ **DEPOSIT SUCCESS!**\n💰 Amount: `{entry['amt']} TK`\n💵 Added: `${usd_to_add:.2f}`", parse_mode="Markdown")
            bot.send_message(ADMIN_ID, f"🔔 **AUTO DEP:** {uid} added ${usd_to_add:.2f} (TrxID: {user_trx})")
            return
            
        else:
            tid = text
            amt = session_data.get("temp_dep_amt", 0.0)
            clear_user_session(uid)
            bot.send_message(uid, "✅ **Request Submitted!**\nAdmin will verify your TrxID shortly.", parse_mode="Markdown")
            admin_txt = f"🔔 **NEW DEPOSIT (MANUAL)**\n👤 User: `{uid}`\n🏦 Method: **{session_data.get('temp_dep_method', 'Manual')}**\n💰 Amt: **${round(float(amt), 2)}**\n🧾 TrxID: `{tid}`"
            markup = types.InlineKeyboardMarkup(row_width=2)
            app_url = BASE_URL.rstrip('/')
            markup.add(types.InlineKeyboardButton("✅ APPROVE", url=f"{app_url}/approve_dep/{uid}/{amt}/{tid}"), types.InlineKeyboardButton("❌ REJECT", url=f"{app_url}/reject_dep/{uid}/{tid}"))
            try: bot.send_message(ADMIN_ID, admin_txt, reply_markup=markup, parse_mode="Markdown")
            except: pass
            return

    # --- USER STATES WITH SMART ERROR HANDLING ---
    if step == "awaiting_deposit_amt":
        try:
            amt = float(text)
            curr_code = u.get("currency", "BDT")
            amt_usd = amt / CURRENCY_RATES.get(curr_code, 1)
            
            s = get_settings()
            payments = s.get("payments", [])
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            for p in payments: 
                is_crypto = any(x in p['name'].lower() for x in ['usdt', 'binance', 'crypto', 'btc', 'pm', 'perfect', 'payeer'])
                display_amt = f"${amt_usd:.2f}" if is_crypto else f"{round(amt_usd * float(p['rate']), 2)} {curr_code}"
                markup.add(types.InlineKeyboardButton(f"🏦 {p['name']} (Pay {display_amt})", callback_data=f"PAY|{amt_usd}|{p['name']}"))
            
            if s.get("cryptomus_active") and s.get("cryptomus_merchant") and s.get("cryptomus_api"):
                markup.add(types.InlineKeyboardButton(f"🤖 Cryptomus (Pay ${amt_usd:.2f})", callback_data=f"PAY_CRYPTO|{amt_usd}|Cryptomus"))
            if s.get("coinpayments_active") and s.get("coinpayments_pub") and s.get("coinpayments_priv"):
                markup.add(types.InlineKeyboardButton(f"🪙 CoinPayments (Pay ${amt_usd:.2f})", callback_data=f"PAY_CRYPTO|{amt_usd}|CoinPayments"))

            clear_user_session(uid)
            return bot.send_message(uid, "💳 **Select Gateway:**", reply_markup=markup, parse_mode="Markdown")
        except ValueError: return bot.send_message(uid, "⚠️ Invalid amount. Numbers only.")

    elif step == "awaiting_link":
        if not re.match(r'^(https?://|t\.me/|@|www\.)[^\s]+$', text, re.IGNORECASE):
            return bot.send_message(uid, "❌ **INVALID FORMAT DETECTED!**\nThe link you provided is not supported.", parse_mode="Markdown", disable_web_page_preview=True)
            
        update_user_session(uid, {"step": "awaiting_qty", "temp_link": text})
        return bot.send_message(uid, "🔢 **Enter Quantity (Numbers only):**", parse_mode="Markdown")

    elif step == "awaiting_qty":
        try:
            qty = int(text)
            sid = session_data.get("temp_sid")
            pid = session_data.get("temp_pid") # Extract Provider ID
            o_type = session_data.get("order_type", "normal")
            
            services = get_cached_services()
            if pid: s = next((x for x in services if str(x['service']) == str(sid) and str(x.get('provider_id', 'MAIN')) == pid), None)
            else: s = next((x for x in services if str(x['service']) == str(sid)), None)
            
            if not s: return bot.send_message(uid, "❌ Service data missing. Please retry.")
            
            try: min_q = int(s.get('min', 0))
            except: min_q = 0
            
            try: max_q = int(s.get('max', 9999999))
            except: max_q = 9999999
            
            if qty < min_q or qty > max_q:
                return bot.send_message(uid, f"❌ **QUANTITY OUT OF RANGE!**\nAccepts between **{min_q}** and **{max_q}**.", parse_mode="Markdown")
            
            if o_type == "drip":
                update_user_session(uid, {"step": "awaiting_drip_runs", "temp_qty": qty})
                return bot.send_message(uid, "🔢 **Drip-Feed Runs:**\nHow many times should this quantity be sent? (e.g. 5)", parse_mode="Markdown")
            
            # 🔥 Detect if Custom Rate was mapped
            custom_rate = 0
            custom_menus_doc = config_col.find_one({"_id": "custom_menus"})
            if custom_menus_doc:
                for menu in custom_menus_doc.get("menus", []):
                    for srv_map in menu.get("services", []):
                        if str(srv_map.get('service_id')) == str(sid) and str(srv_map.get('provider_id')) == pid:
                            if srv_map.get('custom_rate'): custom_rate = float(srv_map['custom_rate'])

            if custom_rate > 0: rate = calculate_price(custom_rate, u.get('spent', 0), u.get('custom_discount', 0), 0)
            else: rate = calculate_price(s['rate'], u.get('spent', 0), u.get('custom_discount', 0), s.get('provider_margin', 0.0))
            
            cost = (rate / 1000) * qty
            curr = u.get("currency", "BDT")
            
            if u.get('balance', 0) < cost: 
                return bot.send_message(uid, f"❌ **INSUFFICIENT FUNDS!**\nNeed: `{fmt_curr(cost, curr)}`", parse_mode="Markdown")
            
            update_user_session(uid, {"draft": {"sid": sid, "provider_id": s.get('provider_id', 'MAIN'), "link": session_data.get("temp_link"), "qty": qty, "cost": cost, "type": "normal"}, "step": ""})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ CONFIRM", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
            bot.send_message(uid, f"⚠️ **ORDER PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Service ID: `{sid}`\n🔗 Link: {session_data.get('temp_link')}\n🔢 Quantity: {qty}\n💰 Cost: `{fmt_curr(cost, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm your order?", reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        except ValueError: bot.send_message(uid, "⚠️ **ERROR:** Please enter valid numbers only.")

    elif step == "awaiting_drip_runs":
        try:
            runs = int(text)
            update_user_session(uid, {"step": "awaiting_drip_interval", "temp_runs": runs})
            bot.send_message(uid, "⏱️ **Drip Interval:**\nTime delay between runs (in minutes, e.g. 15):", parse_mode="Markdown")
        except ValueError: bot.send_message(uid, "⚠️ Enter numbers only.")

    elif step == "awaiting_drip_interval":
        try:
            interval = int(text)
            sid = session_data.get("temp_sid")
            pid = session_data.get("temp_pid")
            qty = session_data.get("temp_qty")
            runs = session_data.get("temp_runs")
            
            services = get_cached_services()
            if pid: s = next((x for x in services if str(x['service']) == str(sid) and str(x.get('provider_id', 'MAIN')) == pid), None)
            else: s = next((x for x in services if str(x['service']) == str(sid)), None)
            
            custom_rate = 0
            custom_menus_doc = config_col.find_one({"_id": "custom_menus"})
            if custom_menus_doc:
                for menu in custom_menus_doc.get("menus", []):
                    for srv_map in menu.get("services", []):
                        if str(srv_map.get('service_id')) == str(sid) and str(srv_map.get('provider_id')) == pid:
                            if srv_map.get('custom_rate'): custom_rate = float(srv_map['custom_rate'])

            if custom_rate > 0: rate = calculate_price(custom_rate, u.get('spent', 0), u.get('custom_discount', 0), 0)
            else: rate = calculate_price(s['rate'], u.get('spent', 0), u.get('custom_discount', 0), s.get('provider_margin', 0.0))
            
            total_qty = qty * runs
            cost = (rate / 1000) * total_qty
            curr = u.get("currency", "BDT")
            
            if u.get('balance', 0) < cost: 
                return bot.send_message(uid, f"❌ **INSUFFICIENT FUNDS!**\nNeed: `{fmt_curr(cost, curr)}`", parse_mode="Markdown")
            
            update_user_session(uid, {"draft": {"sid": sid, "provider_id": s.get('provider_id', 'MAIN'), "link": session_data.get("temp_link"), "qty": qty, "runs": runs, "interval": interval, "total_qty": total_qty, "cost": cost, "type": "drip"}, "step": ""})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ CONFIRM DRIP", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
            bot.send_message(uid, f"💧 **DRIP-FEED PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Service: `{sid}`\n🔗 Link: {session_data.get('temp_link')}\n📦 Total Qty: {total_qty} ({qty} x {runs} runs)\n⏱️ Interval: {interval} mins\n💰 Total Cost: `{fmt_curr(cost, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm?", reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        except ValueError: bot.send_message(uid, "⚠️ Enter numbers only.")

    elif step == "awaiting_sub_user":
        update_user_session(uid, {"step": "awaiting_sub_posts", "temp_user": text})
        bot.send_message(uid, "📸 **How many future posts?** (e.g. 10):", parse_mode="Markdown")

    elif step == "awaiting_sub_posts":
        update_user_session(uid, {"step": "awaiting_sub_qty", "temp_posts": int(text)})
        bot.send_message(uid, "🔢 **Quantity per post?** (e.g. 500):", parse_mode="Markdown")

    elif step == "awaiting_sub_qty":
        update_user_session(uid, {"step": "awaiting_sub_delay", "temp_qty": int(text)})
        bot.send_message(uid, "⏱️ **Delay (minutes) before delivery starts?** (e.g. 15):", parse_mode="Markdown")

    elif step == "awaiting_sub_delay":
        try:
            delay = int(text)
            sid = session_data.get("temp_sid")
            pid = session_data.get("temp_pid")
            posts = session_data.get("temp_posts")
            qty = session_data.get("temp_qty")
            username = session_data.get("temp_user")
            
            services = get_cached_services()
            if pid: s = next((x for x in services if str(x['service']) == str(sid) and str(x.get('provider_id', 'MAIN')) == pid), None)
            else: s = next((x for x in services if str(x['service']) == str(sid)), None)
            
            custom_rate = 0
            custom_menus_doc = config_col.find_one({"_id": "custom_menus"})
            if custom_menus_doc:
                for menu in custom_menus_doc.get("menus", []):
                    for srv_map in menu.get("services", []):
                        if str(srv_map.get('service_id')) == str(sid) and str(srv_map.get('provider_id')) == pid:
                            if srv_map.get('custom_rate'): custom_rate = float(srv_map['custom_rate'])

            if custom_rate > 0: rate = calculate_price(custom_rate, u.get('spent', 0), u.get('custom_discount', 0), 0)
            else: rate = calculate_price(s['rate'], u.get('spent', 0), u.get('custom_discount', 0), s.get('provider_margin', 0.0))
            
            total_qty = posts * qty
            cost = (rate / 1000) * total_qty
            curr = u.get("currency", "BDT")
            
            if u.get('balance', 0) < cost: 
                return bot.send_message(uid, f"❌ **INSUFFICIENT FUNDS!**\nNeed: `{fmt_curr(cost, curr)}`", parse_mode="Markdown")
            
            update_user_session(uid, {"draft": {"sid": sid, "provider_id": s.get('provider_id', 'MAIN'), "username": username, "posts": posts, "qty": qty, "delay": delay, "cost": cost, "type": "sub"}, "step": ""})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ START SUBSCRIPTION", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
            bot.send_message(uid, f"🔄 **SUBSCRIPTION PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Service: `{sid}`\n👤 Target: {username}\n📸 Posts: {posts}\n📦 Qty/Post: {qty}\n⏱️ Delay: {delay} mins\n💰 Estimated Total: `{fmt_curr(cost, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm?", reply_markup=markup, parse_mode="Markdown")
        except ValueError: bot.send_message(uid, "⚠️ Enter numbers only.")

    elif step == "awaiting_bulk_order":
        lines = text.strip().split('\n')
        bulk_draft = []
        total_cost = 0.0
        services = get_cached_services()
        
        for idx, line in enumerate(lines):
            parts = line.split('|')
            if len(parts) != 3: return bot.send_message(uid, f"❌ Error on line {idx+1}: Wrong format.")
            sid, link, qty = parts[0].strip(), parts[1].strip(), parts[2].strip()
            
            if not qty.isdigit(): return bot.send_message(uid, f"❌ Error on line {idx+1}: Qty must be numbers.")
            qty = int(qty)
            s = next((x for x in services if str(x['service']) == str(sid)), None)
            if not s: return bot.send_message(uid, f"❌ Error on line {idx+1}: Service ID {sid} not found.")
            
            rate = calculate_price(s['rate'], u.get('spent', 0), u.get('custom_discount', 0), s.get('provider_margin', 0.0))
            cost = (rate / 1000) * qty
            total_cost += cost
            bulk_draft.append({"sid": sid, "provider_id": s.get('provider_id', 'MAIN'), "link": link, "qty": qty, "cost": cost})
            
        curr = u.get("currency", "BDT")
        if u.get('balance', 0) < total_cost: 
            return bot.send_message(uid, f"❌ **INSUFFICIENT FUNDS!**\nNeed: `{fmt_curr(total_cost, curr)}`", parse_mode="Markdown")
            
        update_user_session(uid, {"draft_bulk": bulk_draft, "total_bulk_cost": total_cost, "step": ""})
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ CONFIRM BULK", callback_data="PLACE_BULK"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
        bot.send_message(uid, f"📝 **BULK ORDER PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n📦 Total Orders: {len(bulk_draft)}\n💰 Total Cost: `{fmt_curr(total_cost, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm Processing?", reply_markup=markup, parse_mode="Markdown")

    elif step == "awaiting_ticket":
        clear_user_session(uid)
        tickets_col.insert_one({"uid": uid, "msg": text, "status": "open", "date": datetime.now()})
        admin_msg = f"📩 **NEW LIVE CHAT**\n👤 User: `{message.from_user.first_name}`\n🆔 ID: `{uid}`\n\n💬 **Message:**\n{text}\n\n_Reply to this message to send an answer directly._"
        threading.Thread(target=send_media_to_admin, args=(message, admin_msg)).start()
        return bot.send_message(uid, "✅ **Message Sent Successfully!** Admin will reply soon.", parse_mode="Markdown")

    elif step == "awaiting_voucher":
        clear_user_session(uid)
        code = text.upper()
        voucher = vouchers_col.find_one({"code": code})
        if not voucher: return bot.send_message(uid, "❌ Invalid Voucher Code.")
        if len(voucher.get('used_by', [])) >= voucher['limit']: return bot.send_message(uid, "❌ Voucher Limit Reached!")
        if uid in voucher.get('used_by', []): return bot.send_message(uid, "❌ You have already claimed this voucher.")
        vouchers_col.update_one({"code": code}, {"$push": {"used_by": uid}})
        users_col.update_one({"_id": uid}, {"$inc": {"balance": voucher['amount']}})
        clear_cached_user(uid)
        curr = u.get("currency", "BDT")
        return bot.send_message(uid, f"✅ **VOUCHER CLAIMED**\nReward: `{fmt_curr(voucher['amount'], curr)}` added to your wallet.", parse_mode="Markdown")

    elif step == "awaiting_search":
        clear_user_session(uid)
        query = text.lower()
        services = get_cached_services()
        hidden = get_settings().get("hidden_services", [])
        if query.isdigit():
            s = next((x for x in services if str(x['service']) == query and query not in hidden), None)
            if s: 
                markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("ℹ️ Order Now", callback_data=f"INFO|{query}|{s.get('provider_id','MAIN')}"))
                return bot.send_message(uid, f"✅ **Found:** {clean_service_name(s['name'])}", reply_markup=markup, parse_mode="Markdown")
        results = [s for s in services if str(s['service']) not in hidden and (query in s['name'].lower() or query in s['category'].lower())][:10]
        if not results: return bot.send_message(uid, "❌ No related services found.")
        markup = types.InlineKeyboardMarkup(row_width=1)
        for s in results: markup.add(types.InlineKeyboardButton(f"⚡ ID:{s['service']} | {clean_service_name(s['name'])[:25]}", callback_data=f"INFO|{s['service']}|{s.get('provider_id','MAIN')}"))
        return bot.send_message(uid, f"🔍 **Top Results:**", reply_markup=markup, parse_mode="Markdown")

# 🔥 MULTI-THREADING IMPLEMENTATION FOR API CALL
@bot.callback_query_handler(func=lambda c: c.data in ["PLACE_ORD", "PLACE_BULK"])
def final_ord(call):
    uid = call.message.chat.id
    u = get_cached_user(uid)
    session_data = get_user_session(uid)
    
    if call.data == "PLACE_BULK":
        drafts = session_data.get('draft_bulk')
        if not drafts: return bot.answer_callback_query(call.id, "❌ Session expired.")
        bot.edit_message_text("⏳ **Processing Bulk Orders in the background... Please wait.**", uid, call.message.message_id, parse_mode="Markdown")
        threading.Thread(target=process_bulk_background, args=(uid, u, drafts, call.message.message_id)).start()
    else:
        draft = session_data.get('draft')
        if not draft: return bot.answer_callback_query(call.id, "❌ Session expired.")
        bot.edit_message_text("⏳ **Processing your order securely in the background... Please wait.**", uid, call.message.message_id, parse_mode="Markdown")
        threading.Thread(target=process_order_background, args=(uid, u, draft, call.message.message_id)).start()

def process_bulk_background(uid, u, drafts, message_id):
    success_count = 0
    total_cost_deducted = 0
    points_earned = 0
    s = get_settings()
    
    for d in drafts:
        time.sleep(0.5)
        api_url, api_key = API_URL, API_KEY
        if d.get("provider_id") and d.get("provider_id") != "MAIN":
            provider = providers_col.find_one({"_id": ObjectId(d.get("provider_id"))})
            if provider:
                api_url = provider.get("api_url")
                api_key = provider.get("api_key")
                
        res = api.place_order(api_url, api_key, d['sid'], link=d['link'], quantity=d['qty'])
        if res and 'order' in res:
            success_count += 1
            total_cost_deducted += d['cost']
            pts = int(float(d['cost']) * float(s.get("points_per_usd", 100)))
            points_earned += pts
            orders_col.insert_one({"oid": res['order'], "uid": uid, "sid": d['sid'], "provider_id": d.get('provider_id', 'MAIN'), "link": d['link'], "qty": d['qty'], "cost": d['cost'], "status": "pending", "date": datetime.now()})
            
    users_col.update_one({"_id": uid}, {"$inc": {"balance": -total_cost_deducted, "spent": total_cost_deducted, "points": points_earned}})
    clear_cached_user(uid)
    clear_user_session(uid)
    bot.edit_message_text(f"✅ **BULK PROCESS COMPLETE!**\n━━━━━━━━━━━━━━━━━━━━\n📦 Successful: {success_count} / {len(drafts)}\n💰 Cost Deducted: `${total_cost_deducted:.3f}`\n🎁 Points Earned: `+{points_earned}`", uid, message_id, parse_mode="Markdown")

def process_order_background(uid, u, draft, message_id):
    s = get_settings()
    points_earned = int(float(draft['cost']) * float(s.get("points_per_usd", 100)))
    o_type = draft.get("type", "normal")
    
    if u.get('shadow_banned'):
        fake_oid = random.randint(100000, 999999)
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost'], "points": points_earned}})
        clear_cached_user(uid)
        clear_user_session(uid)
        
        insert_data = {"oid": fake_oid, "uid": uid, "sid": draft['sid'], "provider_id": draft.get('provider_id', 'MAIN'), "cost": draft['cost'], "status": "pending", "date": datetime.now(), "is_shadow": True}
        if o_type == "sub": insert_data.update({"is_sub": True, "username": draft['username'], "posts": draft['posts'], "qty": draft['qty']})
        else: insert_data.update({"link": draft.get('link'), "qty": draft.get('total_qty', draft.get('qty'))})
        
        orders_col.insert_one(insert_data)
        bot.edit_message_text(f"✅ **Order Placed Successfully!**\n🆔 Order ID: `{fake_oid}`\n🎁 Points Earned: `+{points_earned}`", uid, message_id, parse_mode="Markdown")
        return

    # 🔥 Fetch Multi-Provider Credentials
    api_url, api_key = API_URL, API_KEY
    if draft.get("provider_id") and draft.get("provider_id") != "MAIN":
        provider = providers_col.find_one({"_id": ObjectId(draft.get("provider_id"))})
        if provider:
            api_url = provider.get("api_url")
            api_key = provider.get("api_key")

    if o_type == "drip":
        res = api.place_order(api_url, api_key, draft['sid'], link=draft['link'], quantity=draft['qty'], runs=draft['runs'], interval=draft['interval'])
    elif o_type == "sub":
        res = api.place_order(api_url, api_key, draft['sid'], username=draft['username'], min=draft['qty'], max=draft['qty'], posts=draft['posts'], delay=draft['delay'])
    else:
        res = api.place_order(api_url, api_key, draft['sid'], link=draft['link'], quantity=draft['qty'])
    
    if res and 'order' in res:
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost'], "points": points_earned}})
        clear_cached_user(uid)
        clear_user_session(uid)
        
        insert_data = {"oid": res['order'], "uid": uid, "sid": draft['sid'], "provider_id": draft.get('provider_id', 'MAIN'), "cost": draft['cost'], "status": "pending", "date": datetime.now()}
        if o_type == "sub": insert_data.update({"is_sub": True, "username": draft['username'], "posts": draft['posts'], "qty": draft['qty']})
        else: insert_data.update({"link": draft['link'], "qty": draft.get('total_qty', draft['qty'])})
        
        orders_col.insert_one(insert_data)
        bot.edit_message_text(f"✅ **Order Placed Successfully!**\n🆔 Order ID: `{res['order']}`\n🎁 Points Earned: `+{points_earned}`", uid, message_id, parse_mode="Markdown")
        
        proof_ch = s.get('proof_channel', '')
        if proof_ch:
            masked_id = f"***{str(uid)[-4:]}"
            channel_post = f"```text\n╔════ 🟢 𝗡𝗘𝗪 𝗢𝗥𝗗𝗘𝗥 ════╗\n║ 👤 𝗜𝗗: {masked_id}\n║ 🚀 𝗦𝗲𝗿𝘃𝗶𝗰𝗲 𝗜𝗗: {draft['sid']}\n║ 💵 𝗖𝗼𝘀𝘁: ${draft['cost']:.3f}\n╚════════════════════╝\n```"
            try: bot.send_message(proof_ch, channel_post, parse_mode="Markdown")
            except: pass
    else:
        err_msg = res.get('error', 'API Timeout') if res else 'API Timeout'
        bot.edit_message_text(f"❌ **API REJECTED THE ORDER!**\n\n**Reason:** `{err_msg}`\n\nPlease check your link or try another service.", uid, message_id, parse_mode="Markdown")
        clear_user_session(uid)

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORD")
def cancel_ord(call):
    clear_user_session(call.message.chat.id)
    bot.edit_message_text("🚫 **Order Cancelled.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
