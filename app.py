from flask import Flask, request, render_template, session, redirect, url_for
import telebot
from telebot import types
import os, time, logging, random
from datetime import datetime, timedelta
from config import BOT_TOKEN, ADMIN_PASSWORD, SECRET_KEY
from loader import bot, users_col, orders_col, config_col, tickets_col
import api
import threading
from bson.objectid import ObjectId
import handlers # এটি বটের সব ফাংশনালিটি কানেক্ট করে

# Logging Setup
logging.basicConfig(level=logging.INFO)
telebot.logger.setLevel(logging.DEBUG)

app = Flask(__name__)
app.secret_key = SECRET_KEY

# 🛠 সিস্টেম সেটিংস লোডার (ডাটাবেস থেকে)
def get_settings():
    s = config_col.find_one({"_id": "settings"})
    if not s:
        # ডিফল্ট ভ্যালু যদি ডাটাবেসে কিছু না থাকে
        s = {
            "_id": "settings", 
            "channels": [], 
            "profit_margin": 20.0, 
            "maintenance": False, 
            "payments": [], 
            "ref_target": 10, 
            "ref_bonus": 5.0, 
            "dep_commission": 5.0, 
            "hidden_services": []
        }
        config_col.insert_one(s)
    return s

# ==========================================
# ১. WEBHOOK & INDEX ROUTES
# ==========================================

@app.route("/")
def index():
    return "<body style='background:#020617; color:#38bdf8; text-align:center; padding-top:100px; font-family:sans-serif;'><h1>🚀 Titan System is Fully Operational</h1><p style='color:#64748b;'>NEXUS SMM Bot Engine is running perfectly.</p><br><a href='/admin' style='color:#f8fafc; text-decoration:none; font-weight:bold; background:#0ea5e9; padding:12px 24px; border-radius:10px; box-shadow: 0 4px 14px 0 rgba(14, 165, 233, 0.4);'>Access Titan Panel</a></body>", 200

@app.route("/set_webhook")
def setup_webhook():
    bot.remove_webhook()
    time.sleep(1)
    url = os.environ.get('RENDER_EXTERNAL_URL')
    if url:
        webhook_url = f"{url.rstrip('/')}/{BOT_TOKEN}"
        bot.set_webhook(url=webhook_url)
        return f"<h1 style='color:green;'>✅ Webhook Success!</h1><p>Active URL: {webhook_url}</p>", 200
    return "<h1 style='color:red;'>❌ Error: RENDER_EXTERNAL_URL is not set</h1>", 500

@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

# ==========================================
# ২. AUTHENTICATION (Login/Logout)
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = "❌ Invalid Credentials!"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# ==========================================
# ৩. TITAN DASHBOARD (Analytics & Tables)
# ==========================================

@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    settings = get_settings()
    users = list(users_col.find().sort("joined", -1).limit(200))
    orders = list(orders_col.find().sort("date", -1).limit(100))
    tickets = list(tickets_col.find({"status": "open"}).sort("date", -1))
    
    total_rev = sum(u.get('spent', 0) for u in users_col.find())
    
    # ৭ দিনের সেলস গ্রাফ জেনারেশন
    dates, sales = [], []
    for i in range(6, -1, -1):
        day = (datetime.now() - timedelta(days=i))
        dates.append(day.strftime('%m-%d'))
        
        start_day = datetime(day.year, day.month, day.day)
        end_day = start_day + timedelta(days=1)
        
        daily_total = sum(o.get('cost', 0) for o in orders_col.find({
            "date": {"$gte": start_day, "$lt": end_day}
        }))
        sales.append(round(daily_total, 2))

    stats = {
        'users': users_col.count_documents({}), 
        'orders': orders_col.count_documents({}),
        'revenue': round(total_rev, 2), 
        'api_status': api.get_balance()
    }
    
    return render_template('admin.html', stats=stats, users=users, orders=orders, 
                           settings=settings, tickets=tickets, dates=dates, 
                           sales=sales, channels=settings.get('channels', []))

# ==========================================
# ৪. CORE CONTROL LOGIC
# ==========================================

