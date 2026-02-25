import requests
import time
import logging
from config import API_KEY, API_URL
from loader import config_col

# ==========================================
# ⚡ SMART API ENGINE (Multi-API Supported)
# ==========================================
def _make_request(action, api_url=API_URL, api_key=API_KEY, timeout=10, retries=2, **kwargs):
    if not api_url or not api_key:
        return {"error": "API Setup Missing"}
        
    payload = {'key': api_key, 'action': action}
    payload.update(kwargs)
    
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
            response = requests.post(api_url, data=payload, headers=headers, timeout=timeout)
            try:
                return response.json()
            except ValueError:
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                logging.error(f"API Error: Invalid JSON. Status: {response.status_code}")
                return {"error": f"Invalid response. Status: {response.status_code}"}
                
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return {"error": "API Connection Timeout."}
            
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return {"error": "API Connection Failed."}
            
        except Exception as e:
            return {"error": str(e)}

    return {"error": "Max retries exceeded"}

# ==========================================
# 🔄 MULTI-API ROUTER
# ==========================================
def get_ext_config(target_id):
    """Check if ID is from External API and route it dynamically"""
    target_str = str(target_id)
    if target_str.startswith("ext_"):
        parts = target_str.split('_')
        if len(parts) >= 3:
            try:
                idx = int(parts[1])
                real_id = parts[2]
                s = config_col.find_one({"_id": "settings"})
                if s and "external_apis" in s and len(s["external_apis"]) > idx:
                    ext = s["external_apis"][idx]
                    return ext.get("url"), ext.get("key"), real_id
            except:
                pass
    return API_URL, API_KEY, target_id

# ==========================================
# 📦 SMM PANEL API FUNCTIONS
# ==========================================
def get_services():
    """Main 1xpanel Services"""
    res = _make_request('services', timeout=15)
    if isinstance(res, list): return res
    return []

def get_external_services(url, key):
    """Fetch Services from Custom External APIs"""
    res = _make_request('services', api_url=url, api_key=key, timeout=15)
    if isinstance(res, list): return res
    return []

def place_order(sid, **kwargs):
    """Place order dynamically to main or external panel"""
    url, key, real_sid = get_ext_config(sid)
    res = _make_request('add', api_url=url, api_key=key, timeout=15, service=real_sid, **kwargs)
    
    # If external, mask the order ID so bot can track status from correct panel
    if str(sid).startswith("ext_") and res and 'order' in res:
        parts = str(sid).split('_')
        idx = parts[1]
        res['order'] = f"ext_{idx}_{res['order']}"
        
    return res

def check_order_status(order_id):
    url, key, real_oid = get_ext_config(order_id)
    return _make_request('status', api_url=url, api_key=key, timeout=10, order=real_oid)

def send_refill(order_id):
    url, key, real_oid = get_ext_config(order_id)
    return _make_request('refill', api_url=url, api_key=key, timeout=10, order=real_oid)

def get_balance():
    res = _make_request('balance', timeout=10)
    if isinstance(res, dict) and 'balance' in res:
        return f"{res.get('balance', '0.00')} {res.get('currency', 'USD')}"
    return "N/A"

# ==========================================
# 🌍 REAL-TIME EXCHANGE RATE API
# ==========================================
def get_live_exchange_rates():
    try:
        res = requests.get("test", timeout=8)
        data = res.json()
        if data and "rates" in data:
            return {
                "BDT": data["rates"].get("BDT", 120),
                "INR": data["rates"].get("INR", 83)
            }
    except Exception:
        pass
    return None
