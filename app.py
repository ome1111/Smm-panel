from flask import Flask, request, render_template, session, redirect, url_for
import telebot
from telebot import types
import os, time, logging, random, threading
from datetime import datetime, timedelta
from config import BOT_TOKEN, ADMIN_PASSWORD, SECRET_KEY
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, logs_col
import api
from bson.objectid import ObjectId
import handlers # বটের সব ফাংশনালিটি কানেক্ট করার জন্য

logging.basicConfig(level=logging.INFO)
telebot.logger.setLevel(logging.DEBUG)

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ==========================================
# ⚙️ CORE SETTINGS MANAGER
# ==========================================
def get_settings():
    s = config_col.find_one({"_id": "settings"})
    if not s:
        s = {
            "_id": "settings", 
            "channels": [], 
            "profit_margin": 20.0, 
            "maintenance": False, 
            "payments": [], 
            "ref_target": 10, 
            "ref_bonus": 5.0, 
            "dep_commission": 5.0, 
            "hidden_services": [],
            "fake_orders": 50000, 
            "fake_users": 12000,
            "fake_post_channel": "", 
            "fake_post_freq": 5,
            "cat_ranking": []
        }
        config_col.insert_one(s)
    return s

# ==========================================
# 🤖 ADVANCED BACKGROUND ENGINES
# ==========================================

# 1. Auto-System Engine (Auto-Retry, Auto-Refund & Sync)
def auto_system_engine():
    while True:
        try:
            # Midnight API Sync
            now = datetime.now()
            if now.hour == 0 and now.minute == 0:
                api.get_services()
            
            # Check Pending Orders
            pending_orders = orders_col.find({"status": {"$in": ["pending", "processing", "in progress"]}})
            for o in pending_orders:
                res = api.get_order_status(o['oid'])
                if res and 'status' in res:
                    status = str(res['status']).lower()
                    
                    # Auto Retry / Refund Logic for Failed Orders
                    if status in ['canceled', 'fail', 'error']:
                        retries = o.get('retries', 0)
                        if retries < 3:
                            # Try placing order again
                            new_res = api.place_order(o['sid'], o['link'], o['qty'])
                            if 'order' in new_res:
                                orders_col.update_one({"oid": o['oid']}, {"$set": {"status": "retrying", "api_oid": new_res['order'], "retries": retries + 1}})
                                try: bot.send_message(o['uid'], f"🔄 **AUTO-RETRY:** Order `{o['oid']}` failed. Our system is automatically retrying ({retries+1}/3).", parse_mode="Markdown")
                                except: pass
                            continue
                        else:
                            # Final Refund
                            users_col.update_one({"_id": o['uid']}, {"$inc": {"balance": o['cost'], "spent": -o['cost']}})
                            orders_col.update_one({"oid": o['oid']}, {"$set": {"status": "Refunded"}})
                            try: bot.send_message(o['uid'], f"> 🧾 **REFUND INVOICE**\n> ━━━━━━━━━━━━━━━━━━━━\n> 🆔 **Order ID:** `{o['oid']}`\n> 🏷 **Status:** FAILED (Auto-Refunded)\n> 💰 **Refunded:** `${o['cost']}`\n> \n> _Amount added back to your wallet after 3 failed retries._", parse_mode="Markdown")
                            except: pass

                    # Partial Refund Logic
                    elif status == 'partial':
                        refund_amount = o['cost']
                        if 'remains' in res:
                            try: refund_amount = (float(res['remains']) / float(o['qty'])) * o['cost']
                            except: pass
                        users_col.update_one({"_id": o['uid']}, {"$inc": {"balance": refund_amount, "spent": -refund_amount}})
                        orders_col.update_one({"oid": o['oid']}, {"$set": {"status": "Partial"}})
                        try: bot.send_message(o['uid'], f"> 🧾 **PARTIAL REFUND**\n> ━━━━━━━━━━━━━━━━━━━━\n> 🆔 **Order ID:** `{o['oid']}`\n> 💰 **Refunded:** `${round(refund_amount, 3)}`\n> \n> _Order was partially completed._", parse_mode="Markdown")
                        except: pass

            time.sleep(120) # Runs every 2 minutes
        except: time.sleep(60)

