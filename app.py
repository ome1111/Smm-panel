import os
import time
import random
import threading
import csv
import json
import hashlib
import base64
import hmac
import math
import traceback
import logging
from io import StringIO
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, Response
import telebot
from bson.objectid import ObjectId
import re

# Import from loader and config
from loader import bot, users_col, orders_col, config_col, tickets_col, vouchers_col, redis_client, logs_col
from config import BOT_TOKEN, ADMIN_ID, ADMIN_PASSWORD

# Import modular handlers
import utils
import admin
import main_router

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_nexus_titan_key_1010')

# 🔥 ADMIN PANEL SECURITY (Cookie Theft Protection)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# app.config['SESSION_COOKIE_SECURE'] = True  # (Render-এ HTTPS থাকলে এটি Enable করতে পারেন)

# ==========================================
# 1. WEBHOOK FAST ENGINE (10x Speed & Memory Leak Fixed)
# ==========================================
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Forbidden', 403

@app.route('/set_webhook')
def manual_set_webhook():
    bot.remove_webhook()
    time.sleep(1)
    RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://smm-panel-g8ab.onrender.com')
    success = bot.set_webhook(url=f"{RENDER_URL.rstrip('/')}/{BOT_TOKEN}")
    if success:
        return "<h1>✅ Webhook Connected Successfully!</h1><p>Your Bot is now LIVE and running fast with Redis Cache & Async Workers!</p>"
    else:
        return "<h1>❌ Webhook Connection Failed!</h1><p>Check Render Logs.</p>"

# ==========================================
# 2. CYBER BOX AUTO ENGINE (Redis Distributed Lock)
# ==========================================
def auto_fake_proof_cron():
    while True:
        try:
            time.sleep(45)
            s = config_col.find_one({"_id": "settings"})
            if not s or not s.get('fake_proof_status', False):
                continue

            if s.get('night_mode', False):
                hour = datetime.now().hour
                if 2 <= hour <= 8:
                    continue

            proof_channel = s.get('proof_channel', '')
            if not proof_channel:
                continue

            # 🔥 Redis Lock
            if not redis_client.set("fake_proof_lock", "locked", nx=True, ex=40):
                continue

            dep_freq = s.get('fake_dep_freq', 2)
            ord_freq = s.get('fake_ord_freq', 3)

            # 💰 FAKE DEPOSIT GENERATOR
            if random.random() < (dep_freq / 60): 
                gateways = ["bKash Auto", "Nagad Express", "Binance Pay", "USDT TRC20", "PerfectMoney"]
                method = random.choice(gateways)
                
                is_crypto = any(x in method.lower() for x in ['usdt', 'binance', 'crypto', 'btc', 'pm', 'perfect'])
                
                if is_crypto:
                    amt = round(random.uniform(s.get('fake_deposit_min', 2.5), s.get('fake_deposit_max', 30.0)), 2)
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
                
                cached_services = utils.get_cached_services()
                if cached_services:
                    srv = random.choice(cached_services)
                    srv_name = utils.clean_service_name(srv['name'])
                    base_rate = float(srv.get('rate', 0.5))
                    cost_usd = (base_rate / 1000) * qty * 1.2
                else:
                    srv_name = "Premium Service ⚡"
                    cost_usd = (random.uniform(s.get('fake_order_min', 0.5), s.get('fake_order_max', 10.0)) / 1000) * qty
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

        except Exception as e:
            logging.error(f"Fake Proof Error: {e}")
            pass

threading.Thread(target=auto_fake_proof_cron, daemon=True).start()

# ==========================================
# 3. ADMIN WEB PANEL ROUTES (GOD MODE)
# ==========================================
def get_dashboard_stats():
    cached = redis_client.get("settings_cache")
    if cached:
        s = json.loads(cached)
    else:
        s = config_col.find_one({"_id": "settings"}) or {}
        redis_client.setex("settings_cache", 30, json.dumps(s))
        
    u_count = users_col.count_documents({})
    bal = sum(u.get('balance', 0) for u in users_col.find())
    sales = sum(u.get('spent', 0) for u in users_col.find())
    profit = sales * (s.get('profit_margin', 20.0) / 100)
    return {"u_count": u_count, "bal": f"${bal:.2f}", "sales": f"${sales:.2f}", "profit": f"${profit:.2f}", "s": s}

