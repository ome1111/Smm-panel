from flask import Flask, request, render_template, session, redirect, url_for
import telebot
from telebot import types
import os, time, logging
from config import BOT_TOKEN, ADMIN_PASSWORD, SECRET_KEY
from loader import bot, users_col, orders_col, config_col
import handlers
import api

telebot.logger.setLevel(logging.DEBUG)
app = Flask(__name__)
app.secret_key = SECRET_KEY

@app.route("/")
def index():
    return "<body style='background:#0f172a; color:#38bdf8; text-align:center; padding-top:100px;'><h1>🚀 NEXUS System Online!</h1><a href='/admin' style='color:#f8fafc; text-decoration:none; font-weight:bold; background:#0ea5e9; padding:10px 20px; border-radius:8px;'>Admin Panel</a></body>", 200

@app.route("/set_webhook")
def setup_webhook():
    bot.remove_webhook()
    time.sleep(1)
    url = os.environ.get('RENDER_EXTERNAL_URL')
    if url:
        webhook_url = f"{url.rstrip('/')}/{BOT_TOKEN}"
        bot.set_webhook(url=webhook_url)
        return f"<h1>✅ Webhook Set to: {webhook_url}</h1>", 200
    return "<h1>❌ Error: RENDER_EXTERNAL_URL missing</h1>", 500

@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = "❌ Invalid Admin Password!"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    try:
        recent_users = list(users_col.find().sort("joined", -1).limit(100))
        recent_orders = list(orders_col.find().sort("date", -1).limit(100))
        total_rev = sum(u.get('spent', 0) for u in users_col.find())
        settings = config_col.find_one({"_id": "settings"}) or {}
        channels = settings.get("channels", [])
        
        stats = {
            'users': users_col.count_documents({}),
            'orders': orders_col.count_documents({}),
            'revenue': round(total_rev, 2),
            'api_status': api.get_balance()
        }
    except Exception as e:
        stats = {'users': 0, 'orders': 0, 'revenue': 0, 'api_status': "API Error"}
        recent_users, recent_orders, channels = [], [], []

    return render_template('admin.html', stats=stats, users=recent_users, orders=recent_orders, channels=channels)

# ==========================================
# Force Sub Channels Manager
# ==========================================
@app.route('/add_channel', methods=['POST'])
def add_channel():
    if not session.get('logged_in'): return redirect(url_for('login'))
    ch = request.form.get('channel', '').strip()
    if ch:
        if not ch.startswith('@'): ch = '@' + ch
        config_col.update_one({"_id": "settings"}, {"$addToSet": {"channels": ch}}, upsert=True)
    return redirect(url_for('admin_dashboard'))

@app.route('/del_channel/<channel>')
def del_channel(channel):
    if not session.get('logged_in'): return redirect(url_for('login'))
    ch = '@' + channel
    config_col.update_one({"_id": "settings"}, {"$pull": {"channels": ch}})
    return redirect(url_for('admin_dashboard'))

# ==========================================
# Other Admin Functions
# ==========================================
@app.route('/add_balance/<int:user_id>', methods=['POST'])
def add_balance(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        amount = float(request.form.get('amount', 0))
        users_col.update_one({"_id": user_id}, {"$inc": {"balance": amount}})
        bot.send_message(user_id, f"🎉 **Admin adjusted your balance by ${amount}**", parse_mode="Markdown")
    except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/ban_user/<int:user_id>')
def ban_user(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    users_col.update_one({"_id": user_id}, {"$set": {"balance": -99999}})
    try: bot.send_message(user_id, "🚫 **YOU HAVE BEEN BANNED.**", parse_mode="Markdown")
    except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/refund_order/<oid>')
def refund_order(oid):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        order = orders_col.find_one({"oid": int(oid)})
        if order and order.get('status') != 'Refunded':
            users_col.update_one({"_id": order['uid']}, {"$inc": {"balance": order['cost'], "spent": -order['cost']}})
            orders_col.update_one({"oid": int(oid)}, {"$set": {"status": "Refunded"}})
            bot.send_message(order['uid'], f"💸 **ORDER REFUNDED!**\nID: `{oid}`\nAmount: `${order['cost']}`", parse_mode="Markdown")
    except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/send_broadcast', methods=['POST'])
def send_broadcast():
    if not session.get('logged_in'): return redirect(url_for('login'))
    msg = request.form.get('msg')
    if msg:
        import threading
        def broadcast_task():
            for user in users_col.find({}):
                try: bot.send_message(user['_id'], f"📢 **ADMIN NOTICE**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
                except: pass
        threading.Thread(target=broadcast_task).start()
    return redirect(url_for('admin_dashboard'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
