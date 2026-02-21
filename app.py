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

app = Flask(__name__)
app.secret_key = SECRET_KEY
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')

# Logging Setup
logging.basicConfig(level=logging.INFO)
telebot.logger.setLevel(logging.INFO)

# ==========================================
# ১. SYSTEM HELPERS & CONFIGS
# ==========================================
def get_settings():
    settings = config_col.find_one({"_id": "settings"})
    if not settings:
        settings = {
            "_id": "settings", "channels": [], "profit_margin": 20.0, "maintenance": False, 
            "payments": [], "ref_target": 10, "ref_bonus": 5.0, "dep_commission": 5.0, 
            "hidden_services": [], "log_channel": ""
        }
        config_col.insert_one(settings)
    return settings

# ==========================================
# ২. WEBHOOK AUTO-RESTART
# ==========================================
def set_webhook_auto():
    try:
        bot.remove_webhook()
        time.sleep(2)
        bot.set_webhook(url=f"{BASE_URL}/{BOT_TOKEN}")
        print("✅ Webhook Auto-Restart Successful!")
    except Exception as e:
        print("Webhook Error:", e)

threading.Thread(target=set_webhook_auto, daemon=True).start()

# ==========================================
# ৩. AUTO-REFUND SYSTEM CRON JOB
# ==========================================
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
                            users_col.update_one({"_id": order['uid']}, {"$inc": {"balance": order['cost'], "spent": -order['cost']}})
                            orders_col.update_one({"_id": order['_id']}, {"$set": {"status": "refunded", "attempts": attempts}})
                            try: bot.send_message(order['uid'], f"⚠️ **ORDER REFUNDED**\nOrder `{order['oid']}` failed 3 times. `{order['cost']}` USD returned to wallet.", parse_mode="Markdown")
                            except: pass
                        else:
                            new_res = api.place_order(order.get('sid'), order.get('link'), order.get('qty'))
                            if new_res and 'order' in new_res:
                                orders_col.update_one({"_id": order['_id']}, {"$set": {"oid": new_res['order'], "attempts": attempts}})
                            else:
                                orders_col.update_one({"_id": order['_id']}, {"$set": {"attempts": attempts}})
                    else:
                        orders_col.update_one({"_id": order['_id']}, {"$set": {"status": status}})
        except: pass
        time.sleep(300)

threading.Thread(target=auto_refund_cron, daemon=True).start()

