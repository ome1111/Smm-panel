from flask import Flask, request, render_template, session, redirect, url_for, jsonify, Response
import telebot
from telebot import types
import os
import time
import logging
import random
import threading
import csv
import io
from datetime import datetime, timedelta
from bson.objectid import ObjectId

# Import custom configurations and database collections
from config import BOT_TOKEN, ADMIN_PASSWORD, SECRET_KEY, ADMIN_ID
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, logs_col
import api
import handlers 

# ==========================================
# 1. FLASK APP SETUP & LOGGING
# ==========================================
app = Flask(__name__)
app.secret_key = SECRET_KEY
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')

logging.basicConfig(level=logging.INFO)
telebot.logger.setLevel(logging.INFO)

# ==========================================
# 2. SETTINGS HELPER
# ==========================================
def get_settings():
    settings = config_col.find_one({"_id": "settings"})
    if not settings:
        settings = {
            "_id": "settings", 
            "channels": [], 
            "profit_margin": 20.0, 
            "maintenance": False, 
            "payments": [], 
            "log_channel": "", 
            "proof_channel": "",
            "fake_proof_status": False, 
            "fake_deposit_min": 1.0, 
            "fake_deposit_max": 20.0,
            "fake_order_min": 0.5, 
            "fake_order_max": 10.0, 
            "fake_frequency": 2, 
            "night_mode": True
        }
        config_col.insert_one(settings)
    return settings

# ==========================================
# 3. WEBHOOK & AUTO-REFUND CRON JOBS
# ==========================================
def set_webhook_auto():
    try:
        bot.remove_webhook()
        time.sleep(2)
        bot.set_webhook(url=f"{BASE_URL}/{BOT_TOKEN}")
        print("✅ Webhook Auto-Restart Successful!")
    except Exception as e:
        print(f"Webhook Error: {e}")

threading.Thread(target=set_webhook_auto, daemon=True).start()

def auto_refund_cron():
    while True:
        try:
            active_orders = orders_col.find({"status": {"$in": ["pending", "processing", "in progress"]}})
            
            for order in active_orders:
                res = api.get_order_status(order['oid'])
                
                if res and 'status' in res:
                    status = str(res['status']).lower()
                    
                    if status in ['canceled', 'partial', 'error', 'fail']:
                        attempts = order.get('attempts', 0) + 1
                        
                        if attempts >= 3:
                            # 3 times failed -> Process Refund
                            users_col.update_one(
                                {"_id": order['uid']}, 
                                {"$inc": {"balance": order['cost'], "spent": -order['cost']}}
                            )
                            orders_col.update_one(
                                {"_id": order['_id']}, 
                                {"$set": {"status": "refunded", "attempts": attempts}}
                            )
                            
                            try: 
                                bot.send_message(
                                    order['uid'], 
                                    f"⚠️ **ORDER REFUNDED**\nOrder `{order['oid']}` failed 3 times on the server. `{order['cost']}` USD has been returned to your wallet.", 
                                    parse_mode="Markdown"
                                )
                            except Exception: 
                                pass
                                
                        else:
                            # Retry placing the order silently
                            new_res = api.place_order(order.get('sid'), order.get('link'), order.get('qty'))
                            
                            if new_res and 'order' in new_res:
                                orders_col.update_one(
                                    {"_id": order['_id']}, 
                                    {"$set": {"oid": new_res['order'], "attempts": attempts}}
                                )
                            else:
                                orders_col.update_one(
                                    {"_id": order['_id']}, 
                                    {"$set": {"attempts": attempts}}
                                )
                    else:
                        # Update normal status
                        orders_col.update_one(
                            {"_id": order['_id']}, 
                            {"$set": {"status": status}}
                        )
        except Exception as e:
            pass
            
        time.sleep(300) # Sleep for 5 minutes

threading.Thread(target=auto_refund_cron, daemon=True).start()

