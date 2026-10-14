from flask import Flask, request, jsonify
import requests
import re
from urllib.parse import unquote, urlparse, parse_qs

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response

CF_WORKER_URL = "https://dry-dew-91c7.nguyenkhahieu10209tb.workers.dev/?url="

def bypass_via_worker(target_url):
    try:
        worker_endpoint = f"{CF_WORKER_URL}{target_url}"
        response = requests.get(worker_endpoint, timeout=12)
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and data.get("bypassed_url"):
                return data["bypassed_url"]
    except Exception as e:
        print(f"Worker Error: {e}")
    return None

def fallback_parser(target_url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': 'https://link4m.com/'
        }
        res = requests.get(target_url, headers=headers, allow_redirects=True, timeout=10)
        
        # Thử tìm link ẩn trong thẻ input hoặc script của trang đích
        match_url = re.search(r'https?://[^\s<>"]+|www\.[^\s<>"]+', res.text)
        
        # Nếu trang trả về chứa các URL chuyển hướng ẩn
        if res.url != target_url:
            return res.url
            
        # Tìm kiếm các pattern chuyển hướng dạng mã hóa thông dụng
        if match_url:
            found = match_url.group(0)
            if "link4m" not in found and "google" not in found:
                return found.rstrip('\'">')
                
        return target_url
    except Exception as e:
        print(f"Fallback Error: {e}")
        return target_url

@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/api/bypass', methods=['GET', 'POST', 'OPTIONS'])
def bypass_endpoint():
    if request.method == 'OPTIONS':
        return '', 204
        
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        url = data.get('url') or request.form.get('url')
    else:
        url = request.args.get('url')

    if not url:
        return jsonify({
            "status": "online",
            "message": "Galaxy Bypass API is ready."
        }), 200

    url = unquote(str(url)).strip()

    # Thử gọi Worker trước
    bypassed = bypass_via_worker(url)
    method_used = "cloudflare_worker"

    # Nếu Worker không trả kết quả hoặc trả về nguyên link cũ, dùng fallback
    if not bypassed or bypassed == url:
        bypassed = fallback_parser(url)
        method_used = "python_fallback"

    return jsonify({
        "success": True,
        "original_url": url,
        "bypassed_url": bypassed,
        "destination": bypassed,
        "method": method_used
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