# ==========================================
# ৪. WEBHOOK & AUTH ROUTES
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
def index(): return "<h1>Nexus SMM Titan Bot is Running!</h1>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('login.html', error="Invalid Passcode!")
    if session.get('logged_in'): return redirect(url_for('admin_dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==========================================
# ৫. ADMIN DASHBOARD & SETTINGS
# ==========================================
@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    settings = get_settings()
    users = list(users_col.find().sort("joined", -1))
    orders = list(orders_col.find().sort("date", -1).limit(150))
    tickets = list(tickets_col.find().sort("date", -1))
    vouchers = list(vouchers_col.find().sort("_id", -1))
    
    completed_orders = [o for o in orders_col.find({"status": "completed"})]
    total_sales = sum(o.get('cost', 0) for o in completed_orders)
    margin = settings.get("profit_margin", 20.0)
    live_profit = total_sales - (total_sales / (1 + (margin / 100))) if margin > 0 else 0.0
    
    return render_template('admin.html', users=users, orders=orders, tickets=tickets, vouchers=vouchers,
                           u_count=len(users), o_count=len(orders), bal=api.get_balance(), s=settings, 
                           profit=round(live_profit, 2), sales=round(total_sales, 2))

@app.route('/settings', methods=['POST'])
def update_settings():
    if not session.get('logged_in'): return redirect(url_for('login'))
    profit_margin = float(request.form.get('profit_margin', 20))
    maintenance = request.form.get('maintenance') == 'on'
    log_channel = request.form.get('log_channel', '').strip()
    channels = [c.strip() for c in request.form.get('channels', '').split(',') if c.strip()]
    
    pay_names = request.form.getlist('pay_name[]')
    pay_rates = request.form.getlist('pay_rate[]')
    payments = [{"name": n, "rate": float(r)} for n, r in zip(pay_names, pay_rates) if n and r]
    
    config_col.update_one({"_id": "settings"}, {"$set": {
        "profit_margin": profit_margin, "maintenance": maintenance, "channels": channels,
        "payments": payments, "log_channel": log_channel
    }})
    return redirect(url_for('admin_dashboard'))

# ==========================================
# ৬. NEW ADMIN FEATURES (CSV, WAKE, SMART CAST)
# ==========================================
@app.route('/export_csv')
def export_csv_web():
    if not session.get('logged_in'): return redirect(url_for('login'))
    users = users_col.find()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["UID", "Name", "Balance(USD)", "Spent", "Joined"])
    for u in users:
        writer.writerow([u["_id"], u.get("name", "N/A"), u.get("balance", 0), u.get("spent", 0), u.get("joined", "N/A")])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=users_database.csv"})

@app.route('/wake_sleepers')
def wake_sleepers_web():
    if not session.get('logged_in'): return redirect(url_for('login'))
    three_days_ago = datetime.now() - timedelta(days=3)
    sleepers = users_col.find({"last_active": {"$lt": three_days_ago}})
    def task():
        for u in sleepers:
            try: 
                bot.send_message(u['_id'], "👋 **We Miss You!**\nCome back and check out our new fast services. Enjoy a 5% discount on your next order today!", parse_mode="Markdown")
                time.sleep(0.1)
            except: pass
    threading.Thread(target=task, daemon=True).start()
    return redirect(url_for('admin_dashboard'))

@app.route('/smart_cast', methods=['POST'])
def smart_cast_web():
    if not session.get('logged_in'): return redirect(url_for('login'))
    msg = request.form.get('msg')
    if msg:
        last_week = datetime.now() - timedelta(days=7)
        active_users = orders_col.distinct("uid", {"date": {"$gte": last_week}})
        def task():
            for uid in active_users:
                try: 
                    bot.send_message(uid, f"🎁 **EXCLUSIVE OFFER FOR YOU**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
                    time.sleep(0.1)
                except: pass
        threading.Thread(target=task, daemon=True).start()
    return redirect(url_for('admin_dashboard'))

# ==========================================
# ৭. OTHER MANAGEMENT ROUTES
# ==========================================
@app.route('/approve_dep/<uid>/<amt>/<tid>')
def approve_dep(uid, amt, tid):
    try:
        users_col.update_one({"_id": int(uid)}, {"$inc": {"balance": float(amt)}})
        bot.send_message(int(uid), f"✅ **DEPOSIT APPROVED!**\nAmount: `${amt}` added.\nTrxID: `{tid}`", parse_mode="Markdown")
        bot.send_message(ADMIN_ID, f"✅ Approved ${amt} for {uid}")
    except: pass
    return "Action Completed. You can close this window."

@app.route('/reject_dep/<uid>/<tid>')
def reject_dep(uid, tid):
    try:
        bot.send_message(int(uid), f"❌ **DEPOSIT REJECTED!**\nTrxID `{tid}` was invalid.", parse_mode="Markdown")
        bot.send_message(ADMIN_ID, f"❌ Rejected {tid} for {uid}")
    except: pass
    return "Action Completed."

@app.route('/ban_user/<int:user_id>')
def ban_user(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    users_col.update_one({"_id": user_id}, {"$set": {"banned": True}})
    return redirect(url_for('admin_dashboard'))

@app.route('/unban_user/<int:user_id>')
def unban_user(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    users_col.update_one({"_id": user_id}, {"$set": {"banned": False}})
    return redirect(url_for('admin_dashboard'))

@app.route('/add_fake_user', methods=['POST'])
def add_fake_user():
    if not session.get('logged_in'): return redirect(url_for('login'))
    name = request.form.get('fake_name')
    spent = float(request.form.get('fake_spent', 0))
    users_col.insert_one({"_id": random.randint(100000, 999999), "name": name, "balance": 0.0, "spent": spent, "joined": datetime.now(), "is_fake": True})
    return redirect(url_for('admin_dashboard'))

@app.route('/refund_order/<oid>')
def refund_order(oid):
    if not session.get('logged_in'): return redirect(url_for('login'))
    order = orders_col.find_one({"oid": int(oid)})
    if order and order.get('status') != 'refunded':
        users_col.update_one({"_id": order['uid']}, {"$inc": {"balance": order['cost'], "spent": -order['cost']}})
        orders_col.update_one({"oid": int(oid)}, {"$set": {"status": "refunded"}})
        try: bot.send_message(order['uid'], f"💸 **ORDER REFUNDED (By Admin)!**\nAmount: `${order['cost']}` returned.")
        except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_order/<oid>')
def delete_order(oid):
    if not session.get('logged_in'): return redirect(url_for('login'))
    orders_col.delete_one({"oid": int(oid)})
    return redirect(url_for('admin_dashboard'))

@app.route('/create_voucher', methods=['POST'])
def create_voucher():
    if not session.get('logged_in'): return redirect(url_for('login'))
    vouchers_col.insert_one({"code": request.form.get('code').upper(), "amount": float(request.form.get('amount')), "limit": int(request.form.get('limit')), "used_by": []})
    return redirect(url_for('admin_dashboard'))

@app.route('/reply_ticket', methods=['POST'])
def reply_ticket():
    if not session.get('logged_in'): return redirect(url_for('login'))
    reply = request.form.get('reply_msg')
    uid = int(request.form.get('uid'))
    tickets_col.update_one({"_id": ObjectId(request.form.get('ticket_id'))}, {"$set": {"status": "answered", "reply": reply}})
    try: bot.send_message(uid, f"🎧 **SUPPORT REPLY**\n━━━━━━━━━━━━━━━━━━━━\n{reply}", parse_mode="Markdown")
    except: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_ticket/<tid>')
def delete_ticket(tid):
    if not session.get('logged_in'): return redirect(url_for('login'))
    tickets_col.delete_one({"_id": ObjectId(tid)})
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
                    time.sleep(0.1)
                except: pass
        threading.Thread(target=task, daemon=True).start()
    return redirect(url_for('admin_dashboard'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