# ==========================================
# 4. 🔥 THE ULTIMATE FAKE PROOF ENGINE
# ==========================================
def auto_fake_proof_cron():
    while True:
        try:
            s = get_settings()
            
            if s.get('fake_proof_status'):
                hour = datetime.now().hour
                
                # Night Mode Check (Sleeps from 2 AM to 7 AM)
                if s.get('night_mode') and 2 <= hour < 8:
                    time.sleep(3600) # Sleep for 1 hour
                    continue

                proof_ch = s.get('proof_channel')
                
                if proof_ch:
                    # 50% Chance for Order, 50% for Deposit
                    is_deposit = random.choice([True, False])
                    fake_uid = f"***{random.randint(1111, 9999)}"
                    
                    if is_deposit:
                        # Generate Fake Deposit
                        min_dep = float(s.get('fake_deposit_min', 1.0))
                        max_dep = float(s.get('fake_deposit_max', 20.0))
                        amt = round(random.uniform(min_dep, max_dep), 2)
                        
                        gateways = ["bKash Auto", "Nagad Express", "Binance Pay", "USDT TRC20", "PerfectMoney"]
                        gate = random.choice(gateways)
                        
                        text = (
                            f"> ╔═══ 💳 𝗡𝗘𝗪 𝗗𝗘𝗣𝗢𝗦𝗜𝗧 ═══╗\n"
                            f"> ║ 👤 𝗜𝗗: `{fake_uid}`\n"
                            f"> ║ 🏦 𝗚𝗮𝘁𝗲: {gate}\n"
                            f"> ║ 💵 𝗙𝘂𝗻𝗱: `${amt}`\n"
                            f"> ╚════════════════════╝"
                        )
                        
                        try: 
                            bot.send_message(proof_ch, text, parse_mode="Markdown")
                        except Exception: 
                            pass
                            
                    else:
                        # Generate Fake Order
                        min_ord = float(s.get('fake_order_min', 0.5))
                        max_ord = float(s.get('fake_order_max', 10.0))
                        cost = round(random.uniform(min_ord, max_ord), 2)
                        
                        # Live Sync with Real Services for authentic names
                        services = handlers.get_cached_services()
                        if services:
                            srv = random.choice(services)
                            s_name = handlers.clean_service_name(srv['name'])[:18] + ".."
                            qty = random.randint(1, 50) * 100 # Examples: 100, 1500, 2300
                        else:
                            s_name = "Premium Service"
                            qty = random.randint(1000, 5000)
                            
                        text = (
                            f"> ╔════ 🟢 𝗡𝗘𝗪 𝗢𝗥𝗗𝗘𝗥 ════╗\n"
                            f"> ║ 👤 𝗜𝗗: `{fake_uid}`\n"
                            f"> ║ 🚀 𝗦𝗲𝗿𝘃𝗶𝗰𝗲: {s_name}\n"
                            f"> ║ 📦 𝗤𝘁𝘆: {qty}\n"
                            f"> ║ 💵 𝗖𝗼𝘀𝘁: `${cost}`\n"
                            f"> ╚════════════════════╝"
                        )
                        
                        try: 
                            bot.send_message(proof_ch, text, parse_mode="Markdown")
                        except Exception: 
                            pass

                # Smart Random Delay Logic based on Frequency
                freq = int(s.get('fake_frequency', 2))
                if freq < 1: 
                    freq = 1
                    
                avg_sleep_mins = 60 / freq
                min_sleep = int(avg_sleep_mins * 0.5 * 60)
                max_sleep = int(avg_sleep_mins * 1.5 * 60)
                
                # Sleep for a random time between min and max
                time.sleep(random.randint(max(60, min_sleep), max(300, max_sleep)))
                
            else:
                time.sleep(300) # Check settings again in 5 mins if turned OFF
                
        except Exception as e:
            time.sleep(300)

threading.Thread(target=auto_fake_proof_cron, daemon=True).start()

# ==========================================
# 5. FLASK ROUTES & AUTHENTICATION
# ==========================================
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Forbidden', 403

@app.route("/")
def index(): 
    return "<h1>Nexus SMM Titan Bot is Running Smoothly!</h1>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
            
        return render_template('login.html', error="Invalid Passcode!")
        
    if session.get('logged_in'): 
        return redirect(url_for('admin_dashboard'))
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==========================================
# 6. ADMIN DASHBOARD & ADVANCED SETTINGS
# ==========================================
@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    settings = get_settings()
    
    users = list(users_col.find().sort("joined", -1))
    orders = list(orders_col.find().sort("date", -1).limit(150))
    tickets = list(tickets_col.find().sort("date", -1))
    vouchers = list(vouchers_col.find().sort("_id", -1))
    
    # Live Profit Calculation
    completed_orders = [o for o in orders_col.find({"status": "completed"})]
    total_sales = sum(o.get('cost', 0) for o in completed_orders)
    margin = settings.get("profit_margin", 20.0)
    
    if margin > 0:
        live_profit = total_sales - (total_sales / (1 + (margin / 100))) 
    else:
        live_profit = 0.0
    
    return render_template(
        'admin.html', 
        users=users, 
        orders=orders, 
        tickets=tickets, 
        vouchers=vouchers,
        u_count=len(users), 
        o_count=len(orders), 
        bal=api.get_balance(), 
        s=settings, 
        profit=round(live_profit, 2), 
        sales=round(total_sales, 2)
    )

