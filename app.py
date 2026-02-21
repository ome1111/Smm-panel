from flask import Flask, request, render_template, session, redirect, url_for, jsonify
import telebot
from telebot import types
import os
import time
import logging
import random
import threading
from datetime import datetime, timedelta
from bson.objectid import ObjectId

# Import custom configurations and database collections
from config import BOT_TOKEN, ADMIN_PASSWORD, SECRET_KEY, ADMIN_ID
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, logs_col
import api
import handlers  # Connects all bot functionalities

# ==========================================
# ১. FLASK APP & LOGGING SETUP
# ==========================================
app = Flask(__name__)
app.secret_key = SECRET_KEY
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')

# Set up logging for debugging
logging.basicConfig(level=logging.INFO)
telebot.logger.setLevel(logging.INFO)


# ==========================================
# ২. SYSTEM HELPERS & CONFIGS
# ==========================================
def get_settings():
    """Fetches system settings from the database. Creates default if none exists."""
    settings = config_col.find_one({"_id": "settings"})
    
    if not settings:
        settings = {
            "_id": "settings", 
            "channels": [], 
            "profit_margin": 20.0, 
            "maintenance": False, 
            "payments": [], 
            "ref_target": 10, 
            "ref_bonus": 5.0, 
            "dep_commission": 5.0, 
            "hidden_services": [],
            "log_channel": ""
        }
        config_col.insert_one(settings)
        
    return settings


# ==========================================
# ৩. WEBHOOK AUTO-RESTART THREAD
# ==========================================
def set_webhook_auto():
    """Ensures the bot stays online even if the Render server restarts."""
    try:
        logging.info("Attempting to set webhook...")
        bot.remove_webhook()
        time.sleep(2)
        webhook_url = f"{BASE_URL}/{BOT_TOKEN}"
        bot.set_webhook(url=webhook_url)
        logging.info(f"✅ Webhook successfully set to: {webhook_url}")
    except Exception as e:
        logging.error(f"❌ Webhook Auto-Restart Error: {e}")

# Start the webhook thread
threading.Thread(target=set_webhook_auto, daemon=True).start()