@app.route('/update_core_settings', methods=['POST'])
def update_core_settings():
    if not session.get('logged_in'): return redirect(url_for('login'))
    profit = float(request.form.get('profit', 20))
    maint = True if request.form.get('maintenance') == 'on' else False
    target = int(request.form.get('ref_target', 10))
    bonus = float(request.form.get('ref_bonus', 5.0))
    comm = float(request.form.get('dep_commission', 5.0))
    
    config_col.update_one({"_id": "settings"}, {"$set": {
        "profit_margin": profit, "maintenance": maint, 
        "ref_target": target, "ref_bonus": bonus, "dep_commission": comm
    }})
    return redirect(url_for('admin_dashboard'))

@app.route('/add_fake_spender', methods=['POST'])
def add_fake_spender():
    if not session.get('logged_in'): return redirect(url_for('login'))
    name = request.form.get('name', 'User').strip()
    amt = float(request.form.get('amount', 50.0))
    fake_id = random.randint(100000000, 999999999)
    
    users_col.insert_one({
        "_id": fake_id, "name": f"{name} 💎", "balance": 0.0, "spent": amt, 
        "ref_by": None, "ref_paid": False, "ref_earnings": 0.0, 
        "joined": datetime.now(), "is_fake": True
    })
    return redirect(url_for('admin_dashboard'))

@app.route('/resend_order/<oid>')
def resend_order(oid):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        order = orders_col.find_one({"oid": int(oid)})
        if order:
            res = api.place_order(order['sid'], order['link'], order['qty'])
            if 'order' in res:
                orders_col.update_one({"oid": int(oid)}, {"$set": {"status": "Resent", "api_oid": res['order']}})
                bot.send_message(order['uid'], f"🔄 **ORDER RESENT!**\nAdmin has manually pushed your order #{oid} again.")
    except: pass
    return redirect(url_for('admin_dashboard'))

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
    config_col.update_one({"_id": "settings"}, {"$pull": {"channels": '@' + channel}})
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
    try:
        t = tickets_col.find_one({"_id": ObjectId(tid)})
        if t and reply:
            bot.send_message(t['uid'], f"🎧 **SUPPORT REPLY:**\n━━━━━━━━━━━━━━━━━━━━\n{reply}", parse_mode="Markdown")
            tickets_col.update_one({"_id": ObjectId(tid)}, {"$set": {"status": "closed", "reply": reply}})
    except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/add_balance/<int:user_id>', methods=['POST'])
def add_balance(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        amount = float(request.form.get('amount', 0))
        user = users_col.find_one({"_id": user_id})
        if user:
            users_col.update_one({"_id": user_id}, {"$inc": {"balance": amount}})
            # ডিপোজিট কমিশন লজিক (যদি এডমিন ব্যালেন্স অ্যাড করে)
            if amount > 0 and user.get('ref_by'):
                settings = get_settings()
                commission = amount * (settings.get('dep_commission', 5.0) / 100)
                users_col.update_one({"_id": user['ref_by']}, {"$inc": {"balance": commission, "ref_earnings": commission}})
                try: bot.send_message(user['ref_by'], f"💰 **Deposit Commission!** You earned **${round(commission, 3)}** from your referral's deposit.")
                except: pass
            
            bot.send_message(user_id, f"{'💰' if amount > 0 else '⚠️'} **Balance {'Added' if amount > 0 else 'Deducted'}!**\nAmount: ${abs(amount)}")
    except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/ban_user/<int:user_id>')
def ban_user(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    users_col.update_one({"_id": user_id}, {"$set": {"balance": -999999, "is_banned": True}})
    try: bot.send_message(user_id, "🚫 **ACCESS DENIED.** You have been banned by the administrator.")
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
            bot.send_message(order['uid'], f"💸 **ORDER REFUNDED!**\nAmount: `${order['cost']}` has been returned to your wallet.")
    except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/send_broadcast', methods=['POST'])
def send_broadcast():
    if not session.get('logged_in'): return redirect(url_for('login'))
    msg = request.form.get('msg')
    if msg:
        def task():
            for u in users_col.find({"is_fake": {"$ne": True}}):
                try: 
                    bot.send_message(u['_id'], f"📢 **IMPORTANT NOTICE**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
                    time.sleep(0.05)
                except: pass
        threading.Thread(target=task).start()
    return redirect(url_for('admin_dashboard'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
