import requests
import time

# ==========================================
# ⚡ SMART MULTI-PROVIDER API ENGINE 
# ==========================================
def _make_request(api_url, api_key, action, timeout=15, retries=3, **kwargs):
    """
    ডাইনামিক API রিকোয়েস্ট হ্যান্ডলার। 
    এখন এটি নির্দিষ্ট প্রোভাইডারের URL এবং Key রিসিভ করে কাজ করবে।
    """
    payload = {'key': api_key, 'action': action}
    payload.update(kwargs)
    
    # Cloudflare Bypass Headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for attempt in range(retries):
        try:
            response = requests.post(api_url, data=payload, headers=headers, timeout=timeout)
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
            return {"error": "API Connection Timeout. Panel is too slow after 3 retries."}
        except Exception as e:
            return {"error": str(e)}

# ==========================================
# 📦 DYNAMIC SMM PANEL API FUNCTIONS
# ==========================================
def get_services(api_url, api_key):
    """নির্দিষ্ট প্যানেল থেকে সব সার্ভিসের লিস্ট আনা"""
    res = _make_request(api_url, api_key, 'services', timeout=20)
    return res if isinstance(res, list) else []

def place_order(api_url, api_key, sid, **kwargs):
    """
    নির্দিষ্ট প্যানেলে আসল অর্ডার প্লেস করা।
    """
    return _make_request(api_url, api_key, 'add', timeout=20, service=sid, **kwargs)

def check_order_status(api_url, api_key, order_id):
    """অর্ডারের স্ট্যাটাস এবং প্রোগ্রেস চেক করা"""
    return _make_request(api_url, api_key, 'status', timeout=15, order=order_id)

def send_refill(api_url, api_key, order_id):
    """Refill request পাঠানো"""
    return _make_request(api_url, api_key, 'refill', timeout=15, order=order_id)

def get_balance(api_url, api_key):
    """যেকোনো নির্দিষ্ট প্যানেলের ব্যালেন্স চেক করা"""
    res = _make_request(api_url, api_key, 'balance', timeout=15)
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

