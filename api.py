import requests
import time
from config import API_KEY, API_URL

# ==========================================
# ⚡ SMART API ENGINE (Auto-Retry + Anti-Freeze)
# ==========================================
def _make_request(action, timeout=12, retries=3, **kwargs):
    """
    এই ফাংশনটি সব এপিআই রিকোয়েস্ট হ্যান্ডল করবে। 
    কোনো কারণে প্যানেল স্লো থাকলে বা টাইমআউট হলে এটি নিজে থেকেই ৩ বার ট্রাই করবে।
    """
    payload = {'key': API_KEY, 'action': action}
    payload.update(kwargs)
    
    for attempt in range(retries):
        try:
            response = requests.post(API_URL, data=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(1.5) # Wait before retrying
                continue
            return {"error": "API Connection Timeout. Main panel is too slow after 3 retries."}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5)
                continue
            return {"error": str(e)}

# ==========================================
# 📦 SMM PANEL API FUNCTIONS
# ==========================================
def get_services():
    res = _make_request('services', timeout=15)
    return res if isinstance(res, list) else []

def place_order(sid, link, qty):
    return _make_request('add', timeout=15, service=sid, link=link, quantity=qty)

def check_order_status(order_id):
    return _make_request('status', timeout=10, order=order_id)

def send_refill(order_id):
    return _make_request('refill', timeout=10, order=order_id)

def get_balance():
    res = _make_request('balance', timeout=10)
    if isinstance(res, dict):
        return f"{res.get('balance', '0.00')} {res.get('currency', 'USD')}"
    return "N/A"