@app.route('/')
def index():
    if 'admin' not in session: return redirect(url_for('login'))
    
    try: page = int(request.args.get('page', 1))
    except: page = 1
    per_page = 50
    total_users = users_col.count_documents({})
    total_pages = math.ceil(total_users / per_page)
    users = list(users_col.find().sort("spent", -1).skip((page - 1) * per_page).limit(per_page))
    
    stats = get_dashboard_stats()
    orders = list(orders_col.find().sort("_id", -1).limit(100))
    tickets = list(tickets_col.find().sort("_id", -1))
    vouchers = list(vouchers_col.find().sort("_id", -1))
    
    system_logs = list(logs_col.find().sort("date", -1).limit(50))
    
    services = utils.get_cached_services()
    unique_categories = sorted(list(set(str(s.get('category', 'Uncategorized')) for s in services))) if services else []
    
    saved_orders_doc = config_col.find_one({"_id": "service_orders"}) or {}
    saved_service_orders = saved_orders_doc.get("orders", {})
    
    services_json = json.dumps(services)
    saved_service_orders_json = json.dumps(saved_service_orders)

    return render_template('admin.html', **stats, users=users, orders=orders, tickets=tickets, vouchers=vouchers, 
                           unique_categories=unique_categories, services_json=services_json, saved_service_orders=saved_service_orders_json,
                           page=page, total_pages=total_pages, system_logs=system_logs)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error="Wrong Password!")
    return render_template('login.html')

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
    utils.update_settings_cache("best_choice_sids", sids)
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
        
        # 🔥 Crypto APIs Data & Toggles
        "cryptomus_merchant": request.form.get('cryptomus_merchant', '').strip(),
        "cryptomus_api": request.form.get('cryptomus_api', '').strip(),
        "cryptomus_active": 'cryptomus_active' in request.form,
        
        "coinpayments_pub": request.form.get('coinpayments_pub', '').strip(),
        "coinpayments_priv": request.form.get('coinpayments_priv', '').strip(),
        "coinpayments_active": 'coinpayments_active' in request.form,
        
        "nowpayments_api": request.form.get('nowpayments_api', '').strip(),
        "nowpayments_ipn": request.form.get('nowpayments_ipn', '').strip(),
        "nowpayments_active": 'nowpayments_active' in request.form,
        
        "payeer_merchant": request.form.get('payeer_merchant', '').strip(),
        "payeer_secret": request.form.get('payeer_secret', '').strip(),
        "payeer_active": 'payeer_active' in request.form,
        
        "stars_rate": int(request.form.get('stars_rate', 50)),
        "stars_active": 'stars_active' in request.form,
        
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

    profit_tiers = []
    tier_mins = request.form.getlist('tier_min[]')
    tier_maxs = request.form.getlist('tier_max[]')
    tier_margins = request.form.getlist('tier_margin[]')
    
    for i in range(len(tier_mins)):
        if tier_mins[i].strip() and tier_maxs[i].strip() and tier_margins[i].strip():
            profit_tiers.append({
                "min": float(tier_mins[i]),
                "max": float(tier_maxs[i]),
                "margin": float(tier_margins[i])
            })
    s["profit_tiers"] = profit_tiers

    config_col.update_one({"_id": "settings"}, {"$set": s}, upsert=True)
    redis_client.setex("settings_cache", 30, json.dumps(s))
    return redirect(url_for('index'))

@app.route('/edit_user', methods=['POST'])
def edit_user():
    if 'admin' not in session: return redirect(url_for('login'))
    uid = int(request.form.get('user_id'))
    bal_action = request.form.get('bal_action')
    bal_val = float(request.form.get('balance_val', 0))
    spent = float(request.form.get('spent', 0))
    ref_earn = float(request.form.get('ref_earnings', 0))
    points = int(request.form.get('points', 0))
    discount = float(request.form.get('custom_discount', 0))
    tier = request.form.get('tier_override')
    if tier == 'none': tier = None

    update_query = {"spent": spent, "ref_earnings": ref_earn, "points": points, "custom_discount": discount, "tier_override": tier}
    
    if bal_action == "set":
        update_query["balance"] = bal_val
        users_col.update_one({"_id": uid}, {"$set": update_query})
    elif bal_action == "add":
        users_col.update_one({"_id": uid}, {"$set": update_query, "$inc": {"balance": bal_val}})
    elif bal_action == "sub":
        users_col.update_one({"_id": uid}, {"$set": update_query, "$inc": {"balance": -bal_val}})
        
    utils.clear_cached_user(uid)
    return redirect(url_for('index'))

