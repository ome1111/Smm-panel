import requests
from config import API_URL, API_KEY

def get_services():
    try:
        payload = {'key': API_KEY, 'action': 'services'}
        # 🔥 timeout=10 অ্যাড করা হয়েছে
        response = requests.post(API_URL, data=payload, timeout=10) 
        return response.json()
    except Exception as e:
        print(f"API Error: {e}")
        return None

def place_order(service_id, link, quantity):
    try:
        payload = {'key': API_KEY, 'action': 'add', 'service': service_id, 'link': link, 'quantity': quantity}
        # 🔥 অর্ডারের জন্য timeout=15 অ্যাড করা হয়েছে
        response = requests.post(API_URL, data=payload, timeout=15)
        return response.json()
    except requests.exceptions.Timeout:
        # মেইন সার্ভার ডাউন থাকলেও বট হ্যাং হবে না
        return {"error": "API Connection Timeout. Main Server is currently too slow. Try again."}
    except Exception as e:
        return {"error": str(e)}

def get_order_status(order_id):
    try:
        payload = {'key': API_KEY, 'action': 'status', 'order': order_id}
        response = requests.post(API_URL, data=payload, timeout=10)
        return response.json()
    except:
        return None
