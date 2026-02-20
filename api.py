import requests
from config import API_URL, API_KEY

def _make_request(action, timeout=10, **kwargs):
    """Universal function to safely call the Main SMM API without freezing the bot"""
    payload = {
        'key': API_KEY,
        'action': action
    }
    payload.update(kwargs)
    
    try:
        # 🔥 timeout অ্যাড করা হয়েছে, মেইন সার্ভার ডাউন থাকলে বট আটকে থাকবে না
        response = requests.post(API_URL, data=payload, timeout=timeout)
        response.raise_for_status() # Check for internal server errors
        return response.json()
    except requests.exceptions.Timeout:
        print(f"API Timeout Error during '{action}' action.")
        return {"error": "API Connection Timeout. Main Server is currently too slow. Try again later."}
    except Exception as e:
        print(f"API Error ({action}): {e}")
        return {"error": str(e)}

# ==========================================
# API FUNCTIONS
# ==========================================

def get_balance():
    """Fetch panel balance"""
    return _make_request('balance')

def get_services():
    """Fetch all services from the main panel"""
    res = _make_request('services', timeout=15) # একটু বেশি সময় দিলাম সার্ভিসের লিস্ট বড় হতে পারে
    if isinstance(res, list):
        return res
    return None

def place_order(service_id, link, quantity):
    """Place a new order to the main panel"""
    # অর্ডারের জন্য ১৫ সেকেন্ড সময় দিলাম
    return _make_request('add', timeout=15, service=service_id, link=link, quantity=quantity)

def get_order_status(order_id):
    """Check the status of a specific order"""
    return _make_request('status', timeout=10, order=order_id)

def get_multiple_order_status(order_ids):
    """Check status of multiple orders at once (if supported by main panel)"""
    # order_ids should be a comma-separated string e.g., "123,124,125"
    return _make_request('status', timeout=15, orders=order_ids)

