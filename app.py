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
                bypassed = data["bypassed_url"]
                # Chặn tuyệt đối nếu dính link challenge từ Worker trả về
                if "challenges.cloudflare.com" in bypassed:
                    return None
                return bypassed
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
        
        # Nếu trang trả về bị kẹt ở trang challenge của Cloudflare
        if "challenges.cloudflare.com" in res.url or "cf-turnstile" in res.text:
            return None
            
        if res.url != target_url and "challenges.cloudflare.com" not in res.url:
            return res.url
            
        # Tìm kiếm các link trong nội dung HTML nhưng lọc bỏ rác
        matches = re.findall(r'https?://[^\s<>"]+', res.text)
        for link in matches:
            if not any(x in link for x in ["cloudflare", "link4m", "google", "jquery", "jsdelivr"]):
                return link.rstrip('\'">')
                
        return None
    except Exception as e:
        print(f"Fallback Error: {e}")
        return None

@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/bypass', methods=['GET', 'POST', 'OPTIONS'])        # Đã thêm route này để khớp Frontend
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

    # Nếu Worker không thành công, chạy fallback python
    if not bypassed:
        bypassed = fallback_parser(url)
        method_used = "python_fallback"

    # Kiểm tra lần cuối: Nếu vẫn không tìm được hoặc lòi ra link challenge
    if not bypassed or "challenges.cloudflare.com" in bypassed:
        return jsonify({
            "success": False,
            "original_url": url,
            "error": "Link bị bảo vệ bởi Cloudflare Turnstile, không thể vượt tự động."
        }), 200

    return jsonify({
        "success": True,
        "original_url": url,
        "bypassed_url": bypassed,
        "destination": bypassed,
        "method": method_used
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
