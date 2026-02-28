import re
import math
import random
import json
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from telebot import types
from bson.objectid import ObjectId

# 🔥 loader এবং নির্দিষ্ট utils ফাংশন ইম্পোর্ট (Memory Optimization)
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, redis_client
from config import *
import api
from utils import (escape_md, get_settings, get_currency_rates, fmt_curr,
                   get_cached_user, clear_cached_user, check_spam, check_maintenance,
                   get_cached_services, calculate_price, clean_service_name,
                   identify_platform, detect_platform_from_link, generate_progress_bar,
                   get_user_tier, main_menu, check_sub, create_cryptomus_payment,
                   create_coinpayments_payment, create_nowpayments_payment, create_payeer_payment, BASE_URL)

# Thread Pool for background tasks (Prevents Thread Exhaustion)
order_executor = ThreadPoolExecutor(max_workers=20)

# ==========================================
# 🔥 ANTI-CRASH EDIT ENGINE
# ==========================================
def safe_edit_message(text, chat_id, message_id, reply_markup=None, parse_mode="Markdown", disable_web_page_preview=True):
    try:
        bot.edit_message_text(
            text=text, 
            chat_id=chat_id, 
            message_id=message_id, 
            reply_markup=reply_markup, 
            parse_mode=parse_mode, 
            disable_web_page_preview=disable_web_page_preview
        )
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            logging.error(f"Edit Message Error: {e}")

# ==========================================
# 🔥 REDIS SESSION & LOCK MANAGER
# ==========================================
def is_button_locked(uid, call_id):
    lock_key = f"lock_btn_{uid}"
    if redis_client.get(lock_key):
        try: bot.answer_callback_query(call_id, "⏳ Please wait... processing.")
        except: pass
        return True
    redis_client.setex(lock_key, 2, "locked")
    return False

def get_user_session(uid):
    try:
        data = redis_client.get(f"session_{uid}")
        return json.loads(data) if data else {}
    except:
        return {}

def update_user_session(uid, updates):
    try:
        session = get_user_session(uid)
        session.update(updates)
        redis_client.setex(f"session_{uid}", 3600, json.dumps(session))
    except Exception as e:
        logging.error(f"Redis Session Error: {e}")

def clear_user_session(uid):
    try:
        redis_client.delete(f"session_{uid}")
    except:
        pass