@app.route('/settings', methods=['POST'])
def update_settings():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
    
    profit_margin = float(request.form.get('profit_margin', 20))
    maintenance = request.form.get('maintenance') == 'on'
    log_channel = request.form.get('log_channel', '').strip()
    proof_channel = request.form.get('proof_channel', '').strip()
    
    # Fake Proof Settings
    fake_proof_status = request.form.get('fake_proof_status') == 'on'
    night_mode = request.form.get('night_mode') == 'on'
    fake_deposit_min = float(request.form.get('fake_deposit_min', 1))
    fake_deposit_max = float(request.form.get('fake_deposit_max', 20))
    fake_order_min = float(request.form.get('fake_order_min', 0.5))
    fake_order_max = float(request.form.get('fake_order_max', 10))
    fake_frequency = int(request.form.get('fake_frequency', 2))
    
    # Channels
    channels_raw = request.form.get('channels', '')
    channels = [c.strip() for c in channels_raw.split(',') if c.strip()]
    
    # Payments
    pay_names = request.form.getlist('pay_name[]')
    pay_rates = request.form.getlist('pay_rate[]')
    payments = []
    
    for n, r in zip(pay_names, pay_rates):
        if n and r:
            payments.append({"name": n, "rate": float(r)})
    
    # Update Database
    config_col.update_one(
        {"_id": "settings"}, 
        {"$set": {
            "profit_margin": profit_margin,
            "maintenance": maintenance,
            "log_channel": log_channel,
            "proof_channel": proof_channel,
            "fake_proof_status": fake_proof_status,
            "night_mode": night_mode,
            "fake_deposit_min": fake_deposit_min,
            "fake_deposit_max": fake_deposit_max,
            "fake_order_min": fake_order_min,
            "fake_order_max": fake_order_max,
            "fake_frequency": fake_frequency,
            "channels": channels,
            "payments": payments
        }}
    )
    
    return redirect(url_for('admin_dashboard'))

# ==========================================
# 7. ALL OTHER ROUTES (100% SECURE & COMPLETE)
# ==========================================
@app.route('/export_csv')
def export_csv_web():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    users = users_col.find()
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(["UID", "Name", "Balance(USD)", "Spent", "Joined"])
    for u in users: 
        writer.writerow([
            u["_id"], 
            u.get("name", "N/A"), 
            u.get("balance", 0), 
            u.get("spent", 0), 
            u.get("joined", "N/A")
        ])
        
    return Response(
        output.getvalue(), 
        mimetype="text/csv", 
        headers={"Content-Disposition": "attachment;filename=users.csv"}
    )

@app.route('/wake_sleepers')
def wake_sleepers_web():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    three_days_ago = datetime.now() - timedelta(days=3)
    sleepers = users_col.find({"last_active": {"$lt": three_days_ago}})
    
    def task():
        for u in sleepers:
            try: 
                bot.send_message(
                    u['_id'], 
                    "👋 **We Miss You!**\nCome back and check out our new fast services. Enjoy a 5% discount on your next order today!", 
                    parse_mode="Markdown"
                )
                time.sleep(0.2)
            except Exception: 
                pass
                
    threading.Thread(target=task, daemon=True).start()
    return redirect(url_for('admin_dashboard'))

@app.route('/smart_cast', methods=['POST'])
def smart_cast_web():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    msg = request.form.get('msg')
    
    if msg:
        last_week = datetime.now() - timedelta(days=7)
        active_users = orders_col.distinct("uid", {"date": {"$gte": last_week}})
        
        def task():
            for uid in active_users:
                try: 
                    bot.send_message(
                        uid, 
                        f"🎁 **EXCLUSIVE OFFER FOR YOU**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", 
                        parse_mode="Markdown"
                    )
                    time.sleep(0.2)
                except Exception: 
                    pass
                    
        threading.Thread(target=task, daemon=True).start()
        
    return redirect(url_for('admin_dashboard'))

@app.route('/approve_dep/<uid>/<amt>/<tid>')
def approve_dep(uid, amt, tid):
    try:
        user_id = int(uid)
        amount = float(amt)
        
        users_col.update_one({"_id": user_id}, {"$inc": {"balance": amount}})
        
        bot.send_message(
            user_id, 
            f"✅ **DEPOSIT APPROVED!**\nAmount: `${amount}` added.\nTrxID: `{tid}`", 
            parse_mode="Markdown"
        )
        bot.send_message(ADMIN_ID, f"✅ Approved ${amount} for User ID: {uid}")
        
        # Real Deposit -> Forwarding to Proof Channel (Cyber Box Style)
        s = get_settings()
        proof_ch = s.get('proof_channel')
        
        if proof_ch:
            text = (
                f"> ╔═══ 💳 𝗡𝗘𝗪 𝗗𝗘𝗣𝗢𝗦𝗜𝗧 ═══╗\n"
                f"> ║ 👤 𝗜𝗗: `***{str(uid)[-4:]}`\n"
                f"> ║ 🏦 𝗚𝗮𝘁𝗲: Verified User\n"
                f"> ║ 💵 𝗙𝘂𝗻𝗱: `${amount}`\n"
                f"> ╚════════════════════╝"
            )
            try: 
                bot.send_message(proof_ch, text, parse_mode="Markdown")
            except Exception: 
                pass
                
    except Exception: 
        pass
        
    return "<h3>Action Completed. You can close this window.</h3>"