# 2. Fake Auto-Post Engine (Channel Marketing)
def fake_auto_post_task():
    while True:
        try:
            settings = get_settings()
            channel = settings.get("fake_post_channel", "")
            freq = settings.get("fake_post_freq", 5) 
            
            if channel and freq > 0:
                sleep_time = 3600 / freq
                time.sleep(sleep_time)
                
                is_deposit = random.choice([True, False])
                if is_deposit:
                    amt = random.choice([10, 25, 50, 100, 150, 200])
                    msg = f"💸 **NEW DEPOSIT ALERT!**\n━━━━━━━━━━━━━━━━━━━━\n👤 **User:** `{random.randint(100000, 999999)}`\n💰 **Amount:** `${amt}`\n✅ **Status:** Successful\n━━━━━━━━━━━━━━━━━━━━\n🚀 _Join NEXUS SMM & Boost Your Social Media!_"
                else:
                    qty = random.choice([1000, 2000, 5000, 10000])
                    platform = random.choice(["Instagram Likes", "Telegram Members", "YouTube Views", "Facebook Followers"])
                    msg = f"📦 **NEW ORDER PLACED!**\n━━━━━━━━━━━━━━━━━━━━\n👤 **User:** `{random.randint(100000, 999999)}`\n🏷 **Service:** {platform}\n🔢 **Quantity:** {qty}\n⚡ **Speed:** Fast\n━━━━━━━━━━━━━━━━━━━━\n🚀 _Start boosting today!_"
                
                try: bot.send_message(channel, msg, parse_mode="Markdown")
                except: pass
            else:
                time.sleep(60)
        except: time.sleep(60)

# Start Background Threads
threading.Thread(target=auto_system_engine, daemon=True).start()
threading.Thread(target=fake_auto_post_task, daemon=True).start()

# ==========================================
# 🌐 WEBHOOK & AUTH ROUTES
# ==========================================

@app.route("/")
def index():
    return "<body style='background:#020617; color:#38bdf8; text-align:center; padding-top:100px; font-family:sans-serif;'><h1>🚀 Titan God System Online</h1><a href='/admin' style='color:#fff; text-decoration:none; background:#0ea5e9; padding:10px 20px; border-radius:8px;'>Admin Panel</a></body>", 200

@app.route("/set_webhook")
def setup_webhook():
    bot.remove_webhook()
    time.sleep(1)
    url = os.environ.get('RENDER_EXTERNAL_URL')
    if url:
        webhook_url = f"{url.rstrip('/')}/{BOT_TOKEN}"
        bot.set_webhook(url=webhook_url)
        return f"<h1>✅ Webhook Success! URL: {webhook_url}</h1>", 200
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
            error = "❌ Invalid Password!"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# ==========================================
# 📊 MAIN DASHBOARD ROUTE
# ==========================================

@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    settings = get_settings()
    # Users sorted by last active for SPY MODE
    users = list(users_col.find().sort("last_active", -1).limit(200)) 
    orders = list(orders_col.find().sort("date", -1).limit(150))
    tickets = list(tickets_col.find({"status": "open"}).sort("date", -1))
    vouchers = list(vouchers_col.find().sort("_id", -1))
    
    total_rev = sum(u.get('spent', 0) for u in users_col.find())
    
    # 7 Days Sales Chart Data
    dates, sales = [], []
    for i in range(6, -1, -1):
        day = (datetime.now() - timedelta(days=i))
        dates.append(day.strftime('%m-%d'))
        start_day = datetime(day.year, day.month, day.day)
        end_day = start_day + timedelta(days=1)
        day_total = sum(o.get('cost', 0) for o in orders_col.find({"date": {"$gte": start_day, "$lt": end_day}}))
        sales.append(round(day_total, 2))

    stats = {
        'users': users_col.count_documents({}), 
        'orders': orders_col.count_documents({}),
        'revenue': round(total_rev, 2), 
        'api_status': api.get_balance()
    }
    
    return render_template('admin.html', stats=stats, users=users, orders=orders, 
                           settings=settings, tickets=tickets, vouchers=vouchers, 
                           dates=dates, sales=sales, channels=settings.get('channels', []))

# ==========================================
# 🛠 SYSTEM CONTROLS & MARKETING
# ==========================================