# ==========================================
# 3. FORCE SUB, REFERRAL & START LOGIC
# ==========================================
def process_new_user_bonuses(uid):
    user = get_cached_user(uid) or {}
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
        user = users_col.find_one({"_id": uid}) or {}
        clear_cached_user(uid)
        
        try:
            safe_name = escape_md(message.from_user.first_name)
            ref_text = f"`{referrer}`" if referrer else "None"
            bot.send_message(ADMIN_ID, f"👤 **NEW USER JOINED!**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **User ID:** `{uid}`\n📛 **Name:** {safe_name}\n🤝 **Referred By:** {ref_text}", parse_mode="Markdown")
        except: pass
        
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

    safe_name = escape_md(message.from_user.first_name)
    welcome_text = f"""{greeting}, {safe_name}! ⚡️

🚀 **𝗪𝗘𝗟𝗖𝗢𝗠𝗘 𝗧𝗢 𝗡𝗘𝗫𝗨𝗦 𝗦𝗠𝗠**
_"Your Ultimate Social Growth Engine"_
━━━━━━━━━━━━━━━━━━━━━
👤 **𝗨𝘀𝗲𝗿:** {safe_name}
🆔 **𝗦𝘆𝘀𝘁𝗲𝗺 𝗜𝗗:** `{uid}`
👑 **𝗦𝘁𝗮𝘁𝘂𝘀:** Connected 🟢
💡 _Pro Tip: Paste any profile/post link directly here to Quick-Order!_
━━━━━━━━━━━━━━━━━━━━━
Let's boost your digital presence today! 👇"""
    bot.send_message(uid, welcome_text, reply_markup=main_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CHECK_SUB")
def sub_callback(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    uid = call.message.chat.id
    if check_sub(uid):
        try: bot.delete_message(uid, call.message.message_id)
        except: pass
        bot.send_message(uid, "✅ **Access Granted! Welcome to the panel.**", reply_markup=main_menu())
        process_new_user_bonuses(uid)
    else: bot.send_message(uid, "❌ You haven't joined all channels.")

# ==========================================
# 4. ORDERING ENGINE & FILTERS
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🚀 New Order")
def new_order_start(message):
    uid = message.chat.id
    clear_user_session(uid)
    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    services = get_cached_services()
    if not services: return bot.send_message(uid, "⏳ **API Syncing...** Try again in a few seconds.")
    
    hidden = get_settings().get("hidden_services", [])
    platforms = sorted(list(set(identify_platform(str(s.get('category', 'Other'))) for s in services if str(s.get('service', '0')) not in hidden)))
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    best_sids = get_settings().get("best_choice_sids", [])
    if best_sids: markup.add(types.InlineKeyboardButton("🌟 ADMIN BEST CHOICE 🌟", callback_data="SHOW_BEST_CHOICE|0"))
    for p in platforms: markup.add(types.InlineKeyboardButton(p, callback_data=f"PLAT|{p}|0"))
    bot.send_message(uid, "📂 **Select a Platform:**\n_💡 Pro Tip: Just paste any link in the chat to auto-detect platform!_", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("SHOW_BEST_CHOICE"))
def show_best_choices(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    parts = call.data.split("|")
    page = int(parts[1]) if len(parts) > 1 else 0
    
    services = get_cached_services()
    best_sids = get_settings().get("best_choice_sids", [])
    user = get_cached_user(call.message.chat.id) or {}
    curr = user.get("currency", "BDT")
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    start_idx, end_idx = page * 10, page * 10 + 10
    
    for tsid in best_sids[start_idx:end_idx]:
        srv = next((x for x in services if str(x.get('service', '')) == str(tsid).strip()), None)
        if srv:
            rate = calculate_price(srv.get('rate', 0.0), user.get('spent', 0), user.get('custom_discount', 0))
            markup.add(types.InlineKeyboardButton(f"ID:{srv.get('service', '0')} | {fmt_curr(rate, curr)} | {clean_service_name(srv.get('name'))}", callback_data=f"INFO|{tsid}"))
            
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"SHOW_BEST_CHOICE|{page-1}"))
    if end_idx < len(best_sids): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"SHOW_BEST_CHOICE|{page+1}"))
    if nav: markup.row(*nav)
    
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="NEW_ORDER_BACK"))
    safe_edit_message("🌟 **ADMIN BEST CHOICE** 🌟\nHandpicked premium services for you:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "NEW_ORDER_BACK")
def back_to_main(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    new_order_start(call.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("PLAT|"))
def show_cats(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id) 
    _, platform, page = call.data.split("|")
    page = int(page)
    services = get_cached_services()
    hidden = get_settings().get("hidden_services", [])
    
    cats = sorted(list(set(str(s.get('category', 'Other')) for s in services if identify_platform(str(s.get('category', 'Other'))) == platform and str(s.get('service', '0')) not in hidden)))
    
    start_idx, end_idx = page * 15, page * 15 + 15
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    all_cats_sorted = sorted(list(set(str(s.get('category', 'Other')) for s in services)))
    for cat in cats[start_idx:end_idx]:
        idx = all_cats_sorted.index(cat)
        markup.add(types.InlineKeyboardButton(f"📁 {cat[:35]}", callback_data=f"CAT|{idx}|0|all"))
        
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"PLAT|{platform}|{page-1}"))
    if end_idx < len(cats): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"PLAT|{platform}|{page+1}"))
    if nav: markup.row(*nav)
    
    safe_plat = escape_md(platform)
    safe_edit_message(f"📍 **{safe_plat}**\n━━━━━━━━━━━━━━━━━━━━\n📂 **Choose Category:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("CAT|"))
def list_servs(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id) 
    
    parts = call.data.split("|")
    cat_idx = int(parts[1])
    page = int(parts[2])
    filter_type = parts[3] if len(parts) > 3 else "all"
    
    services = get_cached_services()
    all_cats = sorted(list(set(str(s.get('category', 'Other')) for s in services)))
    
    if cat_idx >= len(all_cats): return bot.send_message(call.message.chat.id, "❌ Error loading category.")
    cat_name = all_cats[cat_idx]
    
    hidden = get_settings().get("hidden_services", [])
    user = get_cached_user(call.message.chat.id) or {}
    curr = user.get("currency", "BDT")
    
    filtered = [s for s in services if str(s.get('category', 'Other')) == cat_name and str(s.get('service', '0')) not in hidden]
    
    if filter_type == "price_asc":
        filtered.sort(key=lambda x: calculate_price(x.get('rate', 0.0), user.get('spent',0), user.get('custom_discount', 0)))
    elif filter_type == "fast":
        filtered = [x for x in filtered if any(kw in str(x.get('name', '')).lower() for kw in ['instant', 'fast', '⚡'])]
    elif filter_type == "guarantee":
        filtered = [x for x in filtered if any(kw in str(x.get('name', '')).lower() for kw in ['refill', 'non drop', '💎', '♻️', 'guarantee'])]

    start_idx, end_idx = page * 10, page * 10 + 10
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    markup.row(
        types.InlineKeyboardButton("🔽 Price", callback_data=f"CAT|{cat_idx}|0|price_asc"),
        types.InlineKeyboardButton("⚡ Fast", callback_data=f"CAT|{cat_idx}|0|fast"),
        types.InlineKeyboardButton("🛡️ Guar", callback_data=f"CAT|{cat_idx}|0|guarantee"),
        types.InlineKeyboardButton("🔄 All", callback_data=f"CAT|{cat_idx}|0|all")
    )
    
    if not filtered:
        markup.add(types.InlineKeyboardButton("❌ No services found for this filter.", callback_data="dummy"))
    else:
        for s in filtered[start_idx:end_idx]:
            rate = calculate_price(s.get('rate', 0.0), user.get('spent',0), user.get('custom_discount', 0))
            markup.add(types.InlineKeyboardButton(f"ID:{s.get('service', '0')} | {fmt_curr(rate, curr)} | {clean_service_name(s.get('name'))}", callback_data=f"INFO|{s.get('service', '0')}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"CAT|{cat_idx}|{page-1}|{filter_type}"))
    if end_idx < len(filtered): nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"CAT|{cat_idx}|{page+1}|{filter_type}"))
    if nav: markup.row(*nav)
    
    markup.add(types.InlineKeyboardButton("🔙 Back to Platforms", callback_data=f"PLAT|{identify_platform(cat_name)}|0"))
    
    safe_cat = escape_md(cat_name[:30])
    filter_label = {"all": "All Services", "price_asc": "Low to High", "fast": "Fastest Services", "guarantee": "Guaranteed/Refill"}.get(filter_type, "All")
    msg_text = f"📦 **{safe_cat}**\n━━━━━━━━━━━━━━━━━━━━\n🔍 Filter: **{filter_label}**\nSelect Service:"
    
    safe_edit_message(msg_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("INFO|"))
def info_card(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id) 
    parts = call.data.split("|")
    sid = "|".join(parts[1:]) 
    
    services = get_cached_services()
    s = next((x for x in services if str(x.get('service', '0')) == str(sid)), None)
    if not s: 
        return bot.send_message(call.message.chat.id, "❌ Service unavailable at the moment. Try again.")
    
    user = get_cached_user(call.message.chat.id) or {}
    curr = user.get("currency", "BDT")
    rate = calculate_price(s.get('rate', 0.0), user.get('spent',0), user.get('custom_discount', 0))
    avg_time = s.get('time', 'Instant - 24h') if s.get('time') else 'Instant - 24h'

    safe_name = escape_md(clean_service_name(s.get('name')))
    txt = (f"ℹ️ **SERVICE DETAILS**\n━━━━━━━━━━━━━━━━━━━━\n🏷 **Name:** {safe_name}\n🆔 **ID:** `{sid}`\n"
           f"💰 **Price:** `{fmt_curr(rate, curr)}` / 1000\n📉 **Min:** {s.get('min','0')} | 📈 **Max:** {s.get('max','0')}\n"
           f"⏱ **Live Avg Time:** `{escape_md(avg_time)}`⚡️\n━━━━━━━━━━━━━━━━━━━━")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🚀 Normal Order", callback_data=f"TYPE|{sid}|normal"))
    if str(s.get('dripfeed', 'False')).lower() == 'true':
        markup.add(types.InlineKeyboardButton("💧 Drip-Feed (Organic)", callback_data=f"TYPE|{sid}|drip"))
    markup.add(types.InlineKeyboardButton("🔄 Auto-Subscription (Posts)", callback_data=f"TYPE|{sid}|sub"))
    
    markup.add(types.InlineKeyboardButton("⭐ Fav", callback_data=f"FAV_ADD|{sid}"))
    
    try: 
        all_cats = sorted(list(set(str(x.get('category', 'Other')) for x in services)))
        cat_idx = all_cats.index(str(s.get('category', 'Other')))
        markup.add(types.InlineKeyboardButton("🔙 Back to Category", callback_data=f"CAT|{cat_idx}|0|all"))
    except: 
        pass
    
    if call.message.text and ("YOUR ORDERS" in call.message.text or "Found:" in call.message.text or "Top Results:" in call.message.text): 
        try: bot.send_message(call.message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")
        except: pass
    else: 
        safe_edit_message(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("TYPE|"))
def order_type_router(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id) 
    parts = call.data.split("|")
    sid = "|".join(parts[1:-1]) 
    o_type = parts[-1]
    
    session = get_user_session(call.message.chat.id)
    magic_link = session.get("temp_link", "")
    
    if o_type == "normal":
        if magic_link:
            update_user_session(call.message.chat.id, {"step": "awaiting_qty", "temp_sid": sid, "order_type": "normal"})
            bot.send_message(call.message.chat.id, f"🎯 **Link Detected:** {escape_md(magic_link)}\n🔢 **Enter Quantity (Numbers only):**", parse_mode="Markdown", disable_web_page_preview=True)
        else:
            update_user_session(call.message.chat.id, {"step": "awaiting_link", "temp_sid": sid, "order_type": "normal"})
            bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**\n_(Example: https://t.me/yourchannel)_", parse_mode="Markdown")
            
    elif o_type == "drip":
        update_user_session(call.message.chat.id, {"step": "awaiting_link", "temp_sid": sid, "order_type": "drip"})
        bot.send_message(call.message.chat.id, "💧 **DRIP-FEED ORDER**\n🔗 **Paste the Target Link:**", parse_mode="Markdown")
        
    elif o_type == "sub":
        update_user_session(call.message.chat.id, {"step": "awaiting_sub_user", "temp_sid": sid, "order_type": "sub"})
        bot.send_message(call.message.chat.id, "🔄 **AUTO-SUBSCRIPTION WIZARD**\n👤 **Enter Target Username:**\n_(e.g., @cristiano or cristiano)_", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ORD|"))
def start_ord(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    sid = "|".join(call.data.split("|")[1:])
    update_user_session(call.message.chat.id, {"step": "awaiting_link", "temp_sid": sid, "order_type": "normal"})
    bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**\n_(Example: https://t.me/yourchannel)_", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("REORDER|"))
def reorder_callback(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    sid = "|".join(call.data.split("|")[1:])
    update_user_session(call.message.chat.id, {"step": "awaiting_link", "temp_sid": sid, "order_type": "normal"})
    bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link for Reorder:**\n_(Example: https://t.me/yourchannel)_", parse_mode="Markdown")

# ==========================================
# 5. UNIVERSAL BUTTONS & PROFILE
# ==========================================
def fetch_orders_page(chat_id, page=0, filter_type="all"):
    user = get_cached_user(chat_id) or {}
    curr = user.get("currency", "BDT")
    
    query = {"uid": chat_id}
    if filter_type == "subs": query["is_sub"] = True
    
    # 🔥 FIX: Use count_documents and skip/limit for massive speed boost!
    total_orders = orders_col.count_documents(query)
    
    if total_orders == 0:
        return "📭 No orders found." if filter_type == "all" else "📭 No active subscriptions found.", None
    
    start = page * 3
    page_orders = list(orders_col.find(query).sort("_id", -1).skip(start).limit(3))
    
    title = "📦 **YOUR ORDERS**" if filter_type == "all" else "🔄 **ACTIVE SUBSCRIPTIONS**"
    txt = f"{title} (Page {page+1}/{math.ceil(total_orders/3)})\n━━━━━━━━━━━━━━━━━━━━\n"
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
        
        txt += f"🆔 `{o.get('oid', 'N/A')}` | 💰 `{fmt_curr(o.get('cost', 0), curr)}`\n"
        if o.get("is_sub"):
            txt += f"👤 Target: {escape_md(str(o.get('username', 'N/A')))}\n"
            txt += f"📸 Posts: {o.get('posts', 0)} | Qty/Post: {qty}\n"
        else:
            safe_link = escape_md(str(o.get('link', 'N/A'))[:25])
            txt += f"🔗 {safe_link}...\n"
            
        txt += f"🏷 Status: {st_emoji} {st.upper()}\n"
        if st in ['in progress', 'processing', 'pending'] and not o.get("is_sub"):
            txt += f"📊 Progress: `{p_bar}`\n✅ Delivered: {delivered} / {qty}\n"
        txt += "\n"
        
        row_btns = [types.InlineKeyboardButton(f"🔁 Reorder", callback_data=f"REORDER|{o.get('sid', 0)}")]
        if st in ['completed', 'partial'] and not o.get("is_shadow") and not o.get("is_sub"):
            row_btns.append(types.InlineKeyboardButton(f"🔄 Refill", callback_data=f"INSTANT_REFILL|{o.get('oid', 0)}"))
        markup.row(*row_btns)
            
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"MYORD|{page-1}|{filter_type}"))
    if start + 3 < total_orders: nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"MYORD|{page+1}|{filter_type}"))
    if filter_type == "subs": nav.append(types.InlineKeyboardButton("🔙 All Orders", callback_data="MYORD|0|all"))
    if nav: markup.row(*nav)
    return txt, markup

@bot.callback_query_handler(func=lambda c: c.data.startswith("INSTANT_REFILL|"))
def process_instant_refill(call):
    if is_button_locked(call.from_user.id, call.id): return
    try:
        oid = int(call.data.split("|")[1])
    except ValueError:
        return bot.answer_callback_query(call.id, "❌ Invalid Order ID.", show_alert=True)
        
    res = api.send_refill(oid)
    if res and 'refill' in res: bot.answer_callback_query(call.id, f"✅ Auto-Refill Triggered! Task ID: {res['refill']}", show_alert=True)
    else: bot.answer_callback_query(call.id, "❌ Refill not available or requested too early.", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("MYORD|"))
def my_orders_pagination(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    parts = call.data.split("|")
    page = int(parts[1])
    filter_type = parts[2] if len(parts) > 2 else "all"
    txt, markup = fetch_orders_page(call.message.chat.id, page, filter_type)
    safe_edit_message(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data == "REDEEM_POINTS")
def redeem_points(call):
    if is_button_locked(call.from_user.id, call.id): return
    u = get_cached_user(call.message.chat.id) or {}
    pts = u.get("points", 0)
    s = get_settings()
    rate = s.get("points_to_usd_rate", 1000)
    if pts < rate: return bot.answer_callback_query(call.id, f"❌ Minimum {rate} Points required to redeem.", show_alert=True)
    reward = pts / float(rate)
    users_col.update_one({"_id": call.message.chat.id}, {"$inc": {"balance": reward}, "$set": {"points": 0}})
    clear_cached_user(call.message.chat.id)
    bot.answer_callback_query(call.id, f"✅ Redeemed {pts} Points for ${reward:.2f}!", show_alert=True)
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("FAV_ADD|"))
def add_to_favorites(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id, "⭐ Added to Favorites!", show_alert=True)
    sid = "|".join(call.data.split("|")[1:])
    users_col.update_one({"_id": call.message.chat.id}, {"$addToSet": {"favorites": sid}})
    clear_cached_user(call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("SET_CURR|"))
def set_currency_callback(call):
    if is_button_locked(call.from_user.id, call.id): return
    curr = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"currency": curr}})
    clear_cached_user(call.message.chat.id)
    bot.answer_callback_query(call.id, f"✅ Currency updated to {curr}")
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    call.message.text = "👤 Profile"
    universal_buttons(call.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("PAY|"))
def pay_details(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    
    parts = call.data.split("|")
    if len(parts) == 4:
        _, amt_usd_str, exact_local_amt_str, method = parts
        amt_usd = float(amt_usd_str)
        exact_local_amt = float(exact_local_amt_str)
    else:
        _, amt_usd_str, method = parts
        amt_usd = float(amt_usd_str)
        exact_local_amt = None
        
    uid = call.message.chat.id
    u = get_cached_user(uid) or {}
    curr = u.get("currency", "BDT")
    
    s = get_settings()
    pay_data = next((p for p in s.get('payments', []) if p['name'] == method), None)
    address = pay_data.get('address', 'Contact Admin') if pay_data else 'Contact Admin'
    rate = pay_data.get('rate', 120) if pay_data else 120
    
    is_crypto = any(x in method.lower() for x in ['usdt', 'binance', 'crypto', 'btc', 'pm', 'perfect', 'payeer'])
    local_amt = amt_usd * float(rate)
    
    if is_crypto:
        display_amt = f"${amt_usd:.2f}"
    else:
        if exact_local_amt is not None:
            formatted_amt = int(exact_local_amt) if exact_local_amt.is_integer() else round(exact_local_amt, 2)
        else:
            formatted_amt = int(local_amt) if local_amt.is_integer() else round(local_amt, 2)
        display_amt = f"{formatted_amt} TK" if curr == "BDT" else f"{formatted_amt} {curr}"
    
    safe_method = escape_md(method)
    safe_address = escape_md(address)
    
    txt = f"🏦 **{safe_method} Payment Details**\n━━━━━━━━━━━━━━━━━━━━\n💵 **Amount to Send:** `{display_amt}`\n📍 **Account / Address:** `{safe_address}`\n━━━━━━━━━━━━━━━━━━━━\n⚠️ Send the exact amount to the address above, then reply to this message with your **TrxID / Transaction ID**:"
    
    update_user_session(uid, {"step": "awaiting_trx", "temp_dep_amt": amt_usd, "temp_dep_method": method})
    safe_edit_message(txt, uid, call.message.message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("CLOSE_TICKET|"))
def close_support_ticket(call):
    bot.answer_callback_query(call.id, "Ticket Closed Successfully!")
    tid = call.data.split("|")[1]
    tickets_col.update_one({"_id": ObjectId(tid)}, {"$set": {"status": "closed", "closed_by": "User"}})
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    bot.send_message(call.message.chat.id, "✅ **Support Ticket Closed.**\nIf you need further help, you can open a new ticket from Live Chat.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "NEW_TICKET")
def start_new_ticket(call):
    bot.answer_callback_query(call.id)
    update_user_session(call.message.chat.id, {"step": "awaiting_ticket"})
    safe_edit_message("💬 **NEW LIVE SUPPORT TICKET**\nSend your message here. You can also send Screenshots or Photos! Our Admins will reply directly.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("PAY_CRYPTO|"))
def pay_crypto_details(call):
    if is_button_locked(call.from_user.id, call.id): return
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
        
    elif method == "NowPayments":
        order_id = f"{uid}_{random.randint(100000, 999999)}"
        ipn_url = f"{BASE_URL.rstrip('/')}/nowpayments_ipn"
        pay_url = create_nowpayments_payment(amt_usd, order_id, s.get('nowpayments_api'), ipn_url)
        
    elif method == "Payeer":
        order_id = f"{uid}_{random.randint(100000, 999999)}"
        pay_url = create_payeer_payment(amt_usd, order_id, s.get('payeer_merchant'), s.get('payeer_secret'))
        
    if pay_url:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"💳 PAY ${amt_usd:.2f} NOW", url=pay_url))
        txt = f"🔗 **{escape_md(method)} Secure Checkout**\n━━━━━━━━━━━━━━━━━━━━\n💵 **Amount to Send:** `${amt_usd:.2f}`\n\nClick the button below to complete your transaction on the secure gateway. Your balance will be added automatically once confirmed by the network!"
        safe_edit_message(txt, uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    else:
        safe_edit_message(f"❌ Failed to generate {method} invoice. Please check API keys or contact Admin.", uid, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("PAY_STARS|"))
def pay_stars_details(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    
    parts = call.data.split("|")
    amt_usd = float(parts[1])
    stars_amt = int(parts[2])
    uid = call.message.chat.id
    
    try:
        bot.send_invoice(
            uid,
            title="Wallet Deposit",
            description=f"Deposit ${amt_usd:.2f} to your NEXUS SMM wallet using Telegram Stars.",
            invoice_payload=f"dep_{amt_usd}_{random.randint(1000,9999)}",
            provider_token="",
            currency="XTR",
            prices=[types.LabeledPrice(label=f"Deposit ${amt_usd:.2f}", amount=stars_amt)]
        )
    except Exception as e:
        logging.error(f"Telegram Stars Error: {e}")
        bot.send_message(uid, "❌ Failed to generate Telegram Stars invoice.")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("dep_"):
        amt_usd = float(payload.split("_")[1])
        uid = message.chat.id
        
        users_col.update_one({"_id": uid}, {"$inc": {"balance": amt_usd}})
        clear_cached_user(uid)
        
        try: bot.send_message(uid, f"✅ **STARS DEPOSIT SUCCESS!**\nAmount: `${amt_usd:.2f}` has been securely added to your wallet.", parse_mode="Markdown")
        except: pass

        # 🔥 NEW: Admin Notification for Telegram Stars Deposit
        try: bot.send_message(ADMIN_ID, f"🔔 **STARS DEPOSIT:** User `{uid}` added `${amt_usd:.2f}` via Telegram Stars!", parse_mode="Markdown")
        except: pass

def universal_buttons(message):
    uid = message.chat.id
    clear_user_session(uid)
    
    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    u = get_cached_user(uid) or {}
    curr = u.get("currency", "BDT")

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
        
        safe_name = escape_md(str(message.from_user.first_name)[:12])
        safe_tier = escape_md(tier)
        card = f"```text\n╔════════════════════════════════╗\n║  🌟 NEXUS VIP PASSPORT         ║\n╠════════════════════════════════╣\n║  👤 Name: {safe_name.ljust(19)}║\n║  🆔 UID: {str(uid).ljust(20)}║\n║  💳 Balance: {fmt_curr(u.get('balance',0), curr).ljust(18)}║\n║  💸 Spent: {fmt_curr(u.get('spent',0), curr).ljust(20)}║\n║  🏆 Points: {str(u.get('points', 0)).ljust(19)}║\n║  👑 Tier: {safe_tier.ljust(19)}║\n╚════════════════════════════════╝\n```"
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
                safe_name = escape_md(tu.get('name', 'N/A')[:10])
                txt += f"{medals[i]} {safe_name} - `{fmt_curr(tu.get('spent', 0), curr)}`{rt}\n"

        txt += "\n👥 **TOP AFFILIATES (By Earnings):**\n"
        top_refs = list(users_col.find({"ref_earnings": {"$gt": 0}}).sort("ref_earnings", -1).limit(5))
        if not top_refs: txt += "_No affiliates yet!_\n"
        else:
            for i, tu in enumerate(top_refs):
                safe_name = escape_md(tu.get('name', 'N/A')[:10])
                txt += f"{medals[i]} {safe_name} - `{fmt_curr(tu.get('ref_earnings', 0), curr)}`\n"

        bot.send_message(uid, txt + "\n_Be in the Top 3 to earn real wallet cash!_", parse_mode="Markdown")

    elif message.text == "⭐ Favorites":
        favs = u.get("favorites", [])
        if not favs: return bot.send_message(uid, "📭 **Your vault is empty!**\nAdd services to favorites to see them here.", parse_mode="Markdown")
        services = get_cached_services()
        markup = types.InlineKeyboardMarkup(row_width=1)
        for sid in favs:
            s = next((x for x in services if str(x.get('service', '0')) == str(sid)), None)
            if s: 
                safe_name = escape_md(clean_service_name(s.get('name'))[:25])
                markup.add(types.InlineKeyboardButton(f"⭐ ID:{s.get('service', '0')} | {safe_name}", callback_data=f"INFO|{s.get('service', '0')}"))
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
        open_tickets = list(tickets_col.find({"uid": uid, "status": "open"}))
        if open_tickets:
            for t in open_tickets:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("❌ Close Ticket", callback_data=f"CLOSE_TICKET|{t['_id']}"))
                safe_msg = escape_md(t['msg'][:100])
                bot.send_message(uid, f"🎧 **OPEN SUPPORT TICKET**\n━━━━━━━━━━━━━━━━━━━━\n**Date:** `{t.get('date', datetime.now()).strftime('%Y-%m-%d %H:%M')}`\n**Your Message:** {safe_msg}...\n\n_Wait for an admin to reply, or close this ticket._", reply_markup=markup, parse_mode="Markdown")
            
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("➕ Open New Ticket", callback_data="NEW_TICKET"))
            bot.send_message(uid, "Do you want to open another ticket?", reply_markup=markup)
        else:
            update_user_session(uid, {"step": "awaiting_ticket"})
            bot.send_message(uid, "💬 **LIVE SUPPORT**\nSend your message here. You can also send Screenshots or Photos! Our Admins will reply directly.", parse_mode="Markdown")
        
    elif message.text == "📝 Bulk Order":
        update_user_session(uid, {"step": "awaiting_bulk_order"})
        bot.send_message(uid, "📝 **BULK ORDER PROCESSING**\nSend your orders in this exact format (One order per line):\n`ServiceID | Link | Quantity`\n\n**Example:**\n`102 | https://ig.com/p/1 | 1000`\n`55 | https://fb.com/p/2 | 500`", parse_mode="Markdown")

def send_media_to_admin(msg_obj, admin_text):
    try:
        if msg_obj.photo:
            bot.send_photo(ADMIN_ID, msg_obj.photo[-1].file_id, caption=admin_text, parse_mode="Markdown")
        elif msg_obj.document:
            bot.send_document(ADMIN_ID, msg_obj.document.file_id, caption=admin_text, parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Media forwarding to admin failed: {e}")

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
                if "🆔 ID: " in reply_text:
                    target_uid = int(reply_text.split("🆔 ID: ")[1].split("\n")[0].strip().replace("`", ""))
                else:
                    target_uid = int(reply_text.split("ID: ")[1].split("\n")[0].strip().replace("`", ""))
                    
                safe_text = escape_md(text)
                bot.send_message(target_uid, f"👨‍💻 **ADMIN REPLY:**\n━━━━━━━━━━━━━━━━━━━━\n{safe_text}", parse_mode="Markdown")
                tickets_col.update_many({"uid": target_uid, "status": "open"}, {"$set": {"status": "closed", "reply": text}})
                return bot.send_message(ADMIN_ID, f"✅ Reply sent successfully to user `{target_uid}`!")
            except Exception as e: 
                pass

    if check_spam(uid) or check_maintenance(uid) or not check_sub(uid): return
    if text in ["🚀 New Order", "⭐ Favorites", "🔍 Smart Search", "📦 Orders", "💰 Deposit", "📝 Bulk Order", "🤝 Affiliate", "👤 Profile", "🎟️ Voucher", "🏆 Leaderboard", "💬 Live Chat"]:
        return universal_buttons(message)

    u = get_cached_user(uid) or {}
    session_data = get_user_session(uid)
    step = session_data.get("step", "")

    # 🔥 ADMIN INPUT HANDLER
    if str(uid) == str(ADMIN_ID):
        if step == "awaiting_bc":
            clear_user_session(uid)
            bot.send_message(uid, "✅ Broadcast task started!")
            def execute_bc():
                for tu in users_col.find({"is_fake": {"$ne": True}}):
                    try: 
                        bot.send_message(tu["_id"], f"📢 **BROADCAST**\n━━━━━━━━━━━━\n{text}", parse_mode="Markdown")
                        time.sleep(0.05)
                    except: pass
            
            # 🔥 FIX: ThreadPoolExecutor ব্যবহার করা হয়েছে
            order_executor.submit(execute_bc)
            return
            
        elif step == "awaiting_ghost_uid":
            clear_user_session(uid)
            try:
                target = int(text)
                tu = users_col.find_one({"_id": target}) or {}
                if tu: bot.send_message(uid, f"👻 **GHOST INFO:**\nUID: `{target}`\nName: {escape_md(tu.get('name'))}\nBal: `${tu.get('balance', 0):.3f}`\nSpent: `${tu.get('spent', 0):.3f}`\nPoints: `{tu.get('points', 0)}`", parse_mode="Markdown")
                else: bot.send_message(uid, "❌ User not found.")
            except: bot.send_message(uid, "❌ Invalid UID format.")
            return
            
        elif step == "awaiting_alert_uid":
            try:
                target = int(text)
                update_user_session(uid, {"step": "awaiting_alert_msg", "target_uid": target})
                bot.send_message(uid, f"📩 Enter custom alert message for `{target}`:", parse_mode="Markdown")
            except:
                clear_user_session(uid)
                bot.send_message(uid, "❌ Invalid UID format.")
            return
            
        elif step == "awaiting_alert_msg":
            target = session_data.get("target_uid")
            clear_user_session(uid)
            try:
                bot.send_message(target, f"🔔 **SYSTEM ALERT**\n━━━━━━━━━━━━\n{text}", parse_mode="Markdown")
                bot.send_message(uid, "✅ Alert sent successfully!")
            except:
                bot.send_message(uid, "❌ Failed to send alert.")
            return
            
        elif step == "awaiting_points_cfg":
            clear_user_session(uid)
            try:
                pts_usd, to_usd = map(int, text.replace(' ', '').split(','))
                config_col.update_one({"_id": "settings"}, {"$set": {"points_per_usd": pts_usd, "points_to_usd_rate": to_usd}}, upsert=True)
                from utils import update_settings_cache
                update_settings_cache("points_per_usd", pts_usd)
                update_settings_cache("points_to_usd_rate", to_usd)
                bot.send_message(uid, "✅ Points Config Updated Successfully!")
            except:
                bot.send_message(uid, "❌ Invalid format! Example: 50, 1000")
            return

    if step == "" and re.match(r'^(https?://|t\.me/|@|www\.)[^\s]+$', text, re.IGNORECASE):
        platform = detect_platform_from_link(text)
        if platform:
            services = get_cached_services()
            hidden = get_settings().get("hidden_services", [])
            cats = sorted(list(set(str(s.get('category', 'Other')) for s in services if identify_platform(str(s.get('category', 'Other'))) == platform and str(s.get('service', '0')) not in hidden)))
            if cats:
                update_user_session(uid, {"temp_link": text})
                markup = types.InlineKeyboardMarkup(row_width=1)
                all_cats_sorted = sorted(list(set(str(s.get('category', 'Other')) for s in services)))
                for cat in cats[:15]:
                    idx = all_cats_sorted.index(cat)
                    markup.add(types.InlineKeyboardButton(f"📁 {cat[:35]}", callback_data=f"CAT|{idx}|0|all"))
                return bot.send_message(uid, f"✨ **Magic Link Detected!**\n📍 Platform: **{escape_md(platform)}**\n📂 Choose Category for your link:", reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

    if step == "awaiting_trx":
        method_name = str(session_data.get("temp_dep_method", "Manual")).lower()
        is_local_auto = any(x in method_name for x in ['bkash', 'nagad', 'rocket', 'upay', 'bdt'])

        if is_local_auto:
            user_trx = text.upper().strip()
            trx_data = config_col.find_one({"_id": "transactions", "valid_list.trx": user_trx})
            
            # 🔥 NEW: Live Chat Button on Invalid TRX ID
            if not trx_data:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("💬 Live Chat", callback_data="NEW_TICKET"))
                return bot.send_message(uid, "❌ **INVALID TRX ID!**\nআপনার ট্রানজেকশন আইডিটি পাওয়া যায়নি। অনুগ্রহ করে সঠিক আইডি দিন।", reply_markup=markup, parse_mode="Markdown")

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
            tid = escape_md(text)
            amt = session_data.get("temp_dep_amt", 0.0)
            clear_user_session(uid)
            
            bot.send_message(uid, "✅ **Request Submitted!**\nAdmin will verify your TrxID shortly.", parse_mode="Markdown")
            admin_txt = f"🔔 **NEW DEPOSIT (MANUAL)**\n👤 User: `{uid}`\n🏦 Method: **{escape_md(session_data.get('temp_dep_method', 'Manual'))}**\n💰 Amt: **${round(float(amt), 2)}**\n🧾 TrxID: `{tid}`"
            markup = types.InlineKeyboardMarkup(row_width=2)
            app_url = BASE_URL.rstrip('/')
            markup.add(types.InlineKeyboardButton("✅ APPROVE", url=f"{app_url}/approve_dep/{uid}/{amt}/{text}"), types.InlineKeyboardButton("❌ REJECT", url=f"{app_url}/reject_dep/{uid}/{text}"))
            try: bot.send_message(ADMIN_ID, admin_txt, reply_markup=markup, parse_mode="Markdown")
            except: pass
            return

    elif step == "awaiting_deposit_amt":
        try:
            amt = float(text)
            curr_code = u.get("currency", "BDT")
            rates = get_currency_rates()
            amt_usd = amt / rates.get(curr_code, 1)
            
            s = get_settings()
            payments = s.get("payments", [])
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            for p in payments: 
                is_crypto = any(x in p['name'].lower() for x in ['usdt', 'binance', 'crypto', 'btc', 'pm', 'perfect', 'payeer'])
                if is_crypto: display_amt = f"${amt_usd:.2f}"
                else:
                    formatted_amt = int(amt) if amt.is_integer() else round(amt, 2)
                    display_amt = f"{formatted_amt} TK" if curr_code == "BDT" else f"{formatted_amt} {curr_code}"
                markup.add(types.InlineKeyboardButton(f"🏦 {p['name']} (Pay {display_amt})", callback_data=f"PAY|{amt_usd:.4f}|{amt}|{p['name']}"))
            
            if s.get("cryptomus_active") and s.get("cryptomus_merchant") and s.get("cryptomus_api"):
                markup.add(types.InlineKeyboardButton(f"🤖 Cryptomus (Pay ${amt_usd:.2f})", callback_data=f"PAY_CRYPTO|{amt_usd:.4f}|Cryptomus"))
            if s.get("coinpayments_active") and s.get("coinpayments_pub") and s.get("coinpayments_priv"):
                markup.add(types.InlineKeyboardButton(f"🪙 CoinPayments (Pay ${amt_usd:.2f})", callback_data=f"PAY_CRYPTO|{amt_usd:.4f}|CoinPayments"))
            if s.get("nowpayments_active") and s.get("nowpayments_api"):
                markup.add(types.InlineKeyboardButton(f"🚀 NowPayments (Pay ${amt_usd:.2f})", callback_data=f"PAY_CRYPTO|{amt_usd:.4f}|NowPayments"))
            if s.get("payeer_active") and s.get("payeer_merchant") and s.get("payeer_secret"):
                markup.add(types.InlineKeyboardButton(f"🅿️ Payeer (Pay ${amt_usd:.2f})", callback_data=f"PAY_CRYPTO|{amt_usd:.4f}|Payeer"))
                
            if s.get("stars_active"):
                stars_rate = s.get("stars_rate", 50)
                stars_amount = int(amt_usd * stars_rate)
                if stars_amount > 0:
                    markup.add(types.InlineKeyboardButton(f"⭐️ Telegram Stars ({stars_amount} ⭐️)", callback_data=f"PAY_STARS|{amt_usd:.4f}|{stars_amount}"))

            clear_user_session(uid)
            return bot.send_message(uid, "💳 **Select Gateway:**", reply_markup=markup, parse_mode="Markdown")
        except ValueError: return bot.send_message(uid, "⚠️ Invalid amount. Numbers only.")

    elif step == "awaiting_link":
        if not re.match(r'^(https?://|t\.me/|@|www\.)[^\s]+$', text, re.IGNORECASE):
            return bot.send_message(uid, "❌ **INVALID FORMAT DETECTED!**\n\nThe link you provided is not supported. Please make sure it starts with `https://` or `@` or `t.me/`.\n_Example: https://instagram.com/yourprofile_", parse_mode="Markdown", disable_web_page_preview=True)
            
        existing = orders_col.find_one({"uid": uid, "link": text, "status": "pending"})
        if existing:
            bot.send_message(uid, "⚠️ **DUPLICATE ORDER WARNING!**\nYou already have a pending order with this exact link. You can still proceed if you want.", parse_mode="Markdown")
        
        update_user_session(uid, {"step": "awaiting_qty", "temp_link": text})
        return bot.send_message(uid, "🔢 **Enter Quantity (Numbers only):**", parse_mode="Markdown")

    elif step == "awaiting_qty":
        try:
            qty = int(text)
            sid = session_data.get("temp_sid")
            o_type = session_data.get("order_type", "normal")
            
            services = get_cached_services()
            s = next((x for x in services if str(x.get('service', '0')) == str(sid)), None)
            if not s: return bot.send_message(uid, "❌ **Service Not Found!** Try another service.")
            
            try: min_q = int(s.get('min', 0))
            except: min_q = 0
            
            try: max_q = int(s.get('max', 9999999))
            except: max_q = 9999999
            
            if qty < min_q or qty > max_q:
                return bot.send_message(uid, f"❌ **QUANTITY OUT OF RANGE!**\nThe service provider only accepts between **{min_q}** and **{max_q}** for this service. Please enter a valid number.", parse_mode="Markdown")
            
            if o_type == "drip":
                update_user_session(uid, {"step": "awaiting_drip_runs", "temp_qty": qty})
                return bot.send_message(uid, "🔢 **Drip-Feed Runs:**\nHow many times should this quantity be sent? (e.g. 5)", parse_mode="Markdown")
            
            rate = calculate_price(s.get('rate', 0.0), u.get('spent', 0), u.get('custom_discount', 0))
            cost = (rate / 1000) * qty
            curr = u.get("currency", "BDT")
            
            if u.get('balance', 0) < cost: 
                return bot.send_message(uid, f"❌ **INSUFFICIENT FUNDS!**\n\nOrder Cost: `{fmt_curr(cost, curr)}`\nYour Balance: `{fmt_curr(u.get('balance',0), curr)}`\n\nPlease go to **💰 Deposit** to add funds.", parse_mode="Markdown")
            
            update_user_session(uid, {"draft": {"sid": sid, "link": session_data.get("temp_link"), "qty": qty, "cost": cost, "type": "normal"}, "step": ""})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ CONFIRM", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
            safe_link = escape_md(session_data.get('temp_link'))
            bot.send_message(uid, f"⚠️ **ORDER PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Service ID: `{sid}`\n🔗 Link: {safe_link}\n🔢 Quantity: {qty}\n💰 Cost: `{fmt_curr(cost, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm your order?", reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
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
            qty = session_data.get("temp_qty")
            runs = session_data.get("temp_runs")
            
            services = get_cached_services()
            s = next((x for x in services if str(x.get('service', '0')) == str(sid)), None)
            rate = calculate_price(s.get('rate', 0.0), u.get('spent', 0), u.get('custom_discount', 0))
            
            total_qty = qty * runs
            cost = (rate / 1000) * total_qty
            curr = u.get("currency", "BDT")
            
            if u.get('balance', 0) < cost: 
                return bot.send_message(uid, f"❌ **INSUFFICIENT FUNDS!**\nNeed: `{fmt_curr(cost, curr)}`", parse_mode="Markdown")
            
            update_user_session(uid, {"draft": {"sid": sid, "link": session_data.get("temp_link"), "qty": qty, "runs": runs, "interval": interval, "total_qty": total_qty, "cost": cost, "type": "drip"}, "step": ""})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ CONFIRM DRIP", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
            safe_link = escape_md(session_data.get('temp_link'))
            bot.send_message(uid, f"💧 **DRIP-FEED PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Service: `{sid}`\n🔗 Link: {safe_link}\n📦 Total Qty: {total_qty} ({qty} x {runs} runs)\n⏱️ Interval: {interval} mins\n💰 Total Cost: `{fmt_curr(cost, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm?", reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
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
            posts = session_data.get("temp_posts")
            qty = session_data.get("temp_qty")
            username = session_data.get("temp_user")
            
            services = get_cached_services()
            s = next((x for x in services if str(x.get('service', '0')) == str(sid)), None)
            rate = calculate_price(s.get('rate', 0.0), u.get('spent', 0), u.get('custom_discount', 0))
            
            total_qty = posts * qty
            cost = (rate / 1000) * total_qty
            curr = u.get("currency", "BDT")
            
            if u.get('balance', 0) < cost: 
                return bot.send_message(uid, f"❌ **INSUFFICIENT FUNDS!**\nNeed: `{fmt_curr(cost, curr)}`", parse_mode="Markdown")
            
            update_user_session(uid, {"draft": {"sid": sid, "username": username, "posts": posts, "qty": qty, "delay": delay, "cost": cost, "type": "sub"}, "step": ""})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ START SUBSCRIPTION", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
            safe_user = escape_md(username)
            bot.send_message(uid, f"🔄 **SUBSCRIPTION PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Service: `{sid}`\n👤 Target: {safe_user}\n📸 Posts: {posts}\n📦 Qty/Post: {qty}\n⏱️ Delay: {delay} mins\n💰 Estimated Total: `{fmt_curr(cost, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm?", reply_markup=markup, parse_mode="Markdown")
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
            s = next((x for x in services if str(x.get('service', '0')) == str(sid)), None)
            if not s: return bot.send_message(uid, f"❌ Error on line {idx+1}: Service ID {sid} not found.")
            
            rate = calculate_price(s.get('rate', 0.0), u.get('spent', 0), u.get('custom_discount', 0))
            cost = (rate / 1000) * qty
            total_cost += cost
            bulk_draft.append({"sid": sid, "link": link, "qty": qty, "cost": cost})
            
        curr = u.get("currency", "BDT")
        if u.get('balance', 0) < total_cost: 
            return bot.send_message(uid, f"❌ **INSUFFICIENT FUNDS!**\nNeed: `{fmt_curr(total_cost, curr)}`", parse_mode="Markdown")
            
        update_user_session(uid, {"draft_bulk": bulk_draft, "total_bulk_cost": total_cost, "step": ""})
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ CONFIRM BULK", callback_data="PLACE_BULK"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
        bot.send_message(uid, f"📝 **BULK ORDER PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n📦 Total Orders: {len(bulk_draft)}\n💰 Total Cost: `{fmt_curr(total_cost, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm Processing?", reply_markup=markup, parse_mode="Markdown")

    elif step == "awaiting_refill":
        clear_user_session(uid)
        bot.send_message(uid, "✅ Refill Requested! Admin will check it.")
        safe_text = escape_md(text)
        return bot.send_message(ADMIN_ID, f"🔄 **REFILL REQUEST:**\nOrder ID: `{safe_text}`\nBy User: `{uid}`")

    elif step == "awaiting_ticket":
        clear_user_session(uid)
        insert_res = tickets_col.insert_one({"uid": uid, "msg": text, "status": "open", "date": datetime.now()})
        ticket_id = insert_res.inserted_id
        
        safe_name = escape_md(message.from_user.first_name)
        safe_text = escape_md(text)
        admin_msg = f"📩 **NEW LIVE CHAT**\n👤 User: `{safe_name}`\n🆔 ID: `{uid}`\n🎫 Ticket: `{ticket_id}`\n\n💬 **Message:**\n{safe_text}\n\n_Reply to this message with '🆔 ID: {uid}' to send an answer directly._"
        threading.Thread(target=send_media_to_admin, args=(message, admin_msg)).start()
        return bot.send_message(uid, "✅ **Message Sent Successfully!** Admin will reply soon.\n_You can check or close this ticket from Live Chat menu._", parse_mode="Markdown")

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
            s = next((x for x in services if str(x.get('service', '0')) == query and query not in hidden), None)
            if s: 
                markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("ℹ️ Order Now", callback_data=f"INFO|{query}"))
                safe_name = escape_md(clean_service_name(s.get('name')))
                return bot.send_message(uid, f"✅ **Found:** {safe_name}", reply_markup=markup, parse_mode="Markdown")
        results = [s for s in services if str(s.get('service', '0')) not in hidden and (query in str(s.get('name', '')).lower() or query in str(s.get('category', '')).lower())][:10]
        if not results: return bot.send_message(uid, "❌ No related services found.")
        markup = types.InlineKeyboardMarkup(row_width=1)
        for s in results: 
            safe_name = escape_md(clean_service_name(s.get('name'))[:25])
            markup.add(types.InlineKeyboardButton(f"⚡ ID:{s.get('service', '0')} | {safe_name}", callback_data=f"INFO|{s.get('service', '0')}"))
        return bot.send_message(uid, f"🔍 **Top Results:**", reply_markup=markup, parse_mode="Markdown")

# 🔥 PRE-DEDUCT BALANCE TO PREVENT DOUBLE SPEND
@bot.callback_query_handler(func=lambda c: c.data in ["PLACE_ORD", "PLACE_BULK"])
def final_ord(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    
    uid = call.message.chat.id
    u = get_cached_user(uid) or {}
    session_data = get_user_session(uid)
    
    if call.data == "PLACE_BULK":
        drafts = session_data.get('draft_bulk')
        if not drafts: return bot.send_message(uid, "❌ Session expired. Please try again.")
        
        total_cost = session_data.get('total_bulk_cost', 0)
        if u.get('balance', 0) < total_cost:
            return bot.send_message(uid, "❌ Insufficient balance for this bulk order!")
            
        # 🔥 PRE-DEDUCTION
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -total_cost}})
        clear_cached_user(uid)
        clear_user_session(uid)
        
        safe_edit_message("⏳ **Processing Bulk Orders... Please wait.**", uid, call.message.message_id, parse_mode="Markdown")
        
        # 🔥 FIX: ThreadPoolExecutor ব্যবহার করা হয়েছে 
        order_executor.submit(process_bulk_background, uid, drafts, call.message.message_id, total_cost)
    else:
        draft = session_data.get('draft')
        if not draft: return bot.send_message(uid, "❌ Session expired. Please try again.")
        
        cost = draft.get('cost', 0)
        if u.get('balance', 0) < cost:
            return bot.send_message(uid, "❌ Insufficient balance for this order!")
            
        # 🔥 PRE-DEDUCTION
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -cost}})
        clear_cached_user(uid)
        clear_user_session(uid)
        
        safe_edit_message("⏳ **Processing your order securely... Please wait.**", uid, call.message.message_id, parse_mode="Markdown")
        
        # 🔥 FIX: ThreadPoolExecutor ব্যবহার করা হয়েছে
        order_executor.submit(process_order_background, uid, draft, call.message.message_id, cost)

