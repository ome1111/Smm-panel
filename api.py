import requests
import logging
from config import API_URL, API_KEY
from loader import config_col, orders_col

# 🔥 Global Session for faster API calls (Reuses TCP connections)
session = requests.Session()

def get_api_settings():
    s = config_col.find_one({"_id": "settings"})
    return s if s else {}

def get_services():
    try:
        payload = {'key': API_KEY, 'action': 'services'}
        r = session.post(API_URL, data=payload, timeout=15)
        return r.json()
    except Exception as e:
        logging.error(f"Main API Sync Error: {e}")
        return []

def get_external_services(url, key):
    try:
        payload = {'key': key, 'action': 'services'}
        r = session.post(url, data=payload, timeout=15)
        return r.json()
    except Exception as e:
        logging.error(f"Ext API Sync Error: {e}")
        return []

def get_live_exchange_rates():
    try:
        r = session.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        data = r.json()
        rates = data.get('rates', {})
        return {"BDT": rates.get("BDT", 120), "INR": rates.get("INR", 83), "USD": 1}
    except:
        return {"BDT": 120, "INR": 83, "USD": 1}

def place_order(service, link=None, quantity=None, username=None, min=None, max=None, posts=None, delay=None, runs=None, interval=None):
    str_sid = str(service)
    
    # 🚀 SMART ROUTING: EXTERNAL PANELS (FAST)
    if str_sid.startswith("ext_"):
        try:
            parts = str_sid.split("_")
            ext_idx = int(parts[1])
            real_sid = parts[2]
            
            s = get_api_settings()
            ext_apis = s.get("external_apis", [])
            
            if ext_idx < len(ext_apis):
                ext_panel = ext_apis[ext_idx]
                url = ext_panel.get("url")
                key = ext_panel.get("key")
                
                payload = {'key': key, 'action': 'add', 'service': real_sid}
                if link: payload['link'] = link
                if quantity: payload['quantity'] = quantity
                if username: payload['username'] = username
                if min: payload['min'] = min
                if max: payload['max'] = max
                if posts: payload['posts'] = posts
                if delay: payload['delay'] = delay
                if runs: payload['runs'] = runs
                if interval: payload['interval'] = interval
                
                r = session.post(url, data=payload, timeout=10)
                return r.json()
        except Exception as e:
            logging.error(f"Ext API Order Error: {e}")
            return {"error": "External API Timeout"}

    # 🚀 MAIN PANEL ROUTING
    try:
        payload = {'key': API_KEY, 'action': 'add', 'service': service}
        if link: payload['link'] = link
        if quantity: payload['quantity'] = quantity
        if username: payload['username'] = username
        if min: payload['min'] = min
        if max: payload['max'] = max
        if posts: payload['posts'] = posts
        if delay: payload['delay'] = delay
        if runs: payload['runs'] = runs
        if interval: payload['interval'] = interval
        
        r = session.post(API_URL, data=payload, timeout=10)
        return r.json()
    except Exception as e:
        logging.error(f"Main API Order Error: {e}")
        return {"error": "Main API Timeout"}

def check_order_status(order_id):
    try:
        search_query = int(order_id) if str(order_id).isdigit() else order_id
        order = orders_col.find_one({"oid": search_query})
        sid = str(order.get("sid", "")) if order else ""
        
        if sid.startswith("ext_"):
            parts = sid.split("_")
            ext_idx = int(parts[1])
            s = get_api_settings()
            ext_apis = s.get("external_apis", [])
            
            if ext_idx < len(ext_apis):
                ext_panel = ext_apis[ext_idx]
                url = ext_panel.get("url")
                key = ext_panel.get("key")
                
                payload = {'key': key, 'action': 'status', 'order': order_id}
                r = session.post(url, data=payload, timeout=10)
                return r.json()

        payload = {'key': API_KEY, 'action': 'status', 'order': order_id}
        r = session.post(API_URL, data=payload, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def send_refill(order_id):
    try:
        search_query = int(order_id) if str(order_id).isdigit() else order_id
        order = orders_col.find_one({"oid": search_query})
        sid = str(order.get("sid", "")) if order else ""
        
        if sid.startswith("ext_"):
            parts = sid.split("_")
            ext_idx = int(parts[1])
            s = get_api_settings()
            ext_apis = s.get("external_apis", [])
            
            if ext_idx < len(ext_apis):
                ext_panel = ext_apis[ext_idx]
                url = ext_panel.get("url")
                key = ext_panel.get("key")
                
                payload = {'key': key, 'action': 'refill', 'order': order_id}
                r = session.post(url, data=payload, timeout=10)
                return r.json()

        payload = {'key': API_KEY, 'action': 'refill', 'order': order_id}
        r = session.post(API_URL, data=payload, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}
