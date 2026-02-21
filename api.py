import requests
from config import API_KEY, API_URL

# ==========================================
# ⚡ UNIVERSAL REQUEST HANDLER (ANTI-FREEZE)
# ==========================================
def _make_request(action, timeout=12, **kwargs):
    """
    এই ফাংশনটি সব এপিআই রিকোয়েস্ট হ্যান্ডল করবে এবং সার্ভার ফ্রিজ হওয়া রোধ করবে।
    """
    payload = {'key': API_KEY, 'action': action}
    payload.update(kwargs)
    
    try:
        response = requests.post(API_URL, data=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {"error": "API Connection Timeout. Main panel is too slow."}
    except Exception as e:
        return {"error": str(e)}

# ==========================================
# 📦 SMM PANEL API FUNCTIONS
# ==========================================
def get_services():
    """প্যানেল থেকে সব সার্ভিসের লিস্ট আনা"""
    res = _make_request('services', timeout=15)
    return res if isinstance(res, list) else []

def place_order(sid, link, qty):
    """আসল প্যানেলে অর্ডার প্লেস করা"""
    return _make_request('add', timeout=15, service=sid, link=link, quantity=qty)

def get_order_status(order_id):
    """অর্ডারের বর্তমান স্ট্যাটাস চেক করা (Auto-Refund এর জন্য)"""
    return _make_request('status', timeout=10, order=order_id)

def get_balance():
    """আপনার প্যানেলের মেইন ব্যালেন্স চেক করা (অ্যাডমিন প্যানেলের জন্য)"""
    res = _make_request('balance', timeout=10)
    if isinstance(res, dict):
        return f"{res.get('balance', '0.00')} {res.get('currency', 'USD')}"
    return "N/A"
