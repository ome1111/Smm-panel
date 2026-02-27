import time
import json
import random
import logging
import traceback
import threading
from datetime import datetime

from loader import bot, users_col, orders_col, config_col, logs_col, redis_client
from config import ADMIN_ID
import api
from utils import get_settings, get_cached_user, clear_cached_user, fmt_curr, escape_md, get_cached_services

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] [BACKGROUND-WORKER] %(message)s')

def auto_sync_services_cron():
    while True:
        try:
            if not redis_client.set("lock_sync_services_running", "locked", nx=True, ex=43200):
                time.sleep(60)
                continue
        except:
            time.sleep(60)
            continue
            
        try:
            logging.info("🔄 Syncing services from Main API...")
            main_res = api.get_services()
            
            if main_res and isinstance(main_res, list) and len(main_res) > 0: 
                combined_res = main_res.copy()
                s = get_settings()
                ext_apis = s.get("external_apis", [])
                
                for i, ext in enumerate(ext_apis):
                    ext_url = ext.get('url')
                    ext_key = ext.get('key')
                    target_sids = [str(sid).strip() for sid in ext.get('services', []) if str(sid).strip()]
                    
                    if ext_url and ext_key and target_sids:
                        logging.info(f"🔄 Syncing external API {i}...")
                        try:
                            ext_data = api.get_external_services(ext_url, ext_key)
                            if ext_data and isinstance(ext_data, list):
                                for srv in ext_data:
                                    original_id = str(srv.get('service'))
                                    if original_id in target_sids:
                                        new_srv = srv.copy()
                                        new_id = f"ext_{i}_{original_id}"
                                        new_srv['service'] = new_id
                                        new_srv['name'] = f"{new_srv.get('name', 'Unknown')} 🌟"
                                        combined_res.append(new_srv)
                        except Exception as inner_e:
                            logging.error(f"External API {i} Sync Error: {inner_e}")

                try: redis_client.setex("services_cache", 43200, json.dumps(combined_res))
                except: pass
                config_col.update_one({"_id": "api_cache"}, {"$set": {"data": combined_res, "time": time.time()}}, upsert=True)
                logging.info(f"✅ Successfully synced {len(combined_res)} services (Hybrid Mode).")
                
                time.sleep(43200)
                continue
            else:
                logging.warning("⚠️ Main API returned empty data. Retrying in 5 minutes...")
                try: redis_client.delete("lock_sync_services_running")
                except: pass
        except Exception as e: 
            logging.error(f"❌ Service Sync Failed: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Service Sync", "date": datetime.now()})
            except: pass
            try: redis_client.delete("lock_sync_services_running")
            except: pass
            
        time.sleep(300)

def exchange_rate_sync_cron():
    while True:
        try:
            if not redis_client.set("lock_exchange_running", "locked", nx=True, ex=43200):
                time.sleep(60)
                continue
        except:
            time.sleep(60)
            continue
            
        try:
            rates = api.get_live_exchange_rates()
            if rates:
                try: redis_client.set("currency_rates", json.dumps(rates))
                except: pass
                logging.info(f"✅ Live Exchange Rates Synced: {rates}")
                
                time.sleep(43200)
                continue
            else:
                try: redis_client.delete("lock_exchange_running")
                except: pass
        except Exception as e: 
            logging.error(f"❌ Exchange Rate Sync Failed: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Exchange Rate Sync", "date": datetime.now()})
            except: pass
            try: redis_client.delete("lock_exchange_running")
            except: pass
            
        time.sleep(300)

def drip_campaign_cron():
    while True:
        try:
            if not redis_client.set("lock_drip", "locked", nx=True, ex=43000):
                time.sleep(60)
                continue
        except:
            time.sleep(60)
            continue
            
        now = datetime.now()
        try:
            users_cursor = users_col.find({"is_fake": {"$ne": True}}, {"joined": 1, "drip_3": 1, "drip_7": 1, "drip_15": 1})
            
            for u in users_cursor:
                try: 
                    time.sleep(0.05) 
                    joined = u.get("joined")
                    if not joined: continue
                    days = (now - joined).days
                    uid = u["_id"]
                    
                    if days >= 3 and not u.get("drip_3"):
                        try: bot.send_message(uid, "🎁 **Hey! It's been 3 Days!**\nHope you're enjoying our lightning-fast services. Deposit today to boost your socials!", parse_mode="Markdown")
                        except: pass
                        users_col.update_one({"_id": uid}, {"$set": {"drip_3": True}})
                        clear_cached_user(uid)
                    elif days >= 7 and not u.get("drip_7"):
                        try: bot.send_message(uid, "🔥 **1 Week Anniversary!**\nYou've been with us for 7 days. Check out our Flash Sales and keep growing!", parse_mode="Markdown")
                        except: pass
                        users_col.update_one({"_id": uid}, {"$set": {"drip_7": True}})
                        clear_cached_user(uid)
                    elif days >= 15 and not u.get("drip_15"):
                        try: bot.send_message(uid, "💎 **VIP Reminder!**\nAs a loyal user, we invite you to check our Best Choice services today!", parse_mode="Markdown")
                        except: pass
                        users_col.update_one({"_id": uid}, {"$set": {"drip_15": True}})
                        clear_cached_user(uid)
                except Exception as e: 
                    logging.error(f"Drip Campaign User Error: {e}")
        except Exception as e: 
            logging.error(f"Drip Campaign Outer Error: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Drip Campaign", "date": datetime.now()})
            except: pass
        time.sleep(43200)

