import json
from telebot import types
# 🔥 redis_client ইম্পোর্ট করা হলো
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, redis_client
from config import *
import api
from utils import *

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
    if str(message.chat.id) != str(ADMIN_ID): return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Net Worth & Stats", callback_data="ADM_STATS"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="ADM_BC"),
        types.InlineKeyboardButton("👻 Ghost Login", callback_data="ADM_GHOST"),
        types.InlineKeyboardButton("📩 Custom Alert", callback_data="ADM_ALERT"),
        types.InlineKeyboardButton("⚙️ Settings", callback_data="ADM_SETTINGS"),
        types.InlineKeyboardButton("💎 Points Setup", callback_data="ADM_POINTS"),
        types.InlineKeyboardButton("🔄 Force API Sync", callback_data="ADM_SYNC") # 🔥 NEW BUTTON
    )
    bot.send_message(message.chat.id, f"👑 **BOSS DASHBOARD**\nUsers: `{users_col.count_documents({})}`\nSelect an action:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ADM_"))
def admin_callbacks(call):
    if str(call.message.chat.id) != str(ADMIN_ID): return
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    
    if call.data == "ADM_HOME":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 Net Worth & Stats", callback_data="ADM_STATS"),
            types.InlineKeyboardButton("📢 Broadcast", callback_data="ADM_BC"),
            types.InlineKeyboardButton("👻 Ghost Login", callback_data="ADM_GHOST"),
            types.InlineKeyboardButton("📩 Custom Alert", callback_data="ADM_ALERT"),
            types.InlineKeyboardButton("⚙️ Settings", callback_data="ADM_SETTINGS"),
            types.InlineKeyboardButton("💎 Points Setup", callback_data="ADM_POINTS"),
            types.InlineKeyboardButton("🔄 Force API Sync", callback_data="ADM_SYNC") # 🔥 NEW BUTTON
        )
        bot.edit_message_text(f"👑 **BOSS DASHBOARD**\nUsers: `{users_col.count_documents({})}`\nSelect an action:", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        
    elif call.data == "ADM_SETTINGS":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("💰 Profit Margin", callback_data="ADM_PROFIT"),
            types.InlineKeyboardButton("🚧 Maint. Mode", callback_data="ADM_MAIN"),
            types.InlineKeyboardButton("🎁 Welcome Bonus", callback_data="ADM_WBONUS"),
            types.InlineKeyboardButton("⚡ Flash Sale", callback_data="ADM_FSALE"),
            types.InlineKeyboardButton("🌟 Best Choice SIDs", callback_data="ADM_BEST"),
            types.InlineKeyboardButton("🔙 Back to Main", callback_data="ADM_HOME")
        )
        bot.edit_message_text("⚙️ **ADVANCED BOT SETTINGS**\nControl automation features here:", uid, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        
    elif call.data == "ADM_PROFIT":
        set_admin_step(uid, "awaiting_profit") 
        bot.send_message(uid, "💰 **PROFIT MARGIN**\nEnter new profit margin percentage (e.g. 20.5):")

    elif call.data == "ADM_WBONUS":
        set_admin_step(uid, "awaiting_wbonus") 
        bot.send_message(uid, "🎁 **WELCOME BONUS**\nEnter new welcome bonus amount (e.g. 0.5):")

    elif call.data == "ADM_FSALE":
        set_admin_step(uid, "awaiting_fsale") 
        bot.send_message(uid, "⚡ **FLASH SALE**\nEnter flash sale discount percentage (e.g. 10.0):")

    elif call.data == "ADM_BEST":
        set_admin_step(uid, "awaiting_best") 
        bot.send_message(uid, "🌟 **BEST CHOICE SIDs**\nEnter comma-separated Service IDs (e.g. 10, 25, 102):")

    elif call.data == "ADM_STATS":
        bal = sum(u.get('balance', 0) for u in users_col.find())
        spt = sum(u.get('spent', 0) for u in users_col.find())
        bot.send_message(uid, f"📈 **FINANCIAL REPORT**\n\n💰 **Bot Net Worth:** `${bal:.2f}`\n💸 **Total Sales:** `${spt:.2f}`", parse_mode="Markdown")
        
    elif call.data == "ADM_GHOST":
        set_admin_step(uid, "awaiting_ghost_uid") 
        bot.send_message(uid, "👻 **GHOST LOGIN**\nEnter Target User's ID:")
        
    elif call.data == "ADM_ALERT":
        set_admin_step(uid, "awaiting_alert_uid") 
        bot.send_message(uid, "📩 **CUSTOM ALERT**\nEnter Target User's ID:")
        
    elif call.data == "ADM_BC":
        set_admin_step(uid, "awaiting_bc") 
        bot.send_message(uid, "📢 **Enter message for broadcast:**")
        
    elif call.data == "ADM_POINTS":
        set_admin_step(uid, "awaiting_points_cfg") 
        s = get_settings()
        bot.send_message(uid, f"💎 **POINTS CONFIGURATION**\nCurrent Setup:\n- Per $1 Spent: `{s.get('points_per_usd', 100)} Points`\n- To get $1 Reward: `{s.get('points_to_usd_rate', 1000)} Points`\n\n**Reply with new values separated by comma (e.g., 50, 2000):**", parse_mode="Markdown")
        
    elif call.data == "ADM_MAIN":
        s = get_settings()
        ns = not s.get('maintenance', False)
        config_col.update_one({"_id": "settings"}, {"$set": {"maintenance": ns}})
        update_settings_cache("maintenance", ns)
        bot.send_message(uid, f"✅ Maintenance Mode is now: {'**ON**' if ns else '**OFF**'}", parse_mode="Markdown")

    # 🔥 NEW: Force API Sync Action
    elif call.data == "ADM_SYNC":
        bot.send_message(uid, "⏳ **API SYNC INITIATED**\nFetching services from Main Panel and Custom Providers...", parse_mode="Markdown")
        success = force_sync_services()
        if success:
            bot.send_message(uid, "✅ **API Sync Successful!**\nAll menus and services are now up to date in the bot.", parse_mode="Markdown")
        else:
            bot.send_message(uid, "❌ **API Sync Failed!**\nPlease check provider connections or API keys in the Web Panel.", parse_mode="Markdown")
