from flask import Flask, request, jsonify
import requests
import re
from urllib.parse import unquote

app = Flask(__name__)

# Cloudflare Worker Proxy Endpoint
CF_WORKER_URL = "https://dry-dew-91c7.nguyenkhahieu10209tb.workers.dev/?url="

def bypass_via_worker(target_url):
    """
    Gửi request tới Cloudflare Worker proxy để giải mã/bypass link
    """
    try:
        worker_endpoint = f"{CF_WORKER_URL}{target_url}"
        response = requests.get(worker_endpoint, timeout=12)
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and data.get("bypassed_url"):
                return data["bypassed_url"]
    except Exception as e:
        print(f"CF Worker bypass error: {e}")
    return None

def fallback_parser(target_url):
    """
    Xử lý dự phòng bằng Python khi Worker không phản hồi
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }
        res = requests.get(target_url, headers=headers, allow_redirects=True, timeout=8)
        
        # Tìm URL theo pattern regex cơ bản
        match = re.search(r'href=["\'](https?://[^"\']+)["\']', res.text, re.IGNORECASE)
        if match:
            return match.group(1)
            
        return res.url
    except Exception as e:
        print(f"Fallback parser error: {e}")
        return target_url

@app.route('/api/bypass', methods=['GET', 'POST'])
def bypass_endpoint():
    # Lấy URL từ parameter GET hoặc JSON body POST
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        url = data.get('url')
    else:
        url = request.args.get('url')

    if not url:
        return jsonify({
            "success": False,
            "error": "Thiếu tham số 'url'. Vui lòng truyền URL cần bypass."
        }), 400

    url = unquote(url).strip()

    # Thử qua Cloudflare Worker trước
    bypassed = bypass_via_worker(url)
    method_used = "cloudflare_worker"

    # Nếu Worker thất bại, chuyển sang phương thức dự phòng
    if not bypassed:
        bypassed = fallback_parser(url)
        method_used = "python_fallback"

    return jsonify({
        "success": True,
        "original_url": url,
        "bypassed_url": bypassed,
        "method": method_used
    })

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "online",
        "service": "Galaxy Bypass API",
        "cf_worker_active": True
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