@app.route('/add_fake_user', methods=['POST'])
def add_fake_user():
    if 'admin' not in session: return redirect(url_for('login'))
    fake_id = random.randint(1000000, 9999999)
    name = request.form.get('fake_name')
    spent = float(request.form.get('fake_spent', 0))
    ref = float(request.form.get('fake_ref', 0))
    
    users_col.insert_one({"_id": fake_id, "name": name, "balance": 0.0, "spent": spent, "currency": "USD", "ref_earnings": ref, "points": 0, "is_fake": True, "joined": datetime.now()})
    return redirect(url_for('index'))

@app.route('/remove_fake_users')
def remove_fake_users():
    if 'admin' not in session: return redirect(url_for('login'))
    users_col.delete_many({"is_fake": True})
    return redirect(url_for('index'))

@app.route('/smart_cleanup')
def smart_cleanup():
    if 'admin' not in session: return redirect(url_for('login'))
    
    t_del = tickets_col.delete_many({"status": "closed"}).deleted_count
    o_del = orders_col.delete_many({"status": {"$in": ["canceled", "fail", "refunded"]}}).deleted_count
    
    v_del = 0
    for v in vouchers_col.find():
        if len(v.get('used_by', [])) >= v.get('limit', 1):
            vouchers_col.delete_one({"_id": v["_id"]})
            v_del += 1
            
    try:
        report = f"🧹 **SMART CLEANUP COMPLETE**\n━━━━━━━━━━━━━━━━━━━━\n🗑️ Closed Tickets Deleted: `{t_del}`\n🗑️ Failed/Canceled Orders: `{o_del}`\n🗑️ Used Vouchers Removed: `{v_del}`\n\n✅ Database is now fresh, fast & optimized!"
        bot.send_message(ADMIN_ID, report, parse_mode="Markdown")
    except: pass
    
    return redirect(url_for('index'))

@app.route('/delete_user/<int:uid>')
def delete_user(uid):
    if 'admin' not in session: return redirect(url_for('login'))
    users_col.delete_one({"_id": uid})
    redis_client.delete(f"session_{uid}")
    utils.clear_cached_user(uid)
    return redirect(url_for('index'))

@app.route('/toggle_shadow_ban/<int:uid>')
def toggle_shadow_ban(uid):
    if 'admin' not in session: return redirect(url_for('login'))
    u = users_col.find_one({"_id": uid})
    if u: 
        users_col.update_one({"_id": uid}, {"$set": {"shadow_banned": not u.get('shadow_banned', False)}})
        utils.clear_cached_user(uid)
    return redirect(url_for('index'))

@app.route('/ban_user/<int:uid>')
def ban_user(uid):
    if 'admin' not in session: return redirect(url_for('login'))
    users_col.update_one({"_id": uid}, {"$set": {"banned": True}})
    utils.clear_cached_user(uid)
    return redirect(url_for('index'))

@app.route('/unban_user/<int:uid>')
def unban_user(uid):
    if 'admin' not in session: return redirect(url_for('login'))
    users_col.update_one({"_id": uid}, {"$set": {"banned": False}})
    utils.clear_cached_user(uid)
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
            utils.clear_cached_user(u["_id"]) 
            try: bot.send_message(u["_id"], f"🎉 **CONGRATULATIONS!**\nYou ranked #{i+1} Top Spender! Reward `${rewards[i]}` added.", parse_mode="Markdown")
            except: pass
        
    top_refs = list(users_col.find({"ref_earnings": {"$gt": 0}}).sort("ref_earnings", -1).limit(3))
    for i, u in enumerate(top_refs):
        if not u.get('is_fake'):
            users_col.update_one({"_id": u["_id"]}, {"$inc": {"balance": rewards[i]}})
            utils.clear_cached_user(u["_id"])
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
    utils.clear_cached_user(uid)
    u = users_col.find_one({"_id": uid})
    if u and u.get("ref_by"):
        s = config_col.find_one({"_id": "settings"}) or {}
        comm = float(amt) * (s.get("dep_commission", 5.0) / 100)
        if comm > 0:
            users_col.update_one({"_id": u["ref_by"]}, {"$inc": {"balance": comm, "ref_earnings": comm}})
            utils.clear_cached_user(u["ref_by"])
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
        utils.clear_cached_user(o['uid']) 
        try: bot.send_message(o['uid'], f"💰 **ORDER REFUNDED!**\nOrder `{oid}` was refunded. `${o['cost']}` returned to your wallet.", parse_mode="Markdown")
        except: pass
    return redirect(url_for('index'))