@app.route('/update_core_settings', methods=['POST'])
def update_core_settings():
    if not session.get('logged_in'): return redirect(url_for('login'))
    config_col.update_one({"_id": "settings"}, {"$set": {
        "profit_margin": float(request.form.get('profit', 20)), 
        "maintenance": True if request.form.get('maintenance') == 'on' else False, 
        "ref_target": int(request.form.get('ref_target', 10)), 
        "ref_bonus": float(request.form.get('ref_bonus', 5.0)), 
        "dep_commission": float(request.form.get('dep_commission', 5.0))
    }})
    return redirect(url_for('admin_dashboard'))

@app.route('/update_fake_stats', methods=['POST'])
def update_fake_stats():
    if not session.get('logged_in'): return redirect(url_for('login'))
    config_col.update_one({"_id": "settings"}, {"$set": {
        "fake_orders": int(request.form.get('fake_orders', 50000)),
        "fake_users": int(request.form.get('fake_users', 12000))
    }})
    return redirect(url_for('admin_dashboard'))

@app.route('/update_fake_tool', methods=['POST'])
def update_fake_tool():
    if not session.get('logged_in'): return redirect(url_for('login'))
    channel = request.form.get('channel', '').strip()
    freq = int(request.form.get('freq', 5))
    config_col.update_one({"_id": "settings"}, {"$set": {"fake_post_channel": channel, "fake_post_freq": freq}})
    return redirect(url_for('admin_dashboard'))

@app.route('/add_fake_spender', methods=['POST'])
def add_fake_spender():
    if not session.get('logged_in'): return redirect(url_for('login'))
    name = request.form.get('name', 'Premium User').strip()
    amt = float(request.form.get('amount', 50.0))
    fake_id = random.randint(111111111, 999999999)
    users_col.insert_one({"_id": fake_id, "name": f"{name} 💎", "balance": 0.0, "spent": amt, "ref_by": None, "ref_paid": False, "ref_earnings": 0.0, "joined": datetime.now(), "is_fake": True, "last_active": datetime.now(), "last_action": "Placed VIP Order"})
    return redirect(url_for('admin_dashboard'))

@app.route('/add_voucher', methods=['POST'])
def add_voucher():
    if not session.get('logged_in'): return redirect(url_for('login'))
    code = request.form.get('code').strip().upper()
    amount = float(request.form.get('amount'))
    limit = int(request.form.get('limit'))
    if code: vouchers_col.insert_one({"code": code, "amount": amount, "limit": limit, "used_by": []})
    return redirect(url_for('admin_dashboard'))

@app.route('/del_voucher/<code>')
def del_voucher(code):
    if not session.get('logged_in'): return redirect(url_for('login'))
    vouchers_col.delete_one({"code": code})
    return redirect(url_for('admin_dashboard'))

# ==========================================
# 💰 ADVANCED DEPOSIT APPROVAL
# ==========================================

@app.route('/approve_dep/<int:uid>/<float:amt>/<tid>')
def approve_dep(uid, amt, tid):
    user = users_col.find_one({"_id": uid})
    if user:
        users_col.update_one({"_id": uid}, {"$inc": {"balance": amt}})
        
        # Commission Logic
        if user.get('ref_by'):
            settings = get_settings()
            comm = amt * (settings.get('dep_commission', 5.0) / 100)
            users_col.update_one({"_id": user['ref_by']}, {"$inc": {"balance": comm, "ref_earnings": comm}})
            try: bot.send_message(user['ref_by'], f"🎉 **Affiliate Bonus!** You earned `${round(comm,3)}` from referral deposit.", parse_mode="Markdown")
            except: pass

        msg = f"> 🧾 **DEPOSIT INVOICE**\n> ━━━━━━━━━━━━━━━━━━━━\n> ✅ **Status:** APPROVED\n> 💰 **Amount Added:** `${amt}`\n> 🆔 **TrxID:** `{tid}`\n> \n> _Thank you for adding funds!_"
        try: bot.send_message(uid, msg, parse_mode="Markdown")
        except: pass
        
    return "<h1 style='color:green;text-align:center;padding:50px;'>✅ Deposit Approved & Invoice Sent!</h1>", 200

