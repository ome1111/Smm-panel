import requests
import time
import logging
from config import API_KEY, API_URL

# ==========================================
# ⚡ SMART API ENGINE (Optimized for Render & Cloudflare)
# ==========================================
def _make_request(action, timeout=10, retries=2, **kwargs):
    """
    API Request handler with Cloudflare bypass headers and optimized retry logic
    to prevent Webhook blocking on Render.
    """
    payload = {'key': API_KEY, 'action': action}
    payload.update(kwargs)
    
    # Advanced Cloudflare Bypass Headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest'
    }
    
    for attempt in range(retries):
        try:
            # Gunicorn worker timeout থেকে বাঁচতে timeout লিমিট অপ্টিমাইজ করা হয়েছে
            response = requests.post(API_URL, data=payload, headers=headers, timeout=timeout)
            try:
                return response.json()
            except ValueError:
                if attempt < retries - 1:
                    time.sleep(1) # Webhook যাতে আটকে না থাকে তাই 1s sleep
                    continue
                logging.error(f"API Error: Invalid JSON response. Status: {response.status_code}")
                return {"error": f"Invalid response from panel. Status: {response.status_code}"}
                
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            logging.error(f"API Error: Connection Timeout on action '{action}'.")
            return {"error": "API Connection Timeout. Main panel is too slow."}
            
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            logging.error(f"API Request Exception on action '{action}': {e}")
            return {"error": "API Connection Failed."}
            
        except Exception as e:
            logging.error(f"API General Error on action '{action}': {e}")
            return {"error": str(e)}

# ==========================================
# 📦 SMM PANEL API FUNCTIONS
# ==========================================
def get_services():
    """প্যানেল থেকে সব সার্ভিসের লিস্ট আনা (Price Auto-Sync)"""
    res = _make_request('services', timeout=15)
    return res if isinstance(res, list) else []

def place_order(sid, **kwargs):
    """
    আসল প্যানেলে অর্ডার প্লেস করা।
    এখন এটি Normal, Drip-feed এবং Subscription সব ধরনের প্যারামিটার সাপোর্ট করবে।
    """
    return _make_request('add', timeout=15, service=sid, **kwargs)

def check_order_status(order_id):
    """অর্ডারের স্ট্যাটাস এবং প্রোগ্রেস চেক করা"""
    return _make_request('status', timeout=10, order=order_id)

def send_refill(order_id):
    """Refill request পাঠানো (Auto Refill Supported)"""
    return _make_request('refill', timeout=10, order=order_id)

def get_balance():
    """মেইন প্যানেলের ব্যালেন্স চেক করা"""
    res = _make_request('balance', timeout=10)
    if isinstance(res, dict):
        return f"{res.get('balance', '0.00')} {res.get('currency', 'USD')}"
    return "N/A"

# ==========================================
# 🌍 REAL-TIME EXCHANGE RATE API
# ==========================================
def get_live_exchange_rates():
    """
    ফ্রি ওপেন API ব্যবহার করে লাইভ ফরেক্স মার্কেট থেকে BDT এবং INR এর রেট আনবে।
    """
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=8)
        data = res.json()
        if data and "rates" in data:
            return {
                "BDT": data["rates"].get("BDT", 120),
                "INR": data["rates"].get("INR", 83)
            }
    except Exception as e:
        logging.error(f"Exchange Rate Sync Failed: {e}")
        pass
    return None # ফেইল করলে ডিফল্ট রেট ব্যবহার হবে
