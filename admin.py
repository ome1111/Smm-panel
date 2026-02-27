import json
import time
import logging
import io
from datetime import datetime
from telebot import types

# 🔥 redis_client ও অন্যান্য ডেটাবেস কালেকশন ইম্পোর্ট
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, redis_client
from config import ADMIN_ID
import api
from utils import get_settings, fmt_curr, escape_md, clear_cached_user

# ==========================================
# 🔥 ADMIN REDIS SESSION MANAGER
# ==========================================
def set_admin_step(uid, step):
    """অ্যাডমিনের বর্তমান কমান্ড সেশন Redis এ সেভ রাখা"""
    session = {"step": step}
    redis_client.setex(f"session_{uid}", 3600, json.dumps(session))

# ==========================================
# 6. GOD MODE ADMIN COMMANDS
# ==========================================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    # সিকিউরিটি চেক: শুধু অ্যাডমিন ঢুকতে পারবে
    if str(message.chat.id) != str(ADMIN_ID): 
        return
        
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Net Worth & Stats", callback_data="ADM_STATS"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="ADM_BC"),
        types.InlineKeyboardButton("👻 Ghost Login", callback_data="ADM_GHOST"),
        types.InlineKeyboardButton("📩 Custom Alert", callback_data="ADM_ALERT"),
        types.InlineKeyboardButton("⚙️ Settings", callback_data="ADM_SETTINGS"),
        types.InlineKeyboardButton("💎 Points Setup", callback_data="ADM_POINTS")
    )
    
    # 🔥 NEW POWER FEATURES
    markup.add(
        types.InlineKeyboardButton("📅 Daily Report", callback_data="ADM_DAILY"),
        types.InlineKeyboardButton("🎧 Open Tickets", callback_data="ADM_TICKETS")
    )
    markup.add(
        types.InlineKeyboardButton("🛠 Toggle Maintenance", callback_data="ADM_MAINT"),
        types.InlineKeyboardButton("🧹 Clear Cache/Spam", callback_data="ADM_CLEAR")
    )
    
    # 🔥 Instant Sync & Deposit History
    markup.add(
        types.InlineKeyboardButton("🔄 Instant API Sync", callback_data="ADM_SYNC"),
        types.InlineKeyboardButton("💳 Deposit History (TXT)", callback_data="ADM_DEP_HIST")
    )
    
    bot.send_message(message.chat.id, f"👑 **BOSS DASHBOARD**\nUsers: `{users_col.count_documents({})}` | Orders: `{orders_col.count_documents({})}`", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ADM_"))
def admin_callbacks(call):
    uid = call.message.chat.id
    if str(uid) != str(ADMIN_ID): 
        return bot.answer_callback_query(call.id, "❌ Access Denied!")
        
    if call.data == "ADM_STATS":
        bal = sum(u.get('balance', 0) for u in users_col.find())
        spt = sum(u.get('spent', 0) for u in users_col.find())
        bot.send_message(uid, f"📈 **FINANCIAL REPORT**\n━━━━━━━━━━━━━━━━━━━━\n💰 **Bot Net Worth:** `${bal:.2f}`\n💸 **Total Sales:** `${spt:.2f}`", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        
    elif call.data == "ADM_DAILY":
        # আজকের দিনের রিপোর্ট ক্যালকুলেশন
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        new_users = users_col.count_documents({"joined": {"$gte": today}})
        today_orders = list(orders_col.find({"date": {"$gte": today}}))
        today_sales = sum(o.get('cost', 0) for o in today_orders)
        
        report_text = f"📅 **DAILY REPORT ({today.strftime('%Y-%m-%d')})**\n━━━━━━━━━━━━━━━━━━━━\n👥 **New Users Today:** `{new_users}`\n🛍️ **Orders Placed Today:** `{len(today_orders)}`\n💸 **Total Sales Today:** `${today_sales:.3f}`\n━━━━━━━━━━━━━━━━━━━━"
        bot.send_message(uid, report_text, parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        
    elif call.data == "ADM_TICKETS":
        # ওপেন সাপোর্ট টিকিটগুলো দেখানো
        tickets = list(tickets_col.find({"status": "open"}))
        if not tickets:
            bot.answer_callback_query(call.id, "✅ No pending tickets!", show_alert=True)
            return
            
        bot.answer_callback_query(call.id)
        bot.send_message(uid, f"🎧 **Showing {len(tickets)} Open Tickets:**\n_To reply, just Swipe Right (Reply) on the specific ticket message._", parse_mode="Markdown")
        
        for t in tickets:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("❌ Close Ticket", callback_data=f"CLOSE_TICKET|{t['_id']}"))
            
            safe_msg = escape_md(t.get('msg', 'No Message Provided'))
            msg_text = f"📩 **PENDING TICKET**\n🆔 ID: `{t['uid']}`\n🎫 Ticket: `{t['_id']}`\n📅 Date: `{t.get('date', datetime.now()).strftime('%Y-%m-%d %H:%M')}`\n\n💬 **Message:**\n{safe_msg}\n\n_Reply to this exact message to send an answer directly._"
            bot.send_message(uid, msg_text, reply_markup=markup, parse_mode="Markdown")
            
    elif call.data == "ADM_MAINT":
        s = get_settings()
        current_status = s.get("maintenance", False)
        new_status = not current_status
        
        config_col.update_one({"_id": "settings"}, {"$set": {"maintenance": new_status}}, upsert=True)
        from utils import update_settings_cache
        update_settings_cache("maintenance", new_status)
        
        status_text = "🔴 ENABLED (Bot is Offline)" if new_status else "🟢 DISABLED (Bot is Live)"
        bot.send_message(uid, f"🛠 **MAINTENANCE MODE:** {status_text}\n_Users can{'not' if new_status else ''} place orders now._", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        
    elif call.data == "ADM_CLEAR":
        # Redis স্প্যাম ক্যাশ ক্লিন
        keys = redis_client.keys("*cache*") + redis_client.keys("spam_*") + redis_client.keys("blocked_*")
        if keys:
            redis_client.delete(*keys)
        bot.send_message(uid, "🧹 **System Cache & Anti-Spam Blocks Cleared Successfully!**", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        
    elif call.data == "ADM_GHOST":
        set_admin_step(uid, "awaiting_ghost_uid")
        bot.send_message(uid, "👻 **GHOST LOGIN**\nEnter Target User's ID:", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        
    elif call.data == "ADM_ALERT":
        set_admin_step(uid, "awaiting_alert_uid")
        bot.send_message(uid, "📩 **CUSTOM ALERT**\nEnter Target User's ID:", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        
    elif call.data == "ADM_BC":
        set_admin_step(uid, "awaiting_bc")
        bot.send_message(uid, "📢 **BROADCAST**\nEnter message for broadcast:", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        
    elif call.data == "ADM_POINTS":
        set_admin_step(uid, "awaiting_points_cfg")
        s = get_settings()
        bot.send_message(uid, f"💎 **POINTS CONFIGURATION**\n━━━━━━━━━━━━━━━━━━━━\nCurrent Setup:\n- Per $1 Spent: `{s.get('points_per_usd', 100)} Points`\n- To get $1 Reward: `{s.get('points_to_usd_rate', 1000)} Points`\n\n**Reply with new values separated by comma (e.g., 50, 1000):**", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        
    elif call.data == "ADM_SETTINGS":
        bot.send_message(uid, "⚙️ **WEB PANEL SETTINGS**\nPlease log in to the Web Admin Panel (from your Render URL) to manage advanced settings, gateways, and profit margins securely.", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
        
    elif call.data == "ADM_SYNC":
        bot.answer_callback_query(call.id, "🔄 Fetching API data...", show_alert=False)
        msg = bot.send_message(uid, "⏳ **Force syncing services from main & external APIs...**\n_Please wait a few seconds._", parse_mode="Markdown")
        
        try:
            res = api.get_services()
            if res and isinstance(res, list) and len(res) > 0:
                combined_res = res.copy()
                s = get_settings()
                ext_apis = s.get("external_apis", [])
                
                for i, ext in enumerate(ext_apis):
                    ext_url = ext.get('url')
                    ext_key = ext.get('key')
                    target_sids = [str(sid).strip() for sid in ext.get('services', []) if str(sid).strip()]
                    
                    if ext_url and ext_key and target_sids:
                        ext_data = api.get_external_services(ext_url, ext_key)
                        if ext_data and isinstance(ext_data, list):
                            for srv in ext_data:
                                original_id = str(srv.get('service'))
                                if original_id in target_sids:
                                    new_srv = srv.copy()
                                    new_id = f"ext_{i}_{original_id}"
                                    new_srv['service'] = new_id
                                    new_srv['name'] = f"{new_srv.get('name', 'Unknown')} 🌟"
                                    combined_res.append(new_srv)

                redis_client.setex("services_cache", 43200, json.dumps(combined_res))
                config_col.update_one({"_id": "api_cache"}, {"$set": {"data": combined_res, "time": time.time()}}, upsert=True)
                
                bot.edit_message_text(f"✅ **API SYNC SUCCESSFUL!**\n━━━━━━━━━━━━━━━━━━━━\n📦 Total Services: `{len(combined_res)}`\n⚡ Live Cache has been updated.\n\n_All users can now see the latest services in 'New Order'._", uid, msg.message_id, parse_mode="Markdown")
            else:
                bot.edit_message_text("❌ **API SYNC FAILED!**\nMain panel API is slow or returned an empty list. Please try again after 1 minute.", uid, msg.message_id, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Instant Sync Error: {e}")
            bot.edit_message_text(f"❌ **System Error during sync:**\n`{str(e)}`", uid, msg.message_id, parse_mode="Markdown")
            
    elif call.data == "ADM_DEP_HIST":
        bot.answer_callback_query(call.id, "Generating File...")
        
        trx_data = config_col.find_one({"_id": "transactions"})
        if not trx_data or "valid_list" not in trx_data:
            return bot.send_message(uid, "📭 **No deposit history found.**", parse_mode="Markdown")
            
        valid_list = trx_data.get("valid_list", [])
        
        if not valid_list:
            return bot.send_message(uid, "📭 **History is empty.**", parse_mode="Markdown")

        report = "NEXUS SMM - FULL DEPOSIT HISTORY\n"
        report += "="*75 + "\n\n"
        report += f"{'Index':<6} | {'User ID':<15} | {'Amount':<10} | {'TrxID':<25} | {'Status'}\n"
        report += "-"*75 + "\n"

        for i, d in enumerate(reversed(valid_list), 1):
            u_id = str(d.get('user', 'N/A'))
            amt = str(d.get('amt', '0'))
            trx = str(d.get('trx', 'N/A'))
            status = str(d.get('status', 'used')).upper()
            
            report += f"{i:<6} | {u_id:<15} | {amt:<10} | {trx:<25} | {status}\n"

        report += "\n" + "="*75 + "\n"
        report += f"Total Records: {len(valid_list)}\n"
        report += "Generated on: " + time.strftime('%Y-%m-%d %H:%M:%S')

        output = io.BytesIO(report.encode('utf-8'))
        output.name = "deposit_history.txt"
        
        bot.send_document(
            uid, 
            output, 
            caption="📂 **Full Deposit History Report**\n\nএখানে আপনার ডাটাবেসের সব ডিপোজিট হিস্ট্রি দেওয়া হলো।",
            parse_mode="Markdown"
        )

# ==========================================
# 🔥 ADD/REMOVE BALANCE DIRECTLY FROM BOT
# ==========================================
@bot.message_handler(commands=['addbal'])
def add_balance(message):
    if str(message.chat.id) != str(ADMIN_ID): 
        return
    try:
        parts = message.text.split()
        uid = int(parts[1])
        amt = float(parts[2])
        
        users_col.update_one({"_id": uid}, {"$inc": {"balance": amt}})
        clear_cached_user(uid)
        
        bot.send_message(message.chat.id, f"✅ **SUCCESS!**\nAdded `${amt}` to user `{uid}`.", parse_mode="Markdown")
        try: bot.send_message(uid, f"💰 **WALLET UPDATE!**\nAdmin has added `${amt}` to your balance.", parse_mode="Markdown")
        except: pass
    except:
        bot.send_message(message.chat.id, "❌ **Usage:** `/addbal <user_id> <amount>`\n_Example: /addbal 123456789 5.5_", parse_mode="Markdown")

@bot.message_handler(commands=['rembal'])
def rem_balance(message):
    if str(message.chat.id) != str(ADMIN_ID): 
        return
    try:
        parts = message.text.split()
        uid = int(parts[1])
        amt = float(parts[2])
        
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -amt}})
        clear_cached_user(uid)
        
        bot.send_message(message.chat.id, f"✅ **SUCCESS!**\nRemoved `${amt}` from user `{uid}`.", parse_mode="Markdown")
        try: bot.send_message(uid, f"📉 **WALLET UPDATE!**\nAdmin has removed `${amt}` from your balance.", parse_mode="Markdown")
        except: pass
    except:
        bot.send_message(message.chat.id, "❌ **Usage:** `/rembal <user_id> <amount>`\n_Example: /rembal 123456789 5.5_", parse_mode="Markdown")