def auto_sync_orders_cron():
    while True:
        try:
            if not redis_client.set("lock_orders_sync", "locked", nx=True, ex=590):
                time.sleep(60)
                continue
        except:
            time.sleep(60)
            continue
            
        try:
            active_orders = orders_col.find({"status": {"$nin": ["completed", "canceled", "refunded", "fail", "partial"]}})
            for o in active_orders:
                try:
                    time.sleep(0.1) 
                    if o.get("is_shadow"): continue
                    
                    try: res = api.check_order_status(o['oid'])
                    except: continue
                    
                    if res and 'status' in res:
                        new_status = res['status'].lower()
                        old_status = str(o.get('status', '')).lower()
                        remains = res.get('remains', 0)
                        
                        update_data = {"status": new_status, "remains": remains}
                        orders_col.update_one({"_id": o["_id"]}, {"$set": update_data})
                        
                        if new_status != old_status and new_status != 'error':
                            st_emoji = "⏳"
                            if new_status == "completed": st_emoji = "✅"
                            elif new_status in ["canceled", "refunded", "fail"]: st_emoji = "❌"
                            elif new_status in ["in progress", "processing"]: st_emoji = "🔄"
                            elif new_status == "partial": st_emoji = "⚠️"

                            try:
                                safe_link = escape_md(str(o.get('link', 'N/A'))[:25])
                                msg = f"🔔 **ORDER UPDATE!**\n━━━━━━━━━━━━━━━━━━━━\n🆔 Order ID: `{o['oid']}`\n🔗 Link: {safe_link}...\n📦 Status: {st_emoji} **{new_status.upper()}**"
                                bot.send_message(o['uid'], msg, parse_mode="Markdown")
                            except: pass
                            
                            if new_status in ['canceled', 'refunded', 'fail']:
                                u = get_cached_user(o['uid'])
                                curr = u.get("currency", "BDT") if u else "BDT"
                                cost_str = fmt_curr(o['cost'], curr)
                                users_col.update_one({"_id": o['uid']}, {"$inc": {"balance": o['cost'], "spent": -o['cost']}})
                                clear_cached_user(o['uid'])
                                try: bot.send_message(o['uid'], f"💰 **ORDER REFUNDED!**\nOrder `{o['oid']}` failed or canceled by server. `{cost_str}` has been added back to your balance.", parse_mode="Markdown")
                                except: pass
                except Exception as e:
                    logging.error(f"Orders Sync Inner Error: {e}")
        except Exception as e: 
            logging.error(f"Orders Sync Outer Error: {e}")
            try: logs_col.insert_one({"error": str(traceback.format_exc()), "source": "Order Sync", "date": datetime.now()})
            except: pass
            
        time.sleep(600)

def auto_fake_proof_cron():
    while True:
        try:
            time.sleep(45)
            s = get_settings()
            if not s or not s.get('fake_proof_status', False):
                continue

            if s.get('night_mode', False):
                hour = datetime.now().hour
                if 2 <= hour <= 8:
                    continue

            proof_channel = s.get('proof_channel', '')
            if not proof_channel:
                continue

            now = time.time()
            lock_res = config_col.update_one(
                {"_id": "sys_locks", "$or": [{"fake_proof": {"$lt": now}}, {"fake_proof": {"$exists": False}}]},
                {"$set": {"fake_proof": now + 40}},
                upsert=True
            )
            
            if not lock_res.upserted_id and lock_res.modified_count == 0:
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
                
                cached_services = get_cached_services()
                if cached_services:
                    srv = random.choice(cached_services)
                    base_rate = float(srv.get('rate', 0.5))
                    cost_usd = (base_rate / 1000) * qty * 1.2
                else:
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
                
                fake_uid = str(random.randint(1000000, 9999999))
                masked_id = f"***{fake_uid[-4:]}"
                
                sid = srv.get('service', str(random.randint(10, 500)))
                
                msg = f"```text\n╔════ 🟢 𝗡𝗘𝗪 𝗢𝗥𝗗𝗘𝗥 ════╗\n║ 👤 𝗜𝗗: {masked_id}\n║ 🚀 𝗦𝗲𝗿𝘃𝗶𝗰𝗲 𝗜𝗗: {sid}\n║ 💵 𝗖𝗼𝘀𝘁: {display_cost}\n╚════════════════════╝\n```"
                bot.send_message(proof_channel, msg, parse_mode="Markdown")

        except Exception as e:
            logging.error(f"Fake Proof Error: {e}")
            pass

if __name__ == "__main__":
    logging.info("🚀 Background Worker Started Successfully!")
    
    threads = [
        threading.Thread(target=auto_sync_services_cron, daemon=True),
        threading.Thread(target=exchange_rate_sync_cron, daemon=True),
        threading.Thread(target=drip_campaign_cron, daemon=True),
        threading.Thread(target=auto_sync_orders_cron, daemon=True),
        threading.Thread(target=auto_fake_proof_cron, daemon=True)
    ]
    
    for t in threads:
        t.start()
        
    # Keep the main thread alive
    while True:
        time.sleep(3600)
