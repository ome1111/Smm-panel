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
            "maintenance_msg": "Bot is currently upgrading.",
            "payments": [], 
            "log_channel": "", 
            "proof_channel": "",
            "fake_proof_status": False, 
            "fake_deposit_min": 1.0, 
            "fake_deposit_max": 20.0,
            "fake_order_min": 0.5, 
            "fake_order_max": 10.0, 
            "fake_dep_freq": 2, 
            "fake_ord_freq": 3,
            "night_mode": True,
            "ref_bonus": 0.05,
            "dep_commission": 5.0,
            "welcome_bonus_active": False,
            "welcome_bonus": 0.0,
            "flash_sale_active": False,
            "flash_sale_discount": 0.0,
            "reward_top1": 10.0,
            "reward_top2": 5.0,
            "reward_top3": 2.0
        }
        config_col.insert_one(settings)
    return settings

# ==========================================
# 3. WEBHOOK & AUTO NOTIFICATION CRON JOB
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

def auto_refund_and_notification_cron():
    while True:
        try:
            active_orders = orders_col.find({"status": {"$in": ["pending", "processing", "in progress"]}})
            
            for order in active_orders:
                # Skip shadow banned orders (they are ghost orders)
                if order.get('is_shadow'): 
                    continue
                    
                res = api.get_order_status(order['oid'])
                
                if res and 'status' in res:
                    new_status = str(res['status']).lower()
                    old_status = str(order.get('status', 'pending')).lower()
                    
                    # 1. Error / Cancelled / Partial Logic
                    if new_status in ['canceled', 'partial', 'error', 'fail']:
                        attempts = order.get('attempts', 0) + 1
                        
                        if attempts >= 3:
                            # Full Refund
                            users_col.update_one({"_id": order['uid']}, {"$inc": {"balance": order['cost'], "spent": -order['cost']}})
                            orders_col.update_one({"_id": order['_id']}, {"$set": {"status": "refunded", "attempts": attempts}})
                            
                            # SMS: Refund Notification
                            try: 
                                msg = f"⚠️ **ORDER REFUNDED / CANCELED**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **Order ID:** `{order['oid']}`\n💰 **Refund Amount:** `${order['cost']}`\n📊 **Status:** Order could not be fully completed by the server. The amount has been added back to your wallet.\n━━━━━━━━━━━━━━━━━━━━"
                                bot.send_message(order['uid'], msg, parse_mode="Markdown")
                            except Exception: pass
                        else:
                            # Retry placing the order silently
                            new_res = api.place_order(order.get('sid'), order.get('link'), order.get('qty'))
                            if new_res and 'order' in new_res:
                                orders_col.update_one({"_id": order['_id']}, {"$set": {"oid": new_res['order'], "attempts": attempts}})
                            else:
                                orders_col.update_one({"_id": order['_id']}, {"$set": {"attempts": attempts}})
                    
                    # 2. Status Changed Notification (Processing, Completed)
                    elif new_status != old_status:
                        orders_col.update_one({"_id": order['_id']}, {"$set": {"status": new_status}})
                        
                        try:
                            if new_status == 'completed':
                                msg = f"✅ **ORDER SUCCESSFULLY COMPLETED!**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **Order ID:** `{order['oid']}`\n📦 **Quantity:** {order.get('qty', 'N/A')}\n💳 **Cost:** `${order['cost']}`\n📊 **Status:** Mission Accomplished! The requested amount has been fully delivered.\n━━━━━━━━━━━━━━━━━━━━"
                                bot.send_message(order['uid'], msg, parse_mode="Markdown")
                                
                            elif new_status in ['processing', 'in progress']:
                                msg = f"🔄 **ORDER UPDATE: PROCESSING**\n━━━━━━━━━━━━━━━━━━━━\n🆔 **Order ID:** `{order['oid']}`\n🔗 **Link:** {str(order.get('link', 'N/A'))[:25]}...\n📊 **Status:** Your order has been picked up by the server and is currently being processed!\n━━━━━━━━━━━━━━━━━━━━"
                                bot.send_message(order['uid'], msg, parse_mode="Markdown", disable_web_page_preview=True)
                        except Exception:
                            pass
        except Exception: 
            pass
            
        time.sleep(120) # Checks every 2 minutes for faster updates

