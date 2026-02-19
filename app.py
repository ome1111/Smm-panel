from flask import Flask, request, render_template, session, redirect, url_for, flash
from telebot import types
import os
import time
from config import BOT_TOKEN, ADMIN_PASSWORD, SECRET_KEY
from loader import bot, users_col, orders_col
import handlers  # এটি বটের মেসেজ হ্যান্ডলারগুলোকে সচল রাখবে
import api

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ==========================================
# ১. ওয়েব-হুক সেটআপ ও স্ট্যাটাস (Index Route)
# ==========================================
@app.route("/")
def index():
    """ব্রাউজারে মেইন লিঙ্ক ওপেন করলেই ওয়েব-হুক অটো কানেক্ট হবে"""
    bot.remove_webhook()
    time.sleep(1)
    
    url = os.environ.get('RENDER_EXTERNAL_URL')
    if url:
        webhook_url = f"{url.rstrip('/')}/{BOT_TOKEN}"
        try:
            bot.set_webhook(url=webhook_url)
            return f"""
            <body style='background:#0f172a; color:#38bdf8; text-align:center; padding-top:100px; font-family:sans-serif;'>
                <h1>🚀 System is Online!</h1>
                <p style='color:#4ade80;'>Webhook Connected Successfully.</p>
                <hr style='border: 1px solid #1e293b; width: 300px;'>
                <a href='/admin' style='color:#f8fafc; text-decoration:none; font-weight:bold;'>Go to Admin Panel &rarr;</a>
            </body>
            """, 200
        except Exception as e:
            return f"<h1>❌ Webhook Error</h1><p>{e}</p>", 500
            
    return "<h1>⚠️ Setup Missing</h1><p>RENDER_EXTERNAL_URL is not set.</p>", 500

# ==========================================
# ২. টেলিগ্রাম ওয়েব-হুক রিসিভার
# ==========================================
@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

# ==========================================
# ৩. অ্যাডমিন লগইন সিস্টেম
# ==========================================
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

# ==========================================
# ৪. অ্যাডমিন ড্যাশবোর্ড (Stats & Control)
# ==========================================
@app.route('/admin')
def admin_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    try:
        # ডাটাবেস থেকে রিয়েল-টাইম তথ্য আনা
        recent_users = list(users_col.find().sort("joined", -1).limit(100))
        total_revenue = sum(u.get('spent', 0) for u in users_col.find())
        
        stats = {
            'users': users_col.count_documents({}),
            'orders': orders_col.count_documents({}),
            'revenue': round(total_revenue, 2),
            'api_status': api.get_balance()
        }
    except Exception as e:
        stats = {'users': 0, 'orders': 0, 'revenue': 0, 'api_status': "API Error"}
        recent_users = []

    return render_template('admin.html', stats=stats, users=recent_users)

# ==========================================
# ৫. অ্যাডমিন অ্যাকশন (Balance, Ban, Broadcast)
# ==========================================
@app.route('/add_balance/<int:user_id>', methods=['POST'])
def add_balance(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    try:
        amount = float(request.form.get('amount', 0))
        if amount > 0:
            users_col.update_one({"_id": user_id}, {"$inc": {"balance": amount}})
            bot.send_message(user_id, f"🎉 **DEPOSIT SUCCESSFUL!**\n━━━━━━━━━━━━━━━━━━━━\nAdmin added **${amount}** to your balance.\nEnjoy our services!", parse_mode="Markdown")
    except: pass
    
    return redirect(url_for('admin_dashboard'))

@app.route('/ban_user/<int:user_id>')
def ban_user(user_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    users_col.update_one({"_id": user_id}, {"$set": {"balance": -99999}})
    try: bot.send_message(user_id, "🚫 **YOU HAVE BEEN BANNED BY THE ADMIN.**", parse_mode="Markdown")
    except: pass
    
    return redirect(url_for('admin_dashboard'))

@app.route('/send_broadcast', methods=['POST'])
def send_broadcast():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    msg = request.form.get('msg')
    if msg:
        def broadcast_task():
            for user in users_col.find({}):
                try: bot.send_message(user['_id'], f"📢 **ADMIN BROADCAST**\n━━━━━━━━━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
                except: pass
        
        # থ্রেডিং ব্যবহার করা হয়েছে যাতে ব্রডকাস্টের সময় সাইট হ্যাং না হয়
        import threading
        threading.Thread(target=broadcast_task).start()
        
    return redirect(url_for('admin_dashboard'))

# ==========================================
# ৬. ফ্লাস্ক সার্ভার রানার
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
