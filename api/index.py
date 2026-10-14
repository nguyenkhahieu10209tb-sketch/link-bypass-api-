from flask import Flask, request, jsonify
import requests
import re
from urllib.parse import unquote

app = Flask(__name__)

# Thêm CORS trực tiếp vào header để frontend GitHub Pages gọi thoải mái không bị chặn
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        res = requests.get(target_url, headers=headers, allow_redirects=True, timeout=8)
        match = re.search(r'href=["\'](https?://[^"\']+)["\']', res.text, re.IGNORECASE)
        if match:
            return match.group(1)
        return res.url
    except Exception:
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

    bypassed = bypass_via_worker(url)
    method_used = "cloudflare_worker"

    if not bypassed:
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
