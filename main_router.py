import re
import math
import random
from datetime import datetime, timedelta
from telebot import types

from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col
from config import *
import api

# utils.py থেকে সব হেল্পার ফাংশন ইমপোর্ট করা হলো
from utils import *

# ==========================================
# 3. FORCE SUB & START LOGIC
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    users_col.update_one({"_id": uid}, {"$set": {"last_active": datetime.now()}, "$unset": {"step": "", "temp_sid": "", "temp_link": ""}}, upsert=True)
    if check_spam(uid) or check_maintenance(uid): return
    
    hour = datetime.now().hour
    greeting = "🌅 Good Morning" if hour < 12 else "☀️ Good Afternoon" if hour < 18 else "🌙 Good Evening"
    
    user = users_col.find_one({"_id": uid})
    args = message.text.split()
    referrer = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid else None

    if not user:
        users_col.insert_one({"_id": uid, "name": message.from_user.first_name, "balance": 0.0, "spent": 0.0, "points": 0, "currency": "BDT", "ref_by": referrer, "ref_paid": False, "ref_earnings": 0.0, "joined": datetime.now(), "favorites": [], "custom_discount": 0.0, "shadow_banned": False, "tier_override": None, "welcome_paid": False})
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
            else:
                users_col.update_one({"_id": uid}, {"$set": {"welcome_paid": True}})
                
        if user and user.get("ref_by") and not user.get("ref_paid"):
            ref_bonus = s.get("ref_bonus", 0.0)
            if ref_bonus > 0:
                users_col.update_one({"_id": user["ref_by"]}, {"$inc": {"balance": ref_bonus, "ref_earnings": ref_bonus}})
                users_col.update_one({"_id": uid}, {"$set": {"ref_paid": True}})
                try: bot.send_message(user["ref_by"], f"🎉 **REFERRAL SUCCESS!**\nUser `{uid}` verified their account. You earned `${ref_bonus}`!", parse_mode="Markdown")
                except: pass
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
    try: cat_idx = sorted(list(set(x['category'] for x in services))).index(s['category'])
    except: cat_idx = 0
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"CAT|{cat_idx}|0"))
    if call.message.text and "YOUR ORDERS" in call.message.text: bot.send_message(call.message.chat.id, txt, reply_markup=markup, parse_mode="Markdown")
    else: bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ORD|"))
def start_ord(call):
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"step": "awaiting_link", "temp_sid": sid}})
    bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link:**\n_(Example: https://t.me/yourchannel)_", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("REORDER|"))
def reorder_callback(call):
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"step": "awaiting_link", "temp_sid": sid}})
    bot.send_message(call.message.chat.id, "🔗 **Paste the Target Link for Reorder:**\n_(Example: https://t.me/yourchannel)_", parse_mode="Markdown")

# ==========================================
# 5. UNIVERSAL BUTTONS, PROFILE & POINTS
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
        st_emoji = "⏳"
        if st == "completed": st_emoji = "✅"
        elif st in ["canceled", "refunded", "fail"]: st_emoji = "❌"
        elif st in ["in progress", "processing"]: st_emoji = "🔄"
        elif st == "partial": st_emoji = "⚠️"
        
        txt += f"🆔 `{o['oid']}` | 💰 `{fmt_curr(o['cost'], curr)}`\n🔗 {str(o.get('link', 'N/A'))[:25]}...\n🏷 Status: {st_emoji} {st.upper()}\n\n"
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
    else: bot.answer_callback_query(call.id, "❌ Refill not available or requested too early.", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("MYORD|"))
def my_orders_pagination(call):
    page = int(call.data.split("|")[1])
    txt, markup = fetch_orders_page(call.message.chat.id, page)
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data == "REDEEM_POINTS")
def redeem_points(call):
    u = users_col.find_one({"_id": call.message.chat.id})
    pts = u.get("points", 0)
    s = get_settings()
    rate = s.get("points_to_usd_rate", 1000)
    if pts < rate: return bot.answer_callback_query(call.id, f"❌ Minimum {rate} Points required to redeem.", show_alert=True)
    reward = pts / float(rate)
    users_col.update_one({"_id": call.message.chat.id}, {"$inc": {"balance": reward}, "$set": {"points": 0}})
    bot.answer_callback_query(call.id, f"✅ Redeemed {pts} Points for ${reward:.2f}!", show_alert=True)
    bot.delete_message(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("FAV_ADD|"))
def add_to_favorites(call):
    bot.answer_callback_query(call.id, "⭐ Added to Favorites!", show_alert=True)
    sid = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$addToSet": {"favorites": sid}})

