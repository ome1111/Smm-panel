import os
import time
import random
import threading
import csv
import json
from io import StringIO
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, Response
import telebot
from bson.objectid import ObjectId

# Import from loader and config
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col
from config import BOT_TOKEN, ADMIN_ID, ADMIN_PASSWORD

# 🔥 NEW: handlers এর বদলে নতুন ৩টি ফাইল ইমপোর্ট করা হলো
import utils
import admin
import main_router

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_nexus_titan_key_1010')

# ==========================================
# 1. WEBHOOK FAST ENGINE (10x Speed)
# ==========================================
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        threading.Thread(target=bot.process_new_updates, args=([update],)).start()
        return 'OK', 200
    return 'Forbidden', 403

@app.route('/set_webhook')
def manual_set_webhook():
    bot.remove_webhook()
    time.sleep(1)
    RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')
    success = bot.set_webhook(url=f"{RENDER_URL.rstrip('/')}/{BOT_TOKEN}")
    if success:
        return "<h1>✅ Webhook Connected Successfully!</h1><p>Your Bot is now LIVE and running fast!</p>"
    else:
        return "<h1>❌ Webhook Connection Failed!</h1><p>Check Render Logs.</p>"

# ==========================================
# 2. CYBER BOX AUTO ENGINE (100% Realistic Fake Proofs)
# ==========================================
def auto_fake_proof_cron():
    while True:
        try:
            s = config_col.find_one({"_id": "settings"})
            if not s or not s.get('fake_proof_status', False):
                time.sleep(60)
                continue

            if s.get('night_mode', False):
                hour = datetime.now().hour
                if 2 <= hour <= 8:
                    time.sleep(3600)
                    continue

            proof_channel = s.get('proof_channel', '')
            if not proof_channel:
                time.sleep(60)
                continue

            dep_freq = s.get('fake_dep_freq', 2)
            ord_freq = s.get('fake_ord_freq', 3)

            time.sleep(random.randint(15, 75))

            # 💰 FAKE DEPOSIT GENERATOR
            if random.random() < (dep_freq / 60): 
                gateways = ["bKash Auto", "Nagad Express", "Binance Pay", "USDT TRC20", "PerfectMoney"]
                method = random.choice(gateways)
                
                is_crypto = any(x in method.lower() for x in ['usdt', 'binance', 'crypto', 'btc', 'pm', 'perfect'])
                
                if is_crypto:
                    amt = round(random.uniform(2.5, 30.0), 2)
                    display_amt = f"${amt}"
                else:
                    amt = random.choice([50, 100, 150, 200, 300, 500, 1000, 1500, 2000, 5000])
                    curr_sym = "৳" if any(x in method.lower() for x in ['bkash', 'nagad']) else random.choice(["৳", "₹"])
                    display_amt = f"{curr_sym}{amt}"
                
                fake_uid = str(random.randint(1000000, 9999999))
                masked_id = f"***{fake_uid[-4:]}"
                
                msg = f"```text\n╔══ 💰 𝗡𝗘𝗪 𝗗𝗘𝗣𝗢𝗦𝗜𝗧 ══╗\n║ 👤 𝗜𝗗: {masked_id}\n║ 🏦 𝗠𝗲𝘁𝗵𝗼𝗱: {method}\n║ 💵 𝗔𝗺𝗼𝘂𝗻𝘁: {display_amt}\n║ ✅ 𝗦𝘁𝗮𝘁𝘂𝘀: Approved\n╚════════════════════╝\n```"
                bot.send_message(proof_channel, msg, parse_mode="Markdown")

            # 🛒 FAKE ORDER GENERATOR
            if random.random() < (ord_freq / 60):
                qty = random.choice([500, 1000, 2000, 3000, 5000, 10000, 20000, 50000]) 
                
                # 🔥 CHANGED: handlers থেকে utils করা হয়েছে
                cached_services = utils.get_cached_services()
                if cached_services:
                    srv = random.choice(cached_services)
                    srv_name = utils.clean_service_name(srv['name'])
                    base_rate = float(srv.get('rate', 0.5))
                    cost_usd = (base_rate / 1000) * qty * 1.2
                else:
                    srv_name = "Premium Service ⚡"
                    cost_usd = (random.uniform(0.5, 2.5) / 1000) * qty
                    srv = {}
                    
                if cost_usd < 0.01: cost_usd = 0.12 
                
                curr_choice = random.choices(["USD", "BDT", "INR"], weights=[30, 50, 20])[0]
                if curr_choice == "USD":
                    display_cost = f"${round(cost_usd, 3)}"
                elif curr_choice == "BDT":
                    display_cost = f"৳{round(cost_usd * 120, 2)}"
                else:
                    display_cost = f"₹{round(cost_usd * 83, 2)}"

                short_srv = srv_name[:22] + ".." if len(srv_name) > 22 else srv_name
                fake_uid = str(random.randint(1000000, 9999999))
                masked_id = f"***{fake_uid[-4:]}"
                
                fake_oid = random.randint(350000, 999999)
                
                # 🔥 CHANGED: handlers থেকে utils করা হয়েছে
                platform = utils.identify_platform(srv.get('category', ''))
                if "Instagram" in platform: base_link = "https://instagram.com/p/"
                elif "Facebook" in platform: base_link = "https://facebook.com/"
                elif "YouTube" in platform: base_link = "https://youtube.com/watch?v="
                elif "TikTok" in platform: base_link = "https://tiktok.com/@user/video/"
                elif "Telegram" in platform: base_link = "https://t.me/"
                else: base_link = "https://link.to/"
                
                random_hash = ''.join(random.choices("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8))
                masked_link = f"{base_link}{random_hash[:4]}..."
                
                msg = f"```text\n╔════ 🟢 𝗡𝗘𝗪 𝗢𝗥𝗗𝗘𝗥 ════╗\n║ 🆔 𝗢𝗿𝗱𝗲𝗿: #{fake_oid}\n║ 👤 𝗨𝘀𝗲𝗿: {masked_id}\n║ 🚀 𝗦𝗲𝗿𝘃𝗶𝗰𝗲: {short_srv}\n║ 🔗 𝗟𝗶𝗻𝗸: {masked_link}\n║ 📦 𝗤𝘁𝘆: {qty}\n║ 💵 𝗖𝗼𝘀𝘁: {display_cost}\n╚════════════════════╝\n```"
                bot.send_message(proof_channel, msg, parse_mode="Markdown")

        except Exception:
            pass
        time.sleep(45)

threading.Thread(target=auto_fake_proof_cron, daemon=True).start()

# ==========================================
# 3. ADMIN WEB PANEL ROUTES (GOD MODE)
# ==========================================
def get_dashboard_stats():
    s = config_col.find_one({"_id": "settings"}) or {}
    u_count = users_col.count_documents({})
    bal = sum(u.get('balance', 0) for u in users_col.find())
    sales = sum(u.get('spent', 0) for u in users_col.find())
    profit = sales * (s.get('profit_margin', 20.0) / 100)
    return {"u_count": u_count, "bal": f"${bal:.2f}", "sales": f"${sales:.2f}", "profit": f"${profit:.2f}", "s": s}

@app.route('/')
def index():
    if 'admin' not in session: return redirect(url_for('login'))
    stats = get_dashboard_stats()
    users = list(users_col.find().sort("spent", -1))
    orders = list(orders_col.find().sort("_id", -1).limit(100))
    tickets = list(tickets_col.find().sort("_id", -1))
    vouchers = list(vouchers_col.find().sort("_id", -1))
    
    # 🔥 CHANGED: handlers থেকে utils করা হয়েছে
    services = utils.get_cached_services()
    unique_categories = sorted(list(set(s['category'] for s in services))) if services else []
    
    saved_orders_doc = config_col.find_one({"_id": "service_orders"}) or {}
    saved_service_orders = saved_orders_doc.get("orders", {})
    
    services_json = json.dumps(services)
    saved_service_orders_json = json.dumps(saved_service_orders)

    return render_template('admin.html', **stats, users=users, orders=orders, tickets=tickets, vouchers=vouchers, 
                           unique_categories=unique_categories, services_json=services_json, saved_service_orders=saved_service_orders_json)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('index'))
        return "Wrong Password!"
    return '''<form method="post" style="text-align:center; margin-top:20vh; font-family:sans-serif; background:#020617; color:white; height:100vh;">
              <h2>Nexus Titan God Mode</h2>
              <input type="password" name="password" placeholder="Admin Password" style="padding:10px; color:black;">
              <button type="submit" style="padding:10px 20px; background:#0ea5e9; color:white; border:none; cursor:pointer;">Login</button></form>'''

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('login'))

