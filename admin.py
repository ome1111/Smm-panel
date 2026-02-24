import json
import logging
from telebot import types

# 🔥 redis_client ও অন্যান্য ডেটাবেস কালেকশন ইম্পোর্ট
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, redis_client
from config import ADMIN_ID
from utils import get_settings, fmt_curr, escape_md

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
        
    elif call.data == "ADM_GHOST":
        set_admin_step(uid, "awaiting_ghost_uid")
        bot.send_message(uid, "👻 **GHOST LOGIN**\nEnter Target User's ID:", parse_mode="Markdown")
        
    elif call.data == "ADM_ALERT":
        set_admin_step(uid, "awaiting_alert_uid")
        bot.send_message(uid, "📩 **CUSTOM ALERT**\nEnter Target User's ID:", parse_mode="Markdown")
        
    elif call.data == "ADM_BC":
        set_admin_step(uid, "awaiting_bc")
        bot.send_message(uid, "📢 **BROADCAST**\nEnter message for broadcast:", parse_mode="Markdown")
        
    elif call.data == "ADM_POINTS":
        set_admin_step(uid, "awaiting_points_cfg")
        s = get_settings()
        bot.send_message(uid, f"💎 **POINTS CONFIGURATION**\n━━━━━━━━━━━━━━━━━━━━\nCurrent Setup:\n- Per $1 Spent: `{s.get('points_per_usd', 100)} Points`\n- To get $1 Reward: `{s.get('points_to_usd_rate', 1000)} Points`\n\n**Reply with new values separated by comma (e.g., 50, 1000):**", parse_mode="Markdown")
        
    elif call.data == "ADM_SETTINGS":
        bot.send_message(uid, "⚙️ **WEB PANEL SETTINGS**\nPlease log in to the Web Admin Panel (from your Render URL) to manage advanced settings, gateways, and profit margins securely.", parse_mode="Markdown")
        
    bot.answer_callback_query(call.id)