@app.route('/clear_logs')
def clear_logs():
    if 'admin' not in session: return redirect(url_for('login'))
    logs_col.delete_many({})
    return redirect(url_for('index'))

# ==========================================
# 8. LOCAL AUTO PAYMENT WEBHOOK API (For MacroDroid)
# ==========================================
@app.route('/api/add_transaction', methods=['POST', 'GET'])
def add_transaction():
    secret = request.args.get('secret') or (request.json.get('secret') if request.is_json else None)
    
    if secret != "NEXUS_AUTO_PASS_123":
        return jsonify({"status": "error", "msg": "Wrong Secret Key!"}), 403

    sms_text = request.args.get('sms') or (request.json.get('sms') if request.is_json else "")
    
    if not sms_text:
        return jsonify({"status": "error", "msg": "No SMS text provided"}), 400

    try:
        trx_match = re.search(r'(?i)(?:TrxID|TxnID)\s*[:]?\s*([A-Z0-9]{8,12})', sms_text)
        amt_match = re.search(r'(?i)(?:Tk\s+|Amount:\s*Tk\s+)([\d,]+\.\d{2})', sms_text)
        
        if trx_match and amt_match:
            trx = trx_match.group(1).upper()
            amt = float(amt_match.group(1).replace(',', ''))
            
            config_col.update_one(
                {"_id": "transactions"}, 
                {"$push": {"valid_list": {"trx": trx, "amt": amt, "status": "unused"}}}, 
                upsert=True
            )
            return jsonify({"status": "success", "msg": f"Auto Added: Trx {trx}, Amt {amt}"})
        else:
            return jsonify({"status": "ignored", "msg": "TrxID or Amount not found in SMS"}), 200
            
    except Exception as e:
        logging.error(f"Local Auto Pay Error: {e}")
        logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Local Auto Pay", "date": datetime.now()})
        return jsonify({"status": "error", "msg": str(e)})


# ==========================================
# 🔥 9. NEW: SMM PANEL WEBHOOK (Instant Status Sync)
# ==========================================
@app.route('/smm_webhook', methods=['POST', 'GET'])
def smm_webhook():
    try:
        data = request.json if request.is_json else request.form
        if not data: return "No Data", 400
        
        order_id = data.get('order') or data.get('id')
        status = data.get('status')
        
        if order_id and status:
            new_status = str(status).lower()
            o = orders_col.find_one({"oid": int(order_id)})
            if o and o.get('status') != new_status and not o.get('is_shadow'):
                orders_col.update_one({"_id": o["_id"]}, {"$set": {"status": new_status}})
                
                st_emoji = "⏳"
                if new_status == "completed": st_emoji = "✅"
                elif new_status in ["canceled", "refunded", "fail"]: st_emoji = "❌"
                elif new_status in ["in progress", "processing"]: st_emoji = "🔄"
                elif new_status == "partial": st_emoji = "⚠️"
                
                try:
                    msg = f"🔔 **ORDER UPDATE!**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Order ID: `{o['oid']}`\n🔗 Link: {str(o.get('link', 'N/A'))[:25]}...\n📦 Status: {st_emoji} **{new_status.upper()}**"
                    bot.send_message(o['uid'], msg, parse_mode="Markdown")
                except: pass
                
                if new_status in ['canceled', 'refunded', 'fail']:
                    u = utils.get_cached_user(o['uid'])
                    curr = u.get("currency", "BDT") if u else "BDT"
                    cost_str = utils.fmt_curr(o['cost'], curr)
                    users_col.update_one({"_id": o['uid']}, {"$inc": {"balance": o['cost'], "spent": -o['cost']}})
                    utils.clear_cached_user(o['uid'])
                    try: bot.send_message(o['uid'], f"💰 **ORDER REFUNDED!**\nOrder `{o['oid']}` failed or canceled by server. `{cost_str}` has been added back to your balance.", parse_mode="Markdown")
                    except: pass
                    
        return "OK", 200
    except Exception as e:
        logging.error(f"SMM Webhook Error: {e}")
        logs_col.insert_one({"error": str(traceback.format_exc()), "source": "SMM Webhook", "date": datetime.now()})
        return "Error", 500