@app.route('/reject_dep/<uid>/<tid>')
def reject_dep(uid, tid):
    try:
        bot.send_message(
            int(uid), 
            f"❌ **DEPOSIT REJECTED!**\nTrxID `{tid}` was invalid or already used.", 
            parse_mode="Markdown"
        )
        bot.send_message(ADMIN_ID, f"❌ Rejected {tid} for {uid}")
    except Exception: 
        pass
        
    return "<h3>Action Completed. You can close this window.</h3>"

@app.route('/ban_user/<int:user_id>')
def ban_user(user_id):
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    users_col.update_one({"_id": user_id}, {"$set": {"banned": True}})
    return redirect(url_for('admin_dashboard'))

@app.route('/unban_user/<int:user_id>')
def unban_user(user_id):
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    users_col.update_one({"_id": user_id}, {"$set": {"banned": False}})
    return redirect(url_for('admin_dashboard'))

@app.route('/add_fake_user', methods=['POST'])
def add_fake_user():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    name = request.form.get('fake_name')
    spent = float(request.form.get('fake_spent', 0))
    
    users_col.insert_one({
        "_id": random.randint(100000, 999999), 
        "name": name, 
        "balance": 0.0, 
        "spent": spent, 
        "joined": datetime.now(), 
        "is_fake": True
    })
    
    return redirect(url_for('admin_dashboard'))

@app.route('/refund_order/<oid>')
def refund_order(oid):
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    order = orders_col.find_one({"oid": int(oid)})
    
    if order and order.get('status') != 'refunded':
        users_col.update_one(
            {"_id": order['uid']}, 
            {"$inc": {"balance": order['cost'], "spent": -order['cost']}}
        )
        orders_col.update_one({"oid": int(oid)}, {"$set": {"status": "refunded"}})
        
        try: 
            bot.send_message(
                order['uid'], 
                f"💸 **ORDER REFUNDED (By Admin)!**\nAmount: `${order['cost']}` has been safely returned."
            )
        except Exception: 
            pass
            
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_order/<oid>')
def delete_order(oid):
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    orders_col.delete_one({"oid": int(oid)})
    return redirect(url_for('admin_dashboard'))

@app.route('/create_voucher', methods=['POST'])
def create_voucher():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    code = request.form.get('code').upper()
    amount = float(request.form.get('amount'))
    limit = int(request.form.get('limit'))
    
    vouchers_col.insert_one({
        "code": code, 
        "amount": amount, 
        "limit": limit, 
        "used_by": []
    })
    
    return redirect(url_for('admin_dashboard'))

@app.route('/reply_ticket', methods=['POST'])
def reply_ticket():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    reply = request.form.get('reply_msg')
    uid = int(request.form.get('uid'))
    ticket_id = request.form.get('ticket_id')
    
    tickets_col.update_one(
        {"_id": ObjectId(ticket_id)}, 
        {"$set": {"status": "answered", "reply": reply}}
    )
    
    try: 
        bot.send_message(
            uid, 
            f"🎧 **SUPPORT REPLY**\n━━━━━━━━━━━━━━━━━━━━\n{reply}", 
            parse_mode="Markdown"
        )
    except Exception: 
        pass
        
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_ticket/<tid>')
def delete_ticket(tid):
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    tickets_col.delete_one({"_id": ObjectId(tid)})
    return redirect(url_for('admin_dashboard'))

@app.route('/send_broadcast', methods=['POST'])
def send_broadcast():
    if not session.get('logged_in'): 
        return redirect(url_for('login'))
        
    msg = request.form.get('msg')
    
    if msg:
        def task():
            real_users = users_col.find({"is_fake": {"$ne": True}})
            for u in real_users:
                try: 
                    bot.send_message(
                        u['_id'], 
                        f"📢 **IMPORTANT NOTICE**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", 
                        parse_mode="Markdown"
                    )
                    time.sleep(0.2)
                except Exception: 
                    pass
                    
        threading.Thread(target=task, daemon=True).start()
        
    return redirect(url_for('admin_dashboard'))

# ==========================================
# 8. START SERVER
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