threading.Thread(target=auto_refund_and_notification_cron, daemon=True).start()

# ==========================================
# 4. 🔥 MULTI-CURRENCY FAKE PROOF ENGINE
# ==========================================
def auto_fake_deposit_cron():
    while True:
        try:
            s = get_settings()
            if s.get('fake_proof_status'):
                if s.get('night_mode') and 2 <= datetime.now().hour < 8:
                    time.sleep(3600)
                    continue
                    
                proof_ch = s.get('proof_channel')
                if proof_ch:
                    fake_uid = f"***{random.randint(1111, 9999)}"
                    min_dep = float(s.get('fake_deposit_min', 0.01))
                    max_dep = float(s.get('fake_deposit_max', 20.0))
                    amt_usd = random.uniform(min_dep, max_dep)
                    
                    currencies = [('$', 1.0), ('৳', 120.0), ('₹', 83.0)]
                    sym, rate = random.choice(currencies)
                    final_amt = round(amt_usd * rate, 2)
                    
                    gateways = ["bKash Auto", "Nagad Express", "Binance Pay", "USDT TRC20", "PerfectMoney"]
                    gate = random.choice(gateways)
                    
                    text = f"> ╔═══ 💳 𝗡𝗘𝗪 𝗗𝗘𝗣𝗢𝗦𝗜𝗧 ═══╗\n> ║ 👤 𝗜𝗗: `{fake_uid}`\n> ║ 🏦 𝗚𝗮𝘁𝗲: {gate}\n> ║ 💵 𝗙𝘂𝗻𝗱: `{sym}{final_amt}`\n> ╚════════════════════╝"
                    try: bot.send_message(proof_ch, text, parse_mode="Markdown")
                    except Exception: pass
                
                freq = max(1, int(s.get('fake_dep_freq', 2)))
                avg_sleep = 3600 / freq
                time.sleep(random.randint(int(avg_sleep * 0.7), int(avg_sleep * 1.3)))
            else: 
                time.sleep(300)
        except Exception: 
            time.sleep(300)

def auto_fake_order_cron():
    while True:
        try:
            s = get_settings()
            if s.get('fake_proof_status'):
                if s.get('night_mode') and 2 <= datetime.now().hour < 8:
                    time.sleep(3600)
                    continue
                    
                proof_ch = s.get('proof_channel')
                if proof_ch:
                    fake_uid = f"***{random.randint(1111, 9999)}"
                    min_ord = float(s.get('fake_order_min', 0.01))
                    max_ord = float(s.get('fake_order_max', 10.0))
                    cost_usd = random.uniform(min_ord, max_ord)
                    
                    currencies = [('$', 1.0), ('৳', 120.0), ('₹', 83.0)]
                    sym, rate = random.choice(currencies)
                    final_cost = round(cost_usd * rate, 2)
                    
                    services = handlers.get_cached_services()
                    s_name = handlers.clean_service_name(random.choice(services)['name'])[:18] + ".." if services else "Premium Service"
                    qty = random.randint(1, 50) * 100 
                    
                    text = f"> ╔════ 🟢 𝗡𝗘𝗪 𝗢𝗥𝗗𝗘𝗥 ════╗\n> ║ 👤 𝗜𝗗: `{fake_uid}`\n> ║ 🚀 𝗦𝗲𝗿𝘃𝗶𝗰𝗲: {s_name}\n> ║ 📦 𝗤𝘁𝘆: {qty}\n> ║ 💵 𝗖𝗼𝘀𝘁: `{sym}{final_cost}`\n> ╚════════════════════╝"
                    try: bot.send_message(proof_ch, text, parse_mode="Markdown")
                    except Exception: pass
                
                freq = max(1, int(s.get('fake_ord_freq', 3)))
                avg_sleep = 3600 / freq
                time.sleep(random.randint(int(avg_sleep * 0.7), int(avg_sleep * 1.3)))
            else: 
                time.sleep(300)
        except Exception: 
            time.sleep(300)

