import requests
from config import API_URL, API_KEY

def _make_request(action, timeout=12, **kwargs):
    """সার্ভার যাতে হ্যাং না হয় সেজন্য ইউনিভার্সাল টাইমআউট ফাংশন"""
    payload = {'key': API_KEY, 'action': action}
    payload.update(kwargs)
    try:
        response = requests.post(API_URL, data=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {"error": "API Connection Timeout. Main Server is too slow. Please try again later."}
    except Exception as e:
        return {"error": str(e)}

# ==========================================
# API FUNCTIONS
# ==========================================

def get_services():
    res = _make_request('services', timeout=15)
    return res if isinstance(res, list) else []

def place_order(sid, link, qty):
    return _make_request('add', timeout=15, service=sid, link=link, quantity=qty)

def get_order_status(order_id):
    return _make_request('status', timeout=10, order=order_id)

def get_balance():
    res = _make_request('balance', timeout=10)
    if isinstance(res, dict):
        return f"{res.get('balance', '0.00')} {res.get('currency', 'USD')}"
    return "N/A"