@app.route('/export_csv')
def export_csv():
    if 'admin' not in session: return redirect(url_for('login'))
    users = list(users_col.find().sort("spent", -1))
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['User ID', 'Name', 'Balance ($)', 'Spent ($)', 'Currency', 'Referral Earnings ($)', 'Joined Date', 'Last Active', 'Is Fake User'])
    
    for u in users:
        joined_date = u.get('joined', 'N/A')
        if isinstance(joined_date, datetime): joined_date = joined_date.strftime("%Y-%m-%d %H:%M")
        last_active = u.get('last_active', 'N/A')
        if isinstance(last_active, datetime): last_active = last_active.strftime("%Y-%m-%d %H:%M")
            
        cw.writerow([
            u.get('_id', 'N/A'), str(u.get('name', 'N/A')), round(u.get('balance', 0.0), 3),
            round(u.get('spent', 0.0), 3), u.get('currency', 'USD'), round(u.get('ref_earnings', 0.0), 3),
            joined_date, last_active, "Yes" if u.get('is_fake', False) else "No"
        ])
        
    output = Response(si.getvalue(), mimetype='text/csv')
    output.headers["Content-Disposition"] = f"attachment; filename=nexus_users_{datetime.now().strftime('%Y%m%d')}.csv"
    return output

@app.route('/save_best_choice', methods=['POST'])
def save_best_choice():
    if 'admin' not in session: return redirect(url_for('login'))
    raw_sids = request.form.get('best_choice_sids', '')
    sids = [s.strip() for s in raw_sids.split(',') if s.strip()]
    config_col.update_one({"_id": "settings"}, {"$set": {"best_choice_sids": sids}}, upsert=True)
    return redirect(url_for('index'))