threading.Thread(target=auto_fake_deposit_cron, daemon=True).start()
threading.Thread(target=auto_fake_order_cron, daemon=True).start()

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
    return "<h1>Nexus SMM Titan Bot is Running!</h1>"

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
# 6. ADMIN DASHBOARD & SETTINGS
# ==========================================
@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    settings = get_settings()
    users = list(users_col.find().sort("joined", -1))
    orders = list(orders_col.find().sort("date", -1).limit(200))
    tickets = list(tickets_col.find().sort("date", -1))
    vouchers = list(vouchers_col.find().sort("_id", -1))
    
    completed_orders = [o for o in orders_col.find({"status": "completed"})]
    total_sales = sum(o.get('cost', 0) for o in completed_orders)
    margin = settings.get("profit_margin", 20.0)
    live_profit = total_sales - (total_sales / (1 + (margin / 100))) if margin > 0 else 0.0
    
    return render_template(
        'admin.html', 
        users=users, orders=orders, tickets=tickets, vouchers=vouchers, 
        u_count=len(users), o_count=len(orders), bal=api.get_balance(), 
        s=settings, profit=round(live_profit, 2), sales=round(total_sales, 2)
    )

@app.route('/settings', methods=['POST'])
def update_settings():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    config_col.update_one({"_id": "settings"}, {"$set": {
        "profit_margin": float(request.form.get('profit_margin', 20)),
        "maintenance": request.form.get('maintenance') == 'on',
        "maintenance_msg": request.form.get('maintenance_msg', 'Bot is upgrading.'),
        "log_channel": request.form.get('log_channel', '').strip(),
        "proof_channel": request.form.get('proof_channel', '').strip(),
        
        "flash_sale_active": request.form.get('flash_sale_active') == 'on',
        "flash_sale_discount": float(request.form.get('flash_sale_discount', 0.0)),
        
        "welcome_bonus_active": request.form.get('welcome_bonus_active') == 'on',
        "welcome_bonus": float(request.form.get('welcome_bonus', 0.0)),
        "ref_bonus": float(request.form.get('ref_bonus', 0.05)),
        "dep_commission": float(request.form.get('dep_commission', 5.0)),
        
        "reward_top1": float(request.form.get('reward_top1', 10.0)),
        "reward_top2": float(request.form.get('reward_top2', 5.0)),
        "reward_top3": float(request.form.get('reward_top3', 2.0)),
        
        "fake_proof_status": request.form.get('fake_proof_status') == 'on',
        "night_mode": request.form.get('night_mode') == 'on',
        "fake_deposit_min": float(request.form.get('fake_deposit_min', 0.01)),
        "fake_deposit_max": float(request.form.get('fake_deposit_max', 20)),
        "fake_order_min": float(request.form.get('fake_order_min', 0.01)),
        "fake_order_max": float(request.form.get('fake_order_max', 10)),
        "fake_dep_freq": int(request.form.get('fake_dep_freq', 2)),
        "fake_ord_freq": int(request.form.get('fake_ord_freq', 3)),
        
        "channels": [c.strip() for c in request.form.get('channels', '').split(',') if c.strip()],
        "payments": [{"name": n, "rate": float(r)} for n, r in zip(request.form.getlist('pay_name[]'), request.form.getlist('pay_rate[]')) if n and r]
    }})
    return redirect(url_for('admin_dashboard'))

# ==========================================
# 7. GOD MODE & REWARDS ROUTES
# ==========================================
@app.route('/reset_monthly')
def reset_monthly():
    if not session.get('logged_in'): return redirect(url_for('login'))
    users_col.update_many({}, {"$set": {"spent": 0.0, "ref_earnings": 0.0}})
    try: bot.send_message(ADMIN_ID, "♻️ **MONTHLY RESET COMPLETE!**\nAll user spents and referral earnings have been reset to 0.", parse_mode="Markdown")
    except Exception: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/edit_user', methods=['POST'])