# ==========================================
# 10. GLOBAL CRYPTO PAYMENT WEBHOOKS
# ==========================================
@app.route('/cryptomus_webhook', methods=['POST'])
def cryptomus_webhook():
    """Cryptomus Auto-Payment IPN Listener"""
    try:
        data = request.json
        if not data: return "No data", 400
        
        s = config_col.find_one({"_id": "settings"}) or {}
        api_key = s.get('cryptomus_api', '')
        if not api_key: return "Cryptomus not configured", 400
        
        sign = data.get('sign')
        dict_data = data.copy()
        dict_data.pop('sign', None)
        
        # Cryptomus Hash Validation
        encoded_data = base64.b64encode(json.dumps(dict_data, separators=(',', ':')).encode('utf-8')).decode('utf-8')
        expected_sign = hashlib.md5((encoded_data + api_key).encode('utf-8')).hexdigest()
        
        if sign != expected_sign: return "Invalid signature", 400
        
        if data.get('status') in ['paid', 'paid_over']:
            uid = int(str(data.get('order_id', '0')).split('_')[0]) 
            amt = float(data.get('amount'))
            trx = data.get('uuid')
            
            if config_col.find_one({"_id": "transactions", "valid_list.trx": trx}):
                return "Already processed", 200
                
            config_col.update_one({"_id": "transactions"}, {"$push": {"valid_list": {"trx": trx, "amt": amt, "status": "used", "user": uid}}}, upsert=True)
            users_col.update_one({"_id": uid}, {"$inc": {"balance": amt}})
            utils.clear_cached_user(uid)
            
            try: bot.send_message(uid, f"✅ **CRYPTOMUS DEPOSIT SUCCESS!**\nAmount: `${amt}` added to your wallet.", parse_mode="Markdown")
            except: pass
            
        return "OK", 200
    except Exception as e:
        logging.error(f"Cryptomus Webhook Error: {e}")
        logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Cryptomus", "date": datetime.now()})
        return str(e), 500

@app.route('/coinpayments_ipn', methods=['POST'])
def coinpayments_ipn():
    """CoinPayments Auto-Payment IPN Listener"""
    try:
        s = config_col.find_one({"_id": "settings"}) or {}
        ipn_secret = s.get('coinpayments_priv', '')
        if not ipn_secret: return "CoinPayments not configured", 400
        
        hmac_header = request.headers.get('HMAC')
        if not hmac_header: return "No HMAC signature", 400
        
        request_data = request.get_data()
        calculated_hmac = hmac.new(ipn_secret.encode('utf-8'), request_data, hashlib.sha512).hexdigest()
        
        if hmac_header != calculated_hmac: return "Invalid HMAC", 400
        
        status = int(request.form.get('status', -1))
        if status >= 100 or status == 2: 
            uid = int(request.form.get('custom', 0)) 
            amt = float(request.form.get('amount1', 0)) 
            trx = request.form.get('txn_id')
            
            if config_col.find_one({"_id": "transactions", "valid_list.trx": trx}):
                return "Already processed", 200
                
            config_col.update_one({"_id": "transactions"}, {"$push": {"valid_list": {"trx": trx, "amt": amt, "status": "used", "user": uid}}}, upsert=True)
            users_col.update_one({"_id": uid}, {"$inc": {"balance": amt}})
            utils.clear_cached_user(uid)
            
            try: bot.send_message(uid, f"✅ **COINPAYMENTS DEPOSIT SUCCESS!**\nAmount: `${amt}` added to your wallet.", parse_mode="Markdown")
            except: pass
            
        return "OK", 200
    except Exception as e:
        logging.error(f"CoinPayments Webhook Error: {e}")
        logs_col.insert_one({"error": str(traceback.format_exc()), "source": "CoinPayments", "date": datetime.now()})
        return str(e), 500