@app.route('/save_service_order', methods=['POST'])
def save_service_order():
    if 'admin' not in session: return jsonify({"status": "error", "msg": "Unauthorized"})
    data = request.json
    cat = data.get('category')
    order = data.get('order')
    if cat and order:
        config_col.update_one({"_id": "service_orders"}, {"$set": {f"orders.{cat}": order}}, upsert=True)
    return jsonify({"status": "success"})

@app.route('/settings', methods=['POST'])
def save_settings():
    if 'admin' not in session: return redirect(url_for('login'))
    
    s = {
        "profit_margin": float(request.form.get('profit_margin', 20.0)),
        "channels": [c.strip() for c in request.form.get('channels', '').split(',') if c.strip()],
        "log_channel": request.form.get('log_channel', ''),
        "maintenance": 'maintenance' in request.form,
        "maintenance_msg": request.form.get('maintenance_msg', 'Bot is upgrading.'),
        "proof_channel": request.form.get('proof_channel', ''),
        "fake_dep_freq": int(request.form.get('fake_dep_freq', 2)),
        "fake_ord_freq": int(request.form.get('fake_ord_freq', 3)),
        "fake_deposit_min": float(request.form.get('fake_deposit_min', 0.01)),
        "fake_deposit_max": float(request.form.get('fake_deposit_max', 20.0)),
        "fake_order_min": float(request.form.get('fake_order_min', 0.01)),
        "fake_order_max": float(request.form.get('fake_order_max', 10.0)),
        "fake_proof_status": 'fake_proof_status' in request.form,
        "night_mode": 'night_mode' in request.form,
        "flash_sale_active": 'flash_sale_active' in request.form,
        "flash_sale_discount": float(request.form.get('flash_sale_discount', 0.0)),
        "welcome_bonus_active": 'welcome_bonus_active' in request.form,
        "welcome_bonus": float(request.form.get('welcome_bonus', 0.0)),
        "ref_bonus": float(request.form.get('ref_bonus', 0.05)),
        "dep_commission": float(request.form.get('dep_commission', 5.0)),
        "reward_top1": float(request.form.get('reward_top1', 10.0)),
        "reward_top2": float(request.form.get('reward_top2', 5.0)),
        "reward_top3": float(request.form.get('reward_top3', 2.0)),
        "best_choice_sids": config_col.find_one({"_id": "settings"}).get('best_choice_sids', []) if config_col.find_one({"_id": "settings"}) else []
    }
    
    payments = []
    pay_names = request.form.getlist('pay_name[]')
    pay_rates = request.form.getlist('pay_rate[]')
    pay_addrs = request.form.getlist('pay_address[]')
    
    for i in range(len(pay_names)):
        if pay_names[i].strip():
            payments.append({"name": pay_names[i].strip(), "rate": float(pay_rates[i]), "address": pay_addrs[i].strip()})
    s["payments"] = payments

    config_col.update_one({"_id": "settings"}, {"$set": s}, upsert=True)
    return redirect(url_for('index'))