def edit_user():
    if not session.get('logged_in'): return redirect(url_for('login'))
    uid = int(request.form.get('user_id'))
    tier_override = request.form.get('tier_override', '')
    if tier_override == "none": tier_override = None
    users_col.update_one({"_id": uid}, {"$set": {
        "balance": float(request.form.get('balance', 0)),
        "spent": float(request.form.get('spent', 0)),
        "ref_earnings": float(request.form.get('ref_earnings', 0)),
        "custom_discount": float(request.form.get('custom_discount', 0)),
        "tier_override": tier_override
    }})
    return redirect(url_for('admin_dashboard'))

@app.route('/toggle_shadow_ban/<int:uid>')
def toggle_shadow_ban(uid):
    if not session.get('logged_in'): return redirect(url_for('login'))
    u = users_col.find_one({"_id": uid})
    if u: users_col.update_one({"_id": uid}, {"$set": {"shadow_banned": not u.get('shadow_banned', False)}})
    return redirect(url_for('admin_dashboard'))

@app.route('/override_order/<int:oid>/<status>')
def override_order(oid, status):
    if not session.get('logged_in'): return redirect(url_for('login'))
    orders_col.update_one({"oid": oid}, {"$set": {"status": status}})
    return redirect(url_for('admin_dashboard'))

# ==========================================
# 8. STANDARD ROUTES
# ==========================================
@app.route('/export_csv')
def export_csv_web():
    if not session.get('logged_in'): return redirect(url_for('login'))
    users = users_col.find()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["UID", "Name", "Balance(USD)", "Spent", "Ref Earned", "Joined"])
    for u in users: writer.writerow([u["_id"], u.get("name", "N/A"), u.get("balance", 0), u.get("spent", 0), u.get("ref_earnings", 0), u.get("joined", "N/A")])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=users.csv"})

@app.route('/wake_sleepers')
def wake_sleepers_web():
    if not session.get('logged_in'): return redirect(url_for('login'))
    sleepers = users_col.find({"last_active": {"$lt": datetime.now() - timedelta(days=3)}})
    def task():
        for u in sleepers:
            try: bot.send_message(u['_id'], "👋 **We Miss You!**\nCome back and check out our new fast services.", parse_mode="Markdown"); time.sleep(0.2)
            except Exception: pass
    threading.Thread(target=task, daemon=True).start()
    return redirect(url_for('admin_dashboard'))

@app.route('/smart_cast', methods=['POST'])
def smart_cast_web():
    if not session.get('logged_in'): return redirect(url_for('login'))
    msg = request.form.get('msg')
    if msg:
        active_users = orders_col.distinct("uid", {"date": {"$gte": datetime.now() - timedelta(days=7)}})
        def task():
            for uid in active_users:
                try: bot.send_message(uid, f"🎁 **EXCLUSIVE OFFER**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown"); time.sleep(0.2)
                except Exception: pass
        threading.Thread(target=task, daemon=True).start()
    return redirect(url_for('admin_dashboard'))

@app.route('/approve_dep/<uid>/<amt>/<tid>')
def approve_dep(uid, amt, tid):
    try:
        user_id, amount = int(uid), float(amt)
        users_col.update_one({"_id": user_id}, {"$inc": {"balance": amount}})
        bot.send_message(user_id, f"✅ **DEPOSIT APPROVED!**\nAmount: `${amount}` added.\nTrxID: `{tid}`", parse_mode="Markdown")
        bot.send_message(ADMIN_ID, f"✅ Approved ${amount} for User ID: {uid}")
        
        s = get_settings()
        user = users_col.find_one({"_id": user_id})
        
        # Affiliate Deposit Commission
        if user and user.get("ref_by"):
            comm_pct = s.get('dep_commission', 0.0)
            if comm_pct > 0:
                comm_amt = amount * (comm_pct / 100)
                users_col.update_one({"_id": user["ref_by"]}, {"$inc": {"balance": comm_amt, "ref_earnings": comm_amt}})
                try: bot.send_message(user["ref_by"], f"🎉 **LIFETIME COMMISSION!**\nYour referral `{user_id}` deposited funds. You earned `${comm_amt:.3f}`!", parse_mode="Markdown")
                except Exception: pass

        # Real Proof to Channel
        proof_ch = s.get('proof_channel')
        if proof_ch:
            text = f"> ╔═══ 💳 𝗡𝗘𝗪 𝗗𝗘𝗣𝗢𝗦𝗜𝗧 ═══╗\n> ║ 👤 𝗜𝗗: `***{str(uid)[-4:]}`\n> ║ 🏦 𝗚𝗮𝘁𝗲: Verified User\n> ║ 💵 𝗙𝘂𝗻𝗱: `${amount}`\n> ╚════════════════════╝"
            try: bot.send_message(proof_ch, text, parse_mode="Markdown")
            except Exception: pass
    except Exception: pass
    return "<h3>Action Completed.</h3>"