# ==========================================
# ৪. AUTO-REFUND SYSTEM CRON JOB
# ==========================================
def auto_refund_cron():
    """Checks pending orders and refunds users if the main panel fails 3 times."""
    while True:
        try:
            # Find all orders that are not yet completed, canceled, or refunded
            active_orders = orders_col.find({
                "status": {"$in": ["pending", "processing", "in progress"]}
            })
            
            for order in active_orders:
                order_id = order.get('oid')
                uid = order.get('uid')
                cost = order.get('cost', 0)
                
                # Fetch live status from main panel
                res = api.get_order_status(order_id)
                
                if res and 'status' in res:
                    status = str(res['status']).lower()
                    
                    if status in ['canceled', 'partial', 'error', 'fail']:
                        attempts = order.get('attempts', 0) + 1
                        
                        if attempts >= 3:
                            # 3 times failed -> Process Refund
                            users_col.update_one(
                                {"_id": uid}, 
                                {"$inc": {"balance": cost, "spent": -cost}}
                            )
                            orders_col.update_one(
                                {"_id": order['_id']}, 
                                {"$set": {"status": "refunded", "attempts": attempts}}
                            )
                            
                            # Notify User
                            try:
                                bot.send_message(
                                    uid, 
                                    f"⚠️ **ORDER REFUNDED**\nYour Order `{order_id}` failed on the server. `{cost}` USD has been returned to your wallet.", 
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                pass
                                
                        else:
                            # Retry the order silently
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
                        # Update the latest valid status
                        orders_col.update_one(
                            {"_id": order['_id']}, 
                            {"$set": {"status": status}}
                        )
                        
        except Exception as e:
            logging.error(f"Auto-Refund Cron Error: {e}")
            
        # Wait 5 minutes before checking again
        time.sleep(300)

# Start the auto-refund thread
threading.Thread(target=auto_refund_cron, daemon=True).start()


# ==========================================
# ৫. WEBHOOK & INDEX ROUTES
# ==========================================
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def webhook():
    """Receives updates from Telegram and passes them to the bot handlers."""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Forbidden', 403

@app.route("/")
def index():
    """Simple health check route for UptimeRobot."""
    return "<h1>Nexus SMM Titan Bot is Running Smoothly!</h1>"


# ==========================================
# ৬. AUTHENTICATION ROUTES
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login page."""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('login.html', error="Invalid Access Passcode!")
            
    # If already logged in, redirect to dashboard
    if session.get('logged_in'):
        return redirect(url_for('admin_dashboard'))
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logs out the admin."""
    session.clear()
    return redirect(url_for('login'))


# ==========================================
# ৭. ADMIN DASHBOARD ROUTE
# ==========================================
@app.route('/admin')
def admin_dashboard():
    """Main admin dashboard rendering with all statistics."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    settings = get_settings()
    
    # Fetch Data from MongoDB
    users = list(users_col.find().sort("joined", -1))
    orders = list(orders_col.find().sort("date", -1).limit(150))
    tickets = list(tickets_col.find().sort("date", -1))
    vouchers = list(vouchers_col.find().sort("_id", -1))
    
    # Calculate Statistics
    u_count = len(users)
    o_count = len(orders)
    
    # 🔥 LIVE PROFIT CALCULATOR
    completed_orders = [o for o in orders_col.find({"status": "completed"})]
    total_sales = sum(o.get('cost', 0) for o in completed_orders)
    
    margin = settings.get("profit_margin", 20.0)
    # Formula: Sale Price - Buying Price
    # Buying Price = Sale Price / (1 + (Margin / 100))
    if margin > 0:
        buying_price = total_sales / (1 + (margin / 100))
        live_profit = total_sales - buying_price
    else:
        live_profit = 0.0
        
    # Fetch Main Panel Balance
    main_balance = api.get_balance()
    
    return render_template(
        'admin.html', 
        users=users, 
        orders=orders, 
        tickets=tickets, 
        vouchers=vouchers,
        u_count=u_count, 
        o_count=o_count, 
        bal=main_balance, 
        s=settings, 
        profit=round(live_profit, 2), 
        sales=round(total_sales, 2)
    )


# ==========================================
# ৮. SETTINGS & CONFIGURATION ROUTES
# ==========================================
@app.route('/settings', methods=['POST'])
def update_settings():
    """Updates global bot settings, profit margins, and payment methods."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    try:
        profit_margin = float(request.form.get('profit_margin', 20))
        maintenance = request.form.get('maintenance') == 'on'
        
        # Process Channels List
        channels_raw = request.form.get('channels', '')
        channels = [c.strip() for c in channels_raw.split(',') if c.strip()]
        
        # Process Payment Methods
        pay_names = request.form.getlist('pay_name[]')
        pay_rates = request.form.getlist('pay_rate[]')
        
        payments = []
        for name, rate in zip(pay_names, pay_rates):
            if name and rate:
                payments.append({"name": name, "rate": float(rate)})
        
        # Update Database
        config_col.update_one(
            {"_id": "settings"}, 
            {"$set": {
                "profit_margin": profit_margin,
                "maintenance": maintenance,
                "channels": channels,
                "payments": payments
            }}
        )
    except Exception as e:
        logging.error(f"Settings Update Error: {e}")
        
    return redirect(url_for('admin_dashboard'))


# ==========================================
# ৯. USER & DEPOSIT MANAGEMENT ROUTES
# ==========================================
@app.route('/approve_dep/<uid>/<amt>/<tid>')
def approve_dep(uid, amt, tid):
    """Approves a user's deposit request directly from Telegram URL."""
    try:
        user_id = int(uid)
        amount = float(amt)
        
        # Add balance to user
        users_col.update_one({"_id": user_id}, {"$inc": {"balance": amount}})
        
        # Notify User
        success_msg = f"✅ **DEPOSIT APPROVED!**\nAmount: `${amount}` added to your wallet.\nTrxID: `{tid}`"
        bot.send_message(user_id, success_msg, parse_mode="Markdown")
        
        # Notify Admin
        bot.send_message(ADMIN_ID, f"✅ Approved ${amount} for User ID: {user_id}")
        
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Error Approving Deposit: {e}")
        
    return "<h3>Action Completed. Deposit Approved! You can safely close this window.</h3>"

@app.route('/reject_dep/<uid>/<tid>')
def reject_dep(uid, tid):
    """Rejects a user's deposit request."""
    try:
        user_id = int(uid)
        
        # Notify User
        reject_msg = f"❌ **DEPOSIT REJECTED!**\nTrxID `{tid}` was invalid, used, or not received. Contact Admin for support."
        bot.send_message(user_id, reject_msg, parse_mode="Markdown")
        
        # Notify Admin
        bot.send_message(ADMIN_ID, f"❌ Rejected TrxID: {tid} for User ID: {user_id}")
        
    except Exception as e:
        pass
        
    return "<h3>Action Completed. Deposit Rejected! You can safely close this window.</h3>"

@app.route('/ban_user/<int:user_id>')
def ban_user(user_id):
    """Bans a user from using the bot."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    users_col.update_one({"_id": user_id}, {"$set": {"banned": True}})
    
    try: 
        bot.send_message(user_id, "🚫 **ACCESS DENIED.** You have been permanently banned by the administrator.", parse_mode="Markdown")
    except Exception: 
        pass
        
    return redirect(url_for('admin_dashboard'))

@app.route('/unban_user/<int:user_id>')
def unban_user(user_id):
    """Unbans a user."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    users_col.update_one({"_id": user_id}, {"$set": {"banned": False}})
    
    try: 
        bot.send_message(user_id, "✅ **ACCOUNT RESTORED.** Your ban has been lifted.", parse_mode="Markdown")
    except Exception: 
        pass
        
    return redirect(url_for('admin_dashboard'))

@app.route('/add_fake_user', methods=['POST'])
def add_fake_user():
    """Adds a fake user to the database for leaderboard showcasing."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    name = request.form.get('fake_name')
    spent = float(request.form.get('fake_spent', 0))
    fake_id = random.randint(100000, 999999)
    
    users_col.insert_one({
        "_id": fake_id, 
        "name": name, 
        "balance": 0.0, 
        "spent": spent, 
        "joined": datetime.now(), 
        "is_fake": True
    })
    
    return redirect(url_for('admin_dashboard'))


# ==========================================
# ১০. ORDER MANAGEMENT ROUTES
# ==========================================
@app.route('/refund_order/<oid>')
def refund_order(oid):
    """Manually refunds an order and returns the balance to the user."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    try:
        order_id = int(oid)
        order = orders_col.find_one({"oid": order_id})
        
        if order and order.get('status') != 'refunded':
            user_id = order['uid']
            cost = order['cost']
            
            # Return Balance
            users_col.update_one(
                {"_id": user_id}, 
                {"$inc": {"balance": cost, "spent": -cost}}
            )
            
            # Mark as Refunded
            orders_col.update_one({"oid": order_id}, {"$set": {"status": "refunded"}})
            
            # Notify User
            bot.send_message(
                user_id, 
                f"💸 **ORDER REFUNDED (By Admin)!**\nAmount: `${cost}` has been safely returned to your wallet.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logging.error(f"Manual Refund Error: {e}")
        
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_order/<oid>')
def delete_order(oid):
    """Deletes an order from the database permanently."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    orders_col.delete_one({"oid": int(oid)})
    return redirect(url_for('admin_dashboard'))


# ==========================================
# ১১. VOUCHERS & TICKETS ROUTES
# ==========================================
@app.route('/create_voucher', methods=['POST'])
def create_voucher():
    """Creates a new promotional voucher code."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    code = request.form.get('code').upper()
    amount = float(request.form.get('amount'))
    limit = int(request.form.get('limit'))
    
    # Insert new voucher
    vouchers_col.insert_one({
        "code": code, 
        "amount": amount, 
        "limit": limit, 
        "used_by": []
    })
    
    return redirect(url_for('admin_dashboard'))

@app.route('/reply_ticket', methods=['POST'])
def reply_ticket():
    """Replies to a user's support ticket and notifies them via Bot."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    tid = request.form.get('ticket_id')
    uid = int(request.form.get('uid'))
    reply_msg = request.form.get('reply_msg')
    
    # Update Ticket Status
    tickets_col.update_one(
        {"_id": ObjectId(tid)}, 
        {"$set": {"status": "answered", "reply": reply_msg}}
    )
    
    # Send Reply to User
    try: 
        bot.send_message(
            uid, 
            f"🎧 **SUPPORT REPLY**\n━━━━━━━━━━━━━━━━━━━━\n{reply_msg}", 
            parse_mode="Markdown"
        )
    except Exception: 
        pass
        
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_ticket/<tid>')
def delete_ticket(tid):
    """Deletes a closed support ticket."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    tickets_col.delete_one({"_id": ObjectId(tid)})
    return redirect(url_for('admin_dashboard'))


# ==========================================
# ১২. BROADCAST SYSTEM
# ==========================================
@app.route('/send_broadcast', methods=['POST'])
def send_broadcast():
    """Sends a global broadcast message to all non-fake users."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    msg = request.form.get('msg')
    
    if msg:
        def broadcast_task():
            real_users = users_col.find({"is_fake": {"$ne": True}})
            for user in real_users:
                try: 
                    bot.send_message(
                        user['_id'], 
                        f"📢 **IMPORTANT NOTICE**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", 
                        parse_mode="Markdown"
                    )
                    # Small delay to prevent hitting Telegram API limits
                    time.sleep(0.1) 
                except Exception: 
                    pass
                    
        # Run broadcast in background so admin panel doesn't freeze
        threading.Thread(target=broadcast_task, daemon=True).start()
        
    return redirect(url_for('admin_dashboard'))


# ==========================================
# RUN THE APPLICATION
# ==========================================
if __name__ == "__main__":
    # Get port from environment variables, default to 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
