import requests
import time
from config import API_KEY, API_URL

# ==========================================
# ⚡ SMART API ENGINE (Auto-Retry + Cloudflare Bypass)
# ==========================================
def _make_request(action, timeout=15, retries=3, **kwargs):
    """
    এই ফাংশনটি সব API রিকোয়েস্ট হ্যান্ডল করবে। 
    কোনো কারণে প্যানেল স্লো থাকলে বা টাইমআউট হলে এটি নিজে থেকেই ৩ বার ট্রাই করবে।
    """
    payload = {'key': API_KEY, 'action': action}
    payload.update(kwargs)
    
    # Cloudflare Bypass Headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for attempt in range(retries):
        try:
            response = requests.post(API_URL, data=payload, headers=headers, timeout=timeout)
            try:
                return response.json()
            except ValueError:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                response.raise_for_status()
                return {"error": f"Invalid response from panel. Status: {response.status_code}"}
                
        except (requests.exceptions.Timeout, requests.exceptions.RequestException):
            if attempt < retries - 1:
                time.sleep(2) # ২ সেকেন্ড ওয়েট করে আবার ট্রাই করবে
                continue
            return {"error": "API Connection Timeout. Main panel is too slow after 3 retries."}
        except Exception as e:
            return {"error": str(e)}

# ==========================================
# 📦 SMM PANEL API FUNCTIONS
# ==========================================
def get_services():
    """প্যানেল থেকে সব সার্ভিসের লিস্ট আনা (Price Auto-Sync)"""
    res = _make_request('services', timeout=20)
    return res if isinstance(res, list) else []

def place_order(sid, link, qty):
    """আসল প্যানেলে অর্ডার প্লেস করা"""
    return _make_request('add', timeout=20, service=sid, link=link, quantity=qty)

def check_order_status(order_id):
    """অর্ডারের স্ট্যাটাস চেক করা"""
    return _make_request('status', timeout=15, order=order_id)

def send_refill(order_id):
    """Refill request পাঠানো (Auto Refill Supported)"""
    return _make_request('refill', timeout=15, order=order_id)

def get_balance():
    """মেইন প্যানেলের ব্যালেন্স চেক করা"""
    res = _make_request('balance', timeout=15)
    if isinstance(res, dict):
        return f"{res.get('balance', '0.00')} {res.get('currency', 'USD')}"
    return "N/A"

# ==========================================
# 🌍 REAL-TIME EXCHANGE RATE API (NEW FEATURE)
# ==========================================
def get_live_exchange_rates():
    """
    ফ্রি ওপেন API ব্যবহার করে লাইভ ফরেক্স মার্কেট থেকে BDT এবং INR এর রেট আনবে।
    """
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        data = res.json()
        if data and "rates" in data:
            return {
                "BDT": data["rates"].get("BDT", 120),
                "INR": data["rates"].get("INR", 83)
            }
    except Exception:
        pass
    return None # ফেইল করলে ডিফল্ট রেট ব্যবহার হবে