@bot.callback_query_handler(func=lambda c: c.data.startswith("SET_CURR|"))
def set_currency_callback(call):
    curr = call.data.split("|")[1]
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"currency": curr}})
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
    users_col.update_one({"_id": call.message.chat.id}, {"$set": {"step": "awaiting_trx", "temp_dep_amt": amt_usd, "temp_dep_method": method}})
    bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

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
            if s: markup.add(types.InlineKeyboardButton(f"⭐ ID:{s['service']} | {clean_service_name(s['name'])[:25]}", callback_data=f"INFO|{s['service']}"))
        bot.send_message(uid, "⭐ **YOUR SAVED SERVICES:**", reply_markup=markup, parse_mode="Markdown")

    elif message.text == "🤝 Affiliate":
        ref_link = f"https://t.me/{bot.get_me().username}?start={uid}"
        s = get_settings()
        bot.send_message(uid, f"🤝 **AFFILIATE NETWORK**\n━━━━━━━━━━━━━━━━━━━━\n🔗 **Your Unique Link:**\n`{ref_link}`\n\n💰 **Monthly Earned:** `{fmt_curr(u.get('ref_earnings', 0.0), curr)}`\n👥 **Total Verified Invites:** `{users_col.count_documents({'ref_by': uid, 'ref_paid': True})}`\n\n_💡 Earn ${s.get('ref_bonus', 0.0)} instantly when they verify + {s.get('dep_commission', 0.0)}% lifetime commission!_", parse_mode="Markdown", disable_web_page_preview=True)

    elif message.text == "🎟️ Voucher":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_voucher"}})
        bot.send_message(uid, "🎁 **REDEEM VOUCHER**\nEnter your secret promo code below:", parse_mode="Markdown")

    elif message.text == "🔍 Smart Search":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_search"}})
        bot.send_message(uid, "🔍 **SMART SEARCH**\nEnter Service ID or Keyword (e.g., 'Instagram'):", parse_mode="Markdown")
        
    elif message.text == "💬 Live Chat":
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_ticket"}})
        bot.send_message(uid, "💬 **LIVE SUPPORT**\nSend your message here. Our Admins will reply directly!", parse_mode="Markdown")

