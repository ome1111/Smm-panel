from flask import Flask, request, render_template, session, redirect, url_for
import telebot
from telebot import types
import os, time, logging
from datetime import datetime, timedelta
from config import BOT_TOKEN, ADMIN_PASSWORD, SECRET_KEY
from loader import bot, users_col, orders_col, config_col, tickets_col
import api

telebot.logger.setLevel(logging.DEBUG)
app = Flask(__name__)
app.secret_key = SECRET_KEY

# ডিফল্ট সেটিংস জেনারেটর
def get_settings():
    s = config_col.find_one({"_id": "settings"})
    if not s:
        s = {"_id": "settings", "channels": [], "profit_margin": 20, "maintenance": False, 
             "payments": [], "ref_target": 10, "ref_bonus": 5.0, "hidden_services": []}
        config_col.insert_one(s)
    return s

@app.route("/")
def index():
    return "<body style='background:#0f172a; color:#38bdf8; text-align:center; padding-top:100px;'><h1>🚀 Titan System Online!</h1><a href='/admin' style='color:#f8fafc; text-decoration:none; font-weight:bold; background:#0ea5e9; padding:10px 20px; border-radius:8px;'>Admin Panel</a></body>", 200

@app.route("/set_webhook")
def setup_webhook():
    bot.remove_webhook()
    time.sleep(1)
    url = os.environ.get('RENDER_EXTERNAL_URL')
    if url:
        bot.set_webhook(url=f"{url.rstrip('/')}/{BOT_TOKEN}")
        return "<h1>✅ Webhook Set</h1>", 200
    return "<h1>❌ Error</h1>", 500

@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    if request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([types.Update.de_json(request.get_data().decode('utf-8'))])
        return "OK", 200
    return "Forbidden", 403

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else: error = "❌ Invalid Password!"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    settings = get_settings()
    users = list(users_col.find().sort("joined", -1).limit(100))
    orders = list(orders_col.find().sort("date", -1).limit(100))
    tickets = list(tickets_col.find({"status": "open"}).sort("date", -1))
    
    total_rev = sum(u.get('spent', 0) for u in users_col.find())
    
    # 7 Days Sales Graph Data
    dates = [(datetime.now() - timedelta(days=i)).strftime('%m-%d') for i in range(6, -1, -1)]
    sales = []
    for d in dates:
        day_start = datetime.strptime(f"{datetime.now().year}-{d}", '%Y-%m-%d')
        day_total = sum(o['cost'] for o in orders_col.find({"date": {"$gte": day_start, "$lt": day_start + timedelta(days=1)}}))
        sales.append(round(day_total, 2))

    stats = {
        'users': users_col.count_documents({}), 'orders': orders_col.count_documents({}),
        'revenue': round(total_rev, 2), 'api_status': api.get_balance()
    }
    
    return render_template('admin.html', stats=stats, users=users, orders=orders, settings=settings, tickets=tickets, dates=dates, sales=sales)

# ==========================================
# SUPER CONTROL ROUTES
# ==========================================
@app.route('/update_core_settings', methods=['POST'])
def update_core_settings():
    if not session.get('logged_in'): return redirect(url_for('login'))
    profit = float(request.form.get('profit', 20))
    maint = True if request.form.get('maintenance') == 'on' else False
    ref_target = int(request.form.get('ref_target', 10))
    ref_bonus = float(request.form.get('ref_bonus', 5.0))
    
    config_col.update_one({"_id": "settings"}, {"$set": {"profit_margin": profit, "maintenance": maint, "ref_target": ref_target, "ref_bonus": ref_bonus}})
    return redirect(url_for('admin_dashboard'))

@app.route('/add_payment', methods=['POST'])
def add_payment():
    if not session.get('logged_in'): return redirect(url_for('login'))
    name = request.form.get('name')
    details = request.form.get('details')
    rate = float(request.form.get('rate', 120))
    if name and details:
        config_col.update_one({"_id": "settings"}, {"$push": {"payments": {"name": name, "details": details, "rate": rate}}})
    return redirect(url_for('admin_dashboard'))

@app.route('/del_payment/<name>')
def del_payment(name):
    if not session.get('logged_in'): return redirect(url_for('login'))
    config_col.update_one({"_id": "settings"}, {"$pull": {"payments": {"name": name}}})
    return redirect(url_for('admin_dashboard'))

@app.route('/toggle_service', methods=['POST'])
def toggle_service():
    if not session.get('logged_in'): return redirect(url_for('login'))
    sid = request.form.get('sid')
    action = request.form.get('action')
    if action == 'hide': config_col.update_one({"_id": "settings"}, {"$addToSet": {"hidden_services": sid}})
    else: config_col.update_one({"_id": "settings"}, {"$pull": {"hidden_services": sid}})
    return redirect(url_for('admin_dashboard'))

@app.route('/reply_ticket/<tid>', methods=['POST'])
def reply_ticket(tid):
    if not session.get('logged_in'): return redirect(url_for('login'))
    reply = request.form.get('reply')
    ticket = tickets_col.find_one({"_id": tid})
    if ticket and reply:
        try: bot.send_message(ticket['uid'], f"🎧 **Support Reply:**\n━━━━━━━━━━━━━━━━━━━━\n{reply}", parse_mode="Markdown")
        except: pass
        tickets_col.update_one({"_id": tid}, {"$set": {"status": "closed", "reply": reply}})
    return redirect(url_for('admin_dashboard'))

# ... (Previous routes like add_balance, refund_order, ban_user remain exactly same as before)
@app.route('/add_balance/<int:user_id>', methods=['POST'])
def add_balance(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        amount = float(request.form.get('amount', 0))
        users_col.update_one({"_id": user_id}, {"$inc": {"balance": amount}})
        bot.send_message(user_id, f"🎉 Admin adjusted balance by ${amount}")
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
            bot.send_message(order['uid'], f"💸 **REFUNDED!** Order: `{oid}`")
    except: pass
    return redirect(url_for('admin_dashboard'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