@app.route('/reject_dep/<int:uid>/<tid>')
def reject_dep(uid, tid):
    msg = f"❌ **DEPOSIT REJECTED**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **TrxID:** `{tid}`\n\n_Your deposit request was declined by the admin. Please verify your TrxID._"
    try: bot.send_message(uid, msg, parse_mode="Markdown")
    except: pass
    return "<h1 style='color:red;text-align:center;padding:50px;'>❌ Deposit Rejected!</h1>", 200

# ==========================================
# ⚙️ USER, ORDERS & SPY MODE ACTIONS
# ==========================================

@app.route('/add_balance/<int:user_id>', methods=['POST'])
def add_balance(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        amount = float(request.form.get('amount', 0))
        users_col.update_one({"_id": user_id}, {"$inc": {"balance": amount}})
        if amount > 0: msg = f"> 🧾 **WALLET UPDATE**\n> ━━━━━━━━━━━━━━━━━━━━\n> ✅ **Status:** FUNDS ADDED\n> 💰 **Amount:** `${amount}`\n> \n> _Admin manually added funds._"
        else: msg = f"> 🧾 **WALLET UPDATE**\n> ━━━━━━━━━━━━━━━━━━━━\n> ⚠️ **Status:** FUNDS DEDUCTED\n> 💰 **Amount:** `${abs(amount)}`\n> \n> _Admin manually deducted funds._"
        try: bot.send_message(user_id, msg, parse_mode="Markdown")
        except: pass
    except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/ban_user/<int:user_id>')
def ban_user(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    users_col.update_one({"_id": user_id}, {"$set": {"balance": -999999, "is_banned": True}})
    try: bot.send_message(user_id, "🚫 **ACCOUNT SUSPENDED BY ADMIN.**", parse_mode="Markdown")
    except: pass
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
                bot.send_message(order['uid'], f"🔄 **ORDER RESTARTED!**\nAdmin manually resent Order ID: `{oid}`")
    except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/refund_order/<oid>')
def refund_order(oid):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        order = orders_col.find_one({"oid": int(oid)})
        if order and order.get('status') not in ['Refunded', 'Canceled']:
            users_col.update_one({"_id": order['uid']}, {"$inc": {"balance": order['cost'], "spent": -order['cost']}})
            orders_col.update_one({"oid": int(oid)}, {"$set": {"status": "Refunded"}})
            msg = f"> 🧾 **MANUAL REFUND**\n> ━━━━━━━━━━━━━━━━━━━━\n> 🆔 **Order ID:** `{oid}`\n> 💰 **Refunded:** `${order['cost']}`\n> \n> _Amount manually returned by Admin._"
            try: bot.send_message(order['uid'], msg, parse_mode="Markdown")
            except: pass
    except: pass
    return redirect(url_for('admin_dashboard'))

# SINGLE USER MESSAGE (Chat directly from Admin Panel)
@app.route('/send_single_msg', methods=['POST'])
def send_single_msg():
    if not session.get('logged_in'): return redirect(url_for('login'))
    uid = int(request.form.get('uid'))
    msg = request.form.get('msg')
    try:
        bot.send_message(uid, f"💬 **Direct Message from Admin:**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
    except: pass
    return redirect(url_for('admin_dashboard'))

# ==========================================
# ⚙️ CHANNELS & PAYMENTS
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
    config_col.update_one({"_id": "settings"}, {"$pull": {"channels": '@' + channel}})
    return redirect(url_for('admin_dashboard'))

@app.route('/add_payment', methods=['POST'])
def add_payment():
    if not session.get('logged_in'): return redirect(url_for('login'))
    name = request.form.get('name')
    details = request.form.get('details')
    rate = float(request.form.get('rate', 120))
    if name and details: config_col.update_one({"_id": "settings"}, {"$push": {"payments": {"name": name, "details": details, "rate": rate}}})
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
            bot.send_message(t['uid'], f"🎧 **SUPPORT REPLY**\n━━━━━━━━━━━━━━━━━━━━\n{reply}", parse_mode="Markdown")
            tickets_col.update_one({"_id": ObjectId(tid)}, {"$set": {"status": "closed", "reply": reply}})
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
                    bot.send_message(u['_id'], f"📢 **GLOBAL BROADCAST**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
                    time.sleep(0.05)
                except: pass
        threading.Thread(target=task).start()
    return redirect(url_for('admin_dashboard'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