# ==========================================
# 7. MASTER ROUTER (Smart Errors & Ordering)
# ==========================================
@bot.message_handler(func=lambda m: True)
def text_router(message):
    uid = message.chat.id
    text = message.text.strip() if message.text else ""
    if text.startswith('/'): return
    
    # 🔥 FIXED: Admin Direct Reply Logic using message reply
    if str(uid) == str(ADMIN_ID) and message.reply_to_message:
        reply_text = message.reply_to_message.text
        if "🆔 ID: " in reply_text or "ID: " in reply_text:
            try:
                if "🆔 ID: " in reply_text:
                    target_uid = int(reply_text.split("🆔 ID: ")[1].split("\n")[0].strip().replace("`", ""))
                else:
                    target_uid = int(reply_text.split("ID: ")[1].split("\n")[0].strip().replace("`", ""))
                    
                bot.send_message(target_uid, f"👨‍💻 **ADMIN REPLY:**\n━━━━━━━━━━━━━━━━━━━━\n{text}", parse_mode="Markdown")
                # Auto close the ticket in database when Admin replies directly from Telegram
                tickets_col.update_many({"uid": target_uid, "status": "open"}, {"$set": {"status": "closed", "reply": text}})
                return bot.send_message(ADMIN_ID, f"✅ Reply sent successfully to user `{target_uid}`!")
            except Exception as e: 
                pass

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

        elif step == "awaiting_points_cfg":
            try:
                p_usd, p_rate = text.split(",")
                config_col.update_one({"_id": "settings"}, {"$set": {"points_per_usd": int(p_usd.strip()), "points_to_usd_rate": int(p_rate.strip())}})
                users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
                return bot.send_message(uid, "✅ Points System Updated!")
            except: return bot.send_message(uid, "❌ Format error. Use comma (e.g. 100, 1000)")

    # --- AUTO PAYMENT CLAIM LOGIC ---
    if step == "awaiting_trx":
        method_name = str(u.get("temp_dep_method", "Manual")).lower()
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
            bdt_rate = s.get('bdt_rate', 120.0)
            usd_to_add = entry['amt'] / bdt_rate
            
            config_col.update_one({"_id": "transactions", "valid_list.trx": user_trx}, {"$set": {"valid_list.$.status": "used", "valid_list.$.user": uid}})
            users_col.update_one({"_id": uid}, {"$inc": {"balance": usd_to_add}, "$unset": {"step": "", "temp_dep_amt": "", "temp_dep_method": ""}})
            
            bot.send_message(uid, f"✅ **DEPOSIT SUCCESS!**\n💰 Amount: `{entry['amt']} TK`\n💵 Added: `${usd_to_add:.2f}`", parse_mode="Markdown")
            bot.send_message(ADMIN_ID, f"🔔 **AUTO DEP:** {uid} added ${usd_to_add:.2f} (TrxID: {user_trx})")
            return
            
        else:
            tid = text
            amt = u.get("temp_dep_amt", 0.0)
            users_col.update_one({"_id": uid}, {"$unset": {"step": "", "temp_dep_amt": "", "temp_dep_method": ""}})
            
            bot.send_message(uid, "✅ **Request Submitted!**\nAdmin will verify your TrxID shortly.", parse_mode="Markdown")
            admin_txt = f"🔔 **NEW DEPOSIT (MANUAL)**\n👤 User: `{uid}`\n🏦 Method: **{u.get('temp_dep_method', 'Manual')}**\n💰 Amt: **${round(float(amt), 2)}**\n🧾 TrxID: `{tid}`"
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
            payments = get_settings().get("payments", [])
            markup = types.InlineKeyboardMarkup(row_width=1)
            for p in payments: 
                is_crypto = any(x in p['name'].lower() for x in ['usdt', 'binance', 'crypto', 'btc', 'pm', 'perfect', 'payeer'])
                display_amt = f"${amt_usd:.2f}" if is_crypto else f"{round(amt_usd * float(p['rate']), 2)} {curr_code}"
                markup.add(types.InlineKeyboardButton(f"🏦 {p['name']} (Pay {display_amt})", callback_data=f"PAY|{amt_usd}|{p['name']}"))
            users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
            return bot.send_message(uid, "💳 **Select Gateway:**", reply_markup=markup, parse_mode="Markdown")
        except ValueError: return bot.send_message(uid, "⚠️ Invalid amount. Numbers only.")

    elif step == "awaiting_link":
        if not re.match(r'^(https?://|t\.me/|@|www\.)[^\s]+$', text, re.IGNORECASE):
            return bot.send_message(uid, "❌ **INVALID FORMAT DETECTED!**\n\nThe link you provided is not supported. Please make sure it starts with `https://` or `@` or `t.me/`.\n_Example: https://instagram.com/yourprofile_", parse_mode="Markdown", disable_web_page_preview=True)
            
        existing = orders_col.find_one({"uid": uid, "link": text, "status": "pending"})
        if existing:
            bot.send_message(uid, "⚠️ **DUPLICATE ORDER WARNING!**\nYou already have a pending order with this exact link. You can still proceed if you want.", parse_mode="Markdown")
        
        users_col.update_one({"_id": uid}, {"$set": {"step": "awaiting_qty", "temp_link": text}})
        return bot.send_message(uid, "🔢 **Enter Quantity (Numbers only):**", parse_mode="Markdown")

    elif step == "awaiting_qty":
        try:
            qty = int(text)
            sid, link = u.get("temp_sid"), u.get("temp_link")
            services = get_cached_services()
            s = next((x for x in services if str(x['service']) == str(sid)), None)
            
            if qty < int(s['min']) or qty > int(s['max']):
                return bot.send_message(uid, f"❌ **QUANTITY OUT OF RANGE!**\nThe service provider only accepts between **{s['min']}** and **{s['max']}** for this service. Please enter a valid number.", parse_mode="Markdown")
            
            rate = calculate_price(s['rate'], u.get('spent', 0), u.get('custom_discount', 0))
            cost = (rate / 1000) * qty
            curr = u.get("currency", "BDT")
            
            if u.get('balance', 0) < cost: 
                return bot.send_message(uid, f"❌ **INSUFFICIENT FUNDS!**\n\nOrder Cost: `{fmt_curr(cost, curr)}`\nYour Balance: `{fmt_curr(u.get('balance',0), curr)}`\n\nPlease go to **💰 Deposit** to add funds.", parse_mode="Markdown")
            
            users_col.update_one({"_id": uid}, {"$set": {"draft": {"sid": sid, "link": link, "qty": qty, "cost": cost}, "step": ""}})
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ CONFIRM", callback_data="PLACE_ORD"), types.InlineKeyboardButton("❌ CANCEL", callback_data="CANCEL_ORD"))
            bot.send_message(uid, f"⚠️ **ORDER PREVIEW**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Service ID: `{sid}`\n🔗 Link: {link}\n🔢 Quantity: {qty}\n💰 Cost: `{fmt_curr(cost, curr)}`\n━━━━━━━━━━━━━━━━━━━━\nConfirm your order?", reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        except: bot.send_message(uid, "⚠️ **ERROR:** Please enter valid numbers only.")

    elif step == "awaiting_refill":
        users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
        bot.send_message(uid, "✅ Refill Requested! Admin will check it.")
        return bot.send_message(ADMIN_ID, f"🔄 **REFILL REQUEST:**\nOrder ID: `{text}`\nBy User: `{uid}`")

    # 🔥 FIXED: Send Live Chat message to Admin Inbox for direct reply
    elif step == "awaiting_ticket":
        users_col.update_one({"_id": uid}, {"$unset": {"step": ""}})
        
        # Save to database to keep ticket history in your web panel
        tickets_col.insert_one({"uid": uid, "msg": text, "status": "open", "date": datetime.now()})
        
        # Send instant notification to Admin Telegram ID
        user_name = message.from_user.first_name
        admin_msg = f"📩 **NEW LIVE CHAT**\n👤 User: `{user_name}`\n🆔 ID: `{uid}`\n\n💬 **Message:**\n{text}\n\n_Reply to this message to send an answer directly._"
        try: bot.send_message(ADMIN_ID, admin_msg, parse_mode="Markdown")
        except: pass
        
        return bot.send_message(uid, "✅ **Message Sent Successfully!** Admin will reply soon.", parse_mode="Markdown")

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

@bot.callback_query_handler(func=lambda c: c.data == "PLACE_ORD")
def final_ord(call):
    uid = call.message.chat.id
    u = users_col.find_one({"_id": uid})
    draft = u.get('draft')
    if not draft: return bot.answer_callback_query(call.id, "❌ Session expired.")
    
    bot.edit_message_text("🛒 **Processing your order with API...**", uid, call.message.message_id, parse_mode="Markdown")
    curr = u.get("currency", "BDT")
    
    services = get_cached_services()
    srv = next((x for x in services if str(x['service']) == str(draft['sid'])), None)
    srv_name = clean_service_name(srv['name']) if srv else f"ID: {draft['sid']}"
    masked_id = f"***{str(uid)[-4:]}"
    short_srv = srv_name[:22] + ".." if len(srv_name) > 22 else srv_name
    cost_str = fmt_curr(draft['cost'], curr)
    
    s = get_settings()
    proof_ch = s.get('proof_channel', '')
    channel_post = f"```text\n╔════ 🟢 𝗡𝗘𝗪 𝗢𝗥𝗗𝗘𝗥 ════╗\n║ 👤 𝗜𝗗: {masked_id}\n║ 🚀 𝗦𝗲𝗿𝘃𝗶𝗰𝗲: {short_srv}\n║ 📦 𝗤𝘁𝘆: {int(draft['qty'])}\n║ 💵 𝗖𝗼𝘀𝘁: {cost_str}\n╚════════════════════╝\n```"
    points_earned = int(draft['cost'] * s.get("points_per_usd", 100))

    if u.get('shadow_banned'):
        fake_oid = random.randint(100000, 999999)
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost'], "points": points_earned}, "$unset": {"draft": ""}})
        orders_col.insert_one({"oid": fake_oid, "uid": uid, "sid": draft['sid'], "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], "status": "pending", "date": datetime.now(), "is_shadow": True})
        bot.edit_message_text(f"✅ **Order Placed Successfully!**\n🆔 Order ID: `{fake_oid}`\n🎁 Points Earned: `+{points_earned}`", uid, call.message.message_id, parse_mode="Markdown")
        if proof_ch:
            try: bot.send_message(proof_ch, channel_post, parse_mode="Markdown")
            except: pass
        return

    res = api.place_order(draft['sid'], draft['link'], draft['qty'])
    if res and 'order' in res:
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -draft['cost'], "spent": draft['cost'], "points": points_earned}, "$unset": {"draft": ""}})
        orders_col.insert_one({"oid": res['order'], "uid": uid, "sid": draft['sid'], "link": draft['link'], "qty": draft['qty'], "cost": draft['cost'], "status": "pending", "date": datetime.now()})
        bot.edit_message_text(f"✅ **Order Placed Successfully!**\n🆔 Order ID: `{res['order']}`\n🎁 Points Earned: `+{points_earned}`", uid, call.message.message_id, parse_mode="Markdown")
        if proof_ch:
            try: bot.send_message(proof_ch, channel_post, parse_mode="Markdown")
            except: pass
    else:
        err_msg = res.get('error', 'API Timeout') if res else 'API Timeout'
        bot.edit_message_text(f"❌ **API REJECTED THE ORDER!**\n\n**Reason:** `{err_msg}`\n\nPlease check your link or try another service.", uid, call.message.message_id, parse_mode="Markdown")
        users_col.update_one({"_id": uid}, {"$unset": {"draft": "", "step": ""}})

@bot.callback_query_handler(func=lambda c: c.data == "CANCEL_ORD")
def cancel_ord(call):
    users_col.update_one({"_id": call.message.chat.id}, {"$unset": {"draft": "", "step": ""}})
    bot.edit_message_text("🚫 **Order Cancelled.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