@app.route('/reject_dep/<uid>/<tid>')
def reject_dep(uid, tid):
    try: bot.send_message(int(uid), f"❌ **DEPOSIT REJECTED!**\nTrxID `{tid}` was invalid.", parse_mode="Markdown")
    except Exception: pass
    return "<h3>Action Completed.</h3>"

@app.route('/ban_user/<int:user_id>')
def ban_user(user_id):
    if session.get('logged_in'): users_col.update_one({"_id": user_id}, {"$set": {"banned": True}})
    return redirect(url_for('admin_dashboard'))

@app.route('/unban_user/<int:user_id>')
def unban_user(user_id):
    if session.get('logged_in'): users_col.update_one({"_id": user_id}, {"$set": {"banned": False}})
    return redirect(url_for('admin_dashboard'))

@app.route('/add_fake_user', methods=['POST'])
def add_fake_user():
    if session.get('logged_in'):
        users_col.insert_one({"_id": random.randint(100000, 999999), "name": request.form.get('fake_name'), "balance": 0.0, "spent": float(request.form.get('fake_spent', 0)), "ref_earnings": float(request.form.get('fake_ref', 0)), "joined": datetime.now(), "is_fake": True})
    return redirect(url_for('admin_dashboard'))

@app.route('/refund_order/<oid>')
def refund_order(oid):
    if session.get('logged_in'):
        order = orders_col.find_one({"oid": int(oid)})
        if order and order.get('status') != 'refunded':
            users_col.update_one({"_id": order['uid']}, {"$inc": {"balance": order['cost'], "spent": -order['cost']}})
            orders_col.update_one({"oid": int(oid)}, {"$set": {"status": "refunded"}})
            try: bot.send_message(order['uid'], f"💸 **ORDER REFUNDED (By Admin)!**\nAmount: `${order['cost']}` returned.")
            except Exception: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_order/<oid>')
def delete_order(oid):
    if session.get('logged_in'): orders_col.delete_one({"oid": int(oid)})
    return redirect(url_for('admin_dashboard'))

@app.route('/create_voucher', methods=['POST'])
def create_voucher():
    if session.get('logged_in'): vouchers_col.insert_one({"code": request.form.get('code').upper(), "amount": float(request.form.get('amount')), "limit": int(request.form.get('limit')), "used_by": []})
    return redirect(url_for('admin_dashboard'))

@app.route('/reply_ticket', methods=['POST'])
def reply_ticket():
    if session.get('logged_in'):
        reply = request.form.get('reply_msg')
        uid = int(request.form.get('uid'))
        tickets_col.update_one({"_id": ObjectId(request.form.get('ticket_id'))}, {"$set": {"status": "answered", "reply": reply}})
        try: bot.send_message(uid, f"🎧 **SUPPORT REPLY**\n━━━━━━━━━━━━━━━━━━━━\n{reply}", parse_mode="Markdown")
        except Exception: pass
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_ticket/<tid>')
def delete_ticket(tid):
    if session.get('logged_in'): tickets_col.delete_one({"_id": ObjectId(tid)})
    return redirect(url_for('admin_dashboard'))

@app.route('/send_broadcast', methods=['POST'])
def send_broadcast():
    if session.get('logged_in'):
        msg = request.form.get('msg')
        if msg:
            def task():
                for u in users_col.find({"is_fake": {"$ne": True}}):
                    try: bot.send_message(u['_id'], f"📢 **IMPORTANT NOTICE**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown"); time.sleep(0.2)
                    except Exception: pass
            threading.Thread(target=task, daemon=True).start()
    return redirect(url_for('admin_dashboard'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
