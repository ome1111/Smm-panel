import requests
import time
from config import API_KEY, API_URL

# ==========================================
# ⚡ SMART API ENGINE (Cloudflare Bypass + Auto-Retry)
# ==========================================
def _make_request(action, timeout=15, retries=3, **kwargs):
    """
    Ei function ti API request handle korbe, Cloudflare bypass korbe 
    ebong server slow thakle 3 bar auto retry korbe.
    """
    payload = {'key': API_KEY, 'action': action}
    payload.update(kwargs)
    
    # 🔥 FIX 1: Cloudflare Bypass Header (Eta chara panel request block korte pare)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for attempt in range(retries):
        try:
            response = requests.post(API_URL, data=payload, headers=headers, timeout=timeout)
            
            # 🔥 FIX 2: Panel er actual error gulo accurately dhorar jonno json aage parse kora
            try:
                data = response.json()
                return data
            except ValueError:
                # Jodi JSON response na ashe (Mane API URL e kono vul ache)
                response.raise_for_status()
                return {"error": f"Invalid response from main panel. Check API URL. Status: {response.status_code}"}
                
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(2) # 2 second wait kore abar try korbe
                continue
            return {"error": "API Connection Timeout. Main panel is too slow."}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return {"error": f"API Error: {str(e)}"}

# ==========================================
# 📦 SMM PANEL API FUNCTIONS
# ==========================================
def get_services():
    res = _make_request('services', timeout=20)
    return res if isinstance(res, list) else []

def place_order(sid, link, qty):
    return _make_request('add', timeout=20, service=sid, link=link, quantity=qty)

def check_order_status(order_id):
    return _make_request('status', timeout=15, order=order_id)

def send_refill(order_id):
    return _make_request('refill', timeout=15, order=order_id)

def get_balance():
    res = _make_request('balance', timeout=15)
    if isinstance(res, dict):
        return f"{res.get('balance', '0.00')} {res.get('currency', 'USD')}"
    return "N/A"