@app.route('/edit_user', methods=['POST'])
def edit_user():
    if 'admin' not in session: return redirect(url_for('login'))
    uid = int(request.form.get('user_id'))
    bal_action = request.form.get('bal_action')
    bal_val = float(request.form.get('balance_val', 0))
    spent = float(request.form.get('spent', 0))
    ref_earn = float(request.form.get('ref_earnings', 0))
    discount = float(request.form.get('custom_discount', 0))
    tier = request.form.get('tier_override')
    if tier == 'none': tier = None

    update_query = {"spent": spent, "ref_earnings": ref_earn, "custom_discount": discount, "tier_override": tier}
    
    if bal_action == "set":
        update_query["balance"] = bal_val
        users_col.update_one({"_id": uid}, {"$set": update_query})
    elif bal_action == "add":
        users_col.update_one({"_id": uid}, {"$set": update_query, "$inc": {"balance": bal_val}})
    elif bal_action == "sub":
        users_col.update_one({"_id": uid}, {"$set": update_query, "$inc": {"balance": -bal_val}})
        
    return redirect(url_for('index'))

@app.route('/add_fake_user', methods=['POST'])
def add_fake_user():
    if 'admin' not in session: return redirect(url_for('login'))
    fake_id = random.randint(1000000, 9999999)
    name = request.form.get('fake_name')
    spent = float(request.form.get('fake_spent', 0))
    ref = float(request.form.get('fake_ref', 0))
    
    users_col.insert_one({"_id": fake_id, "name": name, "balance": 0.0, "spent": spent, "currency": "USD", "ref_earnings": ref, "is_fake": True, "joined": datetime.now()})
    return redirect(url_for('index'))

@app.route('/remove_fake_users')
def remove_fake_users():
    if 'admin' not in session: return redirect(url_for('login'))
    users_col.delete_many({"is_fake": True})
    return redirect(url_for('index'))

@app.route('/delete_user/<int:uid>')
def delete_user(uid):
    if 'admin' not in session: return redirect(url_for('login'))
    users_col.delete_one({"_id": uid})
    return redirect(url_for('index'))

@app.route('/toggle_shadow_ban/<int:uid>')
def toggle_shadow_ban(uid):
    if 'admin' not in session: return redirect(url_for('login'))
    u = users_col.find_one({"_id": uid})
    if u: users_col.update_one({"_id": uid}, {"$set": {"shadow_banned": not u.get('shadow_banned', False)}})
    return redirect(url_for('index'))

@app.route('/ban_user/<int:uid>')
def ban_user(uid):
    if 'admin' not in session: return redirect(url_for('login'))
    users_col.update_one({"_id": uid}, {"$set": {"banned": True}})
    return redirect(url_for('index'))

@app.route('/unban_user/<int:uid>')
def unban_user(uid):
    if 'admin' not in session: return redirect(url_for('login'))
    users_col.update_one({"_id": uid}, {"$set": {"banned": False}})
    return redirect(url_for('index'))

@app.route('/distribute_rewards')
def distribute_rewards():
    if 'admin' not in session: return redirect(url_for('login'))
    s = config_col.find_one({"_id": "settings"}) or {}
    r1, r2, r3 = s.get('reward_top1', 10.0), s.get('reward_top2', 5.0), s.get('reward_top3', 2.0)
    
    top_spenders = list(users_col.find({"spent": {"$gt": 0}}).sort("spent", -1).limit(3))
    rewards = [r1, r2, r3]
    for i, u in enumerate(top_spenders):
        if not u.get('is_fake'):
            users_col.update_one({"_id": u["_id"]}, {"$inc": {"balance": rewards[i]}})
            try: bot.send_message(u["_id"], f"🎉 **CONGRATULATIONS!**\nYou ranked #{i+1} Top Spender! Reward `${rewards[i]}` added.", parse_mode="Markdown")
            except: pass
        
    top_refs = list(users_col.find({"ref_earnings": {"$gt": 0}}).sort("ref_earnings", -1).limit(3))
    for i, u in enumerate(top_refs):
        if not u.get('is_fake'):
            users_col.update_one({"_id": u["_id"]}, {"$inc": {"balance": rewards[i]}})
            try: bot.send_message(u["_id"], f"🎉 **CONGRATULATIONS!**\nYou ranked #{i+1} Top Affiliate! Reward `${rewards[i]}` added.", parse_mode="Markdown")
            except: pass
        
    return redirect(url_for('index'))

@app.route('/reset_monthly')
def reset_monthly():
    if 'admin' not in session: return redirect(url_for('login'))
    users_col.update_many({}, {"$set": {"spent": 0.0, "ref_earnings": 0.0}})
    return redirect(url_for('index'))

