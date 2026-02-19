import requests
from config import API_KEY, API_URL

def get_services():
    """প্যানেল থেকে সব সার্ভিসের লিস্ট আনা"""
    try:
        r = requests.post(API_URL, data={'key': API_KEY, 'action': 'services'})
        return r.json()
    except Exception as e:
        print(f"API Services Error: {e}")
        return []

def place_order(sid, link, qty):
    """আসল প্যানেলে অর্ডার প্লেস করা"""
    try:
        payload = {
            'key': API_KEY, 
            'action': 'add', 
            'service': sid, 
            'link': link, 
            'quantity': qty
        }
        r = requests.post(API_URL, data=payload)
        return r.json()
    except Exception as e:
        return {"error": f"API Connection Failed: {str(e)}"}

def get_balance():
    """আপনার প্যানেলের মেইন ব্যালেন্স চেক করা (অ্যাডমিন প্যানেলের জন্য)"""
    try:
        r = requests.post(API_URL, data={'key': API_KEY, 'action': 'balance'})
        data = r.json()
        return f"{data.get('balance', '0.00')} {data.get('currency', 'USD')}"
    except:
        return "N/A"