def process_bulk_background(uid, drafts, message_id, pre_deducted_cost):
    try:
        success_count = 0
        successful_cost = 0
        points_earned = 0
        s = get_settings()
        
        for d in drafts:
            time.sleep(0.5)
            res = api.place_order(d['sid'], link=d['link'], quantity=d['qty'])
            if res and 'order' in res:
                success_count += 1
                successful_cost += d['cost']
                
                # 🔥 FIX: Safe Math Calculation
                try:
                    cost_val = float(d.get('cost', 0))
                    pts_rate = float(s.get("points_per_usd", 100))
                    pts = int(cost_val * pts_rate)
                except (ValueError, TypeError):
                    pts = 0
                    
                points_earned += pts
                orders_col.insert_one({"oid": res['order'], "uid": uid, "sid": d['sid'], "link": d['link'], "qty": d['qty'], "cost": d['cost'], "status": "pending", "date": datetime.now()})
                
        refund_amount = pre_deducted_cost - successful_cost
        update_query = {"$inc": {"spent": successful_cost, "points": points_earned}}
        if refund_amount > 0:
            update_query["$inc"]["balance"] = refund_amount
            
        users_col.update_one({"_id": uid}, update_query)
        clear_cached_user(uid)
        
        safe_edit_message(f"✅ **BULK PROCESS COMPLETE!**\n━━━━━━━━━━━━━━━━━━━━\n📦 Successful: {success_count} / {len(drafts)}\n💰 Cost: `${successful_cost:.3f}`\n🎁 Points Earned: `+{points_earned}`\n🔄 Refunded: `${refund_amount:.3f}`", uid, message_id, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Bulk Process Error: {e}")
        users_col.update_one({"_id": uid}, {"$inc": {"balance": pre_deducted_cost}})

def process_order_background(uid, draft, message_id, deducted_cost):
    try:
        s = get_settings()
        points_earned = int(float(draft['cost']) * float(s.get("points_per_usd", 100)))
        o_type = draft.get("type", "normal")
        u = get_cached_user(uid) or {}
        
        if u.get('shadow_banned'):
            fake_oid = random.randint(100000, 999999)
            users_col.update_one({"_id": uid}, {"$inc": {"spent": deducted_cost, "points": points_earned}})
            clear_cached_user(uid)
            
            insert_data = {"oid": fake_oid, "uid": uid, "sid": draft['sid'], "cost": draft['cost'], "status": "pending", "date": datetime.now(), "is_shadow": True}
            if o_type == "sub": insert_data.update({"is_sub": True, "username": draft['username'], "posts": draft['posts'], "qty": draft['qty']})
            else: insert_data.update({"link": draft.get('link'), "qty": draft.get('total_qty', draft.get('qty'))})
            
            orders_col.insert_one(insert_data)
            safe_edit_message(f"✅ **Order Placed Successfully!**\n🆔 Order ID: `{fake_oid}`\n🎁 Points Earned: `+{points_earned}`", uid, message_id, parse_mode="Markdown")
            
            # 🔥 NEW: Admin Notification for Shadow Order
            try:
                link_or_user = draft.get('link') or draft.get('username') or 'N/A'
                bot.send_message(ADMIN_ID, f"👻 **NEW SHADOW ORDER!** (Fake)\n━━━━━━━━━━━━━━━━━━━━\n👤 User ID: `{uid}`\n🆔 Order ID: `{fake_oid}`\n🚀 Service ID: `{draft['sid']}`\n🔗 Link/Target: {link_or_user}\n💰 Cost: `${draft['cost']:.3f}`", parse_mode="Markdown")
            except: pass

            proof_ch = s.get('proof_channel', '')
            if proof_ch:
                masked_id = f"***{str(uid)[-4:]}"
                user_currency = u.get("currency", "BDT")
                formatted_cost = fmt_curr(draft['cost'], user_currency)
                channel_post = f"```text\n╔════ 🟢 𝗡𝗘𝗪 𝗢𝗥𝗗𝗘𝗥 ════╗\n║ 👤 𝗜𝗗: {masked_id}\n║ 🚀 𝗦𝗲𝗿𝘃𝗶𝗰𝗲 𝗜𝗗: {draft['sid']}\n║ 💵 𝗖𝗼𝘀𝘁: {formatted_cost}\n╚════════════════════╝\n```"
                try: bot.send_message(proof_ch, channel_post, parse_mode="Markdown")
                except: pass
            return

        if o_type == "drip":
            # 🔥 NEW: API এর ডিফল্ট ড্রিপফিডের বদলে আমাদের কাস্টম ড্রিপফিড ডাটাবেসে সেভ হবে
            from loader import scheduled_col
            
            cost_per_run = float(draft['cost']) / float(draft['runs'])
            
            scheduled_col.insert_one({
                "uid": uid,
                "sid": draft['sid'],
                "link": draft['link'],
                "qty_per_run": draft['qty'],
                "runs_total": draft['runs'],
                "runs_left": draft['runs'],
                "interval": draft['interval'],
                "cost_per_run": cost_per_run,
                "status": "active",
                "next_run": datetime.now(), # প্রথম রান সাথে সাথেই শুরু হবে
                "locked": False
            })
            
            users_col.update_one({"_id": uid}, {"$inc": {"spent": deducted_cost, "points": points_earned}})
            clear_cached_user(uid)
            
            safe_edit_message(f"✅ **Auto-Repeat (Drip-Feed) Started!**\nআপনার অর্ডারটি আমাদের সিস্টেমে শিডিউল করা হয়েছে। প্রতি {draft['interval']} মিনিট পরপর {draft['qty']} কোয়ান্টিটি করে মোট {draft['runs']} বার স্বয়ংক্রিয়ভাবে অর্ডার পাঠানো হবে।\n🎁 Points Earned: `+{points_earned}`", uid, message_id, parse_mode="Markdown")
            
            try:
                bot.send_message(ADMIN_ID, f"🔔 **NEW SCHEDULED ORDER!**\n👤 User: `{uid}`\n🚀 Service: `{draft['sid']}`\n🔗 Link: {draft['link']}\n📦 Setup: {draft['qty']} x {draft['runs']} runs (Every {draft['interval']} mins)", parse_mode="Markdown")
            except: pass
            
            return
            
        elif o_type == "sub":
            res = api.place_order(draft['sid'], username=draft['username'], min=draft['qty'], max=draft['qty'], posts=draft['posts'], delay=draft['delay'])
        else:
            res = api.place_order(draft['sid'], link=draft['link'], quantity=draft['qty'])
        
        if res and 'order' in res:
            users_col.update_one({"_id": uid}, {"$inc": {"spent": deducted_cost, "points": points_earned}})
            clear_cached_user(uid)
            
            insert_data = {"oid": res['order'], "uid": uid, "sid": draft['sid'], "cost": draft['cost'], "status": "pending", "date": datetime.now()}
            if o_type == "sub": insert_data.update({"is_sub": True, "username": draft['username'], "posts": draft['posts'], "qty": draft['qty']})
            else: insert_data.update({"link": draft['link'], "qty": draft.get('total_qty', draft['qty'])})
            
            orders_col.insert_one(insert_data)
            safe_edit_message(f"✅ **Order Placed Successfully!**\n🆔 Order ID: `{res['order']}`\n🎁 Points Earned: `+{points_earned}`", uid, message_id, parse_mode="Markdown")
            
            # 🔥 NEW: Admin Notification for Real Order
            try:
                link_or_user = draft.get('link') or draft.get('username') or 'N/A'
                bot.send_message(ADMIN_ID, f"🔔 **NEW ORDER RECEIVED!**\n━━━━━━━━━━━━━━━━━━━━\n👤 User ID: `{uid}`\n🆔 Order ID: `{res['order']}`\n🚀 Service ID: `{draft['sid']}`\n🔗 Link/Target: {link_or_user}\n💰 Cost: `${draft['cost']:.3f}`", parse_mode="Markdown")
            except: pass

            proof_ch = s.get('proof_channel', '')
            if proof_ch:
                masked_id = f"***{str(uid)[-4:]}"
                user_currency = u.get("currency", "BDT")
                formatted_cost = fmt_curr(draft['cost'], user_currency)
                channel_post = f"```text\n╔════ 🟢 𝗡𝗘𝗪 𝗢𝗥𝗗𝗘𝗥 ════╗\n║ 👤 𝗜𝗗: {masked_id}\n║ 🚀 𝗦𝗲𝗿𝘃𝗶𝗰𝗲 𝗜𝗗: {draft['sid']}\n║ 💵 𝗖𝗼𝘀𝘁: {formatted_cost}\n╚════════════════════╝\n```"
                try: bot.send_message(proof_ch, channel_post, parse_mode="Markdown")
                except: pass
        else:
            users_col.update_one({"_id": uid}, {"$inc": {"balance": deducted_cost}})
            clear_cached_user(uid)
            err_msg = escape_md(res.get('error', 'API Timeout') if res else 'API Timeout')
            safe_edit_message(f"❌ **API REJECTED THE ORDER!**\n\n**Reason:** `{err_msg}`\n\n_Your balance has been refunded._", uid, message_id, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Order Background Error: {e}")
        users_col.update_one({"_id": uid}, {"$inc": {"balance": deducted_cost}})
        clear_cached_user(uid)
        safe_edit_message("❌ **Internal Server Error!** Could not process order. Your balance has been refunded.", uid, message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORD")
def cancel_ord(call):
    if is_button_locked(call.from_user.id, call.id): return
    bot.answer_callback_query(call.id)
    clear_user_session(call.message.chat.id)
    safe_edit_message("🚫 **Order Cancelled.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