@app.route('/approve_dep/<int:uid>/<amt>/<tid>')
def approve_dep(uid, amt, tid):
    users_col.update_one({"_id": uid}, {"$inc": {"balance": float(amt)}})
    u = users_col.find_one({"_id": uid})
    if u and u.get("ref_by"):
        s = config_col.find_one({"_id": "settings"}) or {}
        comm = float(amt) * (s.get("dep_commission", 5.0) / 100)
        if comm > 0:
            users_col.update_one({"_id": u["ref_by"]}, {"$inc": {"balance": comm, "ref_earnings": comm}})
            try: bot.send_message(u["ref_by"], f"💸 **COMMISSION EARNED!**\nYour referral made a deposit. You earned `${comm:.3f}`!", parse_mode="Markdown")
            except: pass
    try: bot.send_message(uid, f"✅ **DEPOSIT APPROVED!**\nAmount: `${float(amt):.2f}` added to your wallet.\nTrxID: `{tid}`", parse_mode="Markdown")
    except: pass
    return "✅ Deposit Approved and user notified. You can close this window."

@app.route('/reject_dep/<int:uid>/<tid>')
def reject_dep(uid, tid):
    try: bot.send_message(uid, f"❌ **DEPOSIT REJECTED!**\nYour TrxID `{tid}` was invalid. Contact Admin.", parse_mode="Markdown")
    except: pass
    return "❌ Deposit Rejected. User notified."

@app.route('/send_broadcast', methods=['POST'])
def send_bc():
    if 'admin' not in session: return redirect(url_for('login'))
    msg = request.form.get('msg')
    threading.Thread(target=bc_task, args=(msg,)).start()
    return redirect(url_for('index'))
    
def bc_task(msg):
    for u in users_col.find({"is_fake": {"$ne": True}}):
        try: bot.send_message(u["_id"], f"📢 **BROADCAST**\n━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
        except: pass

@app.route('/smart_cast', methods=['POST'])
def smart_cast():
    if 'admin' not in session: return redirect(url_for('login'))
    msg = request.form.get('msg')
    threading.Thread(target=smart_bc_task, args=(msg,)).start()
    return redirect(url_for('index'))

def smart_bc_task(msg):
    for u in users_col.find({"spent": {"$gt": 0}, "is_fake": {"$ne": True}}):
        try: bot.send_message(u["_id"], f"🎁 **EXCLUSIVE VIP OFFER**\n━━━━━━━━━━━━\n{msg}", parse_mode="Markdown")
        except: pass

@app.route('/create_voucher', methods=['POST'])
def create_voucher():
    if 'admin' not in session: return redirect(url_for('login'))
    code = request.form.get('code').upper()
    amt = float(request.form.get('amount', 0))
    limit = int(request.form.get('limit', 1))
    vouchers_col.insert_one({"code": code, "amount": amt, "limit": limit, "used_by": []})
    return redirect(url_for('index'))

@app.route('/reply_ticket', methods=['POST'])
def reply_ticket():
    if 'admin' not in session: return redirect(url_for('login'))
    tid = request.form.get('ticket_id')
    uid = int(request.form.get('uid'))
    msg = request.form.get('reply_msg')
    tickets_col.update_one({"_id": ObjectId(tid)}, {"$set": {"status": "closed", "reply": msg}})
    try: bot.send_message(uid, f"🎧 **TICKET UPDATE**\nAdmin Replied: {msg}", parse_mode="Markdown")
    except: pass
    return redirect(url_for('index'))

@app.route('/delete_ticket/<tid>')
def delete_ticket(tid):
    if 'admin' not in session: return redirect(url_for('login'))
    tickets_col.delete_one({"_id": ObjectId(tid)})
    return redirect(url_for('index'))

@app.route('/delete_order/<oid>')
def delete_order(oid):
    if 'admin' not in session: return redirect(url_for('login'))
    try: oid_val = int(oid)
    except: oid_val = oid
    orders_col.delete_one({"oid": oid_val})
    return redirect(url_for('index'))

@app.route('/override_order/<int:oid>/<status>')
def override_order(oid, status):
    if 'admin' not in session: return redirect(url_for('login'))
    orders_col.update_one({"oid": oid}, {"$set": {"status": status}})
    return redirect(url_for('index'))
    
@app.route('/refund_order/<int:oid>')
def refund_order(oid):
    if 'admin' not in session: return redirect(url_for('login'))
    o = orders_col.find_one({"oid": oid})
    if o and o.get('status') not in ['refunded', 'canceled']:
        users_col.update_one({"_id": o['uid']}, {"$inc": {"balance": o['cost'], "spent": -o['cost']}})
        orders_col.update_one({"oid": oid}, {"$set": {"status": "refunded"}})
        try: bot.send_message(o['uid'], f"💰 **ORDER REFUNDED!**\nOrder `{oid}` was refunded. `${o['cost']}` returned to your wallet.", parse_mode="Markdown")
        except: pass
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