@app.route('/nowpayments_ipn', methods=['POST'])
def nowpayments_ipn():
    """NowPayments Auto-Payment IPN Listener"""
    try:
        s = config_col.find_one({"_id": "settings"}) or {}
        ipn_secret = s.get('nowpayments_ipn', '')
        if not ipn_secret: return "NowPayments IPN not configured", 400
        
        sig = request.headers.get('x-nowpayments-sig')
        if not sig: return "No signature", 400
        
        request_data = request.get_data()
        hmac_obj = hmac.new(ipn_secret.encode('utf-8'), request_data, hashlib.sha512)
        if hmac_obj.hexdigest() != sig: return "Invalid signature", 400
        
        data = request.json
        if data.get('payment_status') == 'finished':
            order_id = data.get('order_id')
            uid = int(str(order_id).split('_')[0])
            amt = float(data.get('price_amount'))
            trx = str(data.get('payment_id'))
            
            if config_col.find_one({"_id": "transactions", "valid_list.trx": trx}):
                return "Already processed", 200
                
            config_col.update_one({"_id": "transactions"}, {"$push": {"valid_list": {"trx": trx, "amt": amt, "status": "used", "user": uid}}}, upsert=True)
            users_col.update_one({"_id": uid}, {"$inc": {"balance": amt}})
            utils.clear_cached_user(uid)
            
            try: bot.send_message(uid, f"✅ **NOWPAYMENTS DEPOSIT SUCCESS!**\nAmount: `${amt}` added to your wallet.", parse_mode="Markdown")
            except: pass
            
        return "OK", 200
    except Exception as e:
        logging.error(f"NowPayments Webhook Error: {e}")
        logs_col.insert_one({"error": str(traceback.format_exc()), "source": "NowPayments", "date": datetime.now()})
        return str(e), 500

@app.route('/payeer_ipn', methods=['POST'])
def payeer_ipn():
    """Payeer Auto-Payment IPN Listener"""
    try:
        s = config_col.find_one({"_id": "settings"}) or {}
        secret = s.get('payeer_secret', '')
        if not secret: return "Payeer not configured", 400
        
        if request.form.get('m_operation_id') and request.form.get('m_sign'):
            arHash = [
                request.form.get('m_operation_id'),
                request.form.get('m_operation_ps'),
                request.form.get('m_operation_date'),
                request.form.get('m_operation_pay_date'),
                request.form.get('m_shop'),
                request.form.get('m_orderid'),
                request.form.get('m_amount'),
                request.form.get('m_curr'),
                request.form.get('m_desc'),
                request.form.get('m_status'),
                secret
            ]
            sign_hash = hashlib.sha256(':'.join(arHash).encode('utf-8')).hexdigest().upper()
            
            if request.form.get('m_sign') == sign_hash and request.form.get('m_status') == 'success':
                order_id = request.form.get('m_orderid')
                # Extract uid from order_id (removing the last 3 random digits created in utils)
                uid = int(str(order_id)[:-3]) 
                amt = float(request.form.get('m_amount'))
                trx = request.form.get('m_operation_id')
                
                if config_col.find_one({"_id": "transactions", "valid_list.trx": trx}):
                    return "Already processed", 200
                    
                config_col.update_one({"_id": "transactions"}, {"$push": {"valid_list": {"trx": trx, "amt": amt, "status": "used", "user": uid}}}, upsert=True)
                users_col.update_one({"_id": uid}, {"$inc": {"balance": amt}})
                utils.clear_cached_user(uid)
                
                try: bot.send_message(uid, f"✅ **PAYEER DEPOSIT SUCCESS!**\nAmount: `${amt}` added to your wallet.", parse_mode="Markdown")
                except: pass
                return "success", 200
        return "error", 400
    except Exception as e:
        logging.error(f"Payeer Webhook Error: {e}")
        logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Payeer", "date": datetime.now()})
        return str(e), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
