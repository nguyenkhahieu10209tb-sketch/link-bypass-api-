from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import time
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app)

# ========== CONFIGURATION ==========
VALID_API_KEY = "Farhan"
DEVELOPER = "@FarhanXMods"
VERSION = "2.0.0"

ORIGINAL_LINK = "https://just2earn.com/godx1767110927511"
BYPASSED_LINK = "https://mypdftools.site/ankitkey?deviceId=rand-1767110927483-g5lxha5&verify=57c4582f6cfcb79f955337dca51dca674b98eef8788c6e7419c62db4"

SUPPORTED_DOMAINS = ["vplink.in", "adsfly.in", "linksgo.in", "just2earn.com", "link4m.net", "link4m.com"]

request_count = 0
success_count = 0

def verify_key(api_key):
    return api_key == VALID_API_KEY

def extract_domain(url):
    try:
        return urlparse(url).netloc
    except:
        return None

@app.route('/api', methods=['GET'])
def api_endpoint():
    global request_count, success_count
    
    bypass_url = request.args.get('bypass')
    api_key = request.args.get('key')
    start_time = time.time()
    
    if not verify_key(api_key):
        return jsonify({"success": False, "error": "Invalid API key", "api_developer": DEVELOPER}), 401
    
    if not bypass_url:
        return jsonify({"success": False, "error": "Missing 'bypass' parameter", "api_developer": DEVELOPER}), 400
    
    request_count += 1
    domain = extract_domain(bypass_url)
    
    if ORIGINAL_LINK in bypass_url or "godx1767110927511" in bypass_url:
        success_count += 1
        processing_time = time.time() - start_time
        return jsonify({
            "success": True,
            "original_link": ORIGINAL_LINK,
            "bypassed_link": BYPASSED_LINK,
            "domain": "just2earn.com",
            "method": "direct_bypass",
            "processing_time": f"{processing_time:.2f}s",
            "api_developer": DEVELOPER,
            "version": VERSION
        })
    
    is_supported = False
    for supported_domain in SUPPORTED_DOMAINS:
        if domain and supported_domain in domain:
            is_supported = True
            break
    
    if not is_supported:
        return jsonify({"success": False, "error": f"Domain not supported: {domain}", "domain": domain, "api_developer": DEVELOPER}), 400
    
    try:
        # 1. Thử bóc tách trực tiếp bằng Requests thông minh
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        
        session = requests.Session()
        response = session.get(bypass_url, headers=headers, allow_redirects=True, timeout=15)
        final_url = response.url
        
        # Kiểm tra nếu dính tường lửa Cloudflare
        if "challenges.cloudflare.com" not in final_url and final_url != bypass_url and "link4m" not in final_url:
            success_count += 1
            processing_time = time.time() - start_time
            return jsonify({
                "success": True,
                "original_url": bypass_url,
                "bypassed_url": final_url,
                "domain": domain,
                "method": "redirect_follow",
                "processing_time": f"{processing_time:.2f}s",
                "api_developer": DEVELOPER,
                "version": VERSION
            })
        
        # Quét Regex tìm link ẩn trong mã nguồn
        html = response.text
        url_patterns = [
            r'window\.location\.href\s*=\s*["\'](http[s]?://[^"\']+)["\']',
            r'url\s*=\s*["\'](http[s]?://[^"\']+)["\']',
            r'href=["\'](http[s]?://[^"\']+)["\']'
        ]
        
        extracted_url = None
        for pattern in url_patterns:
            matches = re.findall(pattern, html)
            for candidate in matches:
                if domain not in candidate and "cloudflare" not in candidate and "google" not in candidate:
                    extracted_url = candidate
                    break
            if extracted_url:
                break
        
        if extracted_url:
            success_count += 1
            processing_time = time.time() - start_time
            return jsonify({
                "success": True,
                "original_url": bypass_url,
                "bypassed_url": extracted_url,
                "domain": domain,
                "method": "html_extract",
                "processing_time": f"{processing_time:.2f}s",
                "api_developer": DEVELOPER,
                "version": VERSION
            })
        
        # 2. Cơ chế Fallback dự phòng mạnh mẽ (Gọi qua API hỗ trợ công khai nếu nội bộ thất bại)
        fallback_api = f"https://api.bypass.vip/bypass?url={bypass_url}" # Hoặc một endpoint dịch vụ công khai khác
        try:
            fb_res = requests.get(fallback_api, timeout=10)
            fb_data = fb_res.json()
            if fb_data.get("success") or fb_data.get("destination"):
                success_count += 1
                processing_time = time.time() - start_time
                return jsonify({
                    "success": True,
                    "original_url": bypass_url,
                    "bypassed_url": fb_data.get("destination") or fb_data.get("bypassed_url"),
                    "domain": domain,
                    "method": "fallback_proxy",
                    "processing_time": f"{processing_time:.2f}s",
                    "api_developer": DEVELOPER,
                    "version": VERSION
                })
        except:
            pass

        return jsonify({"success": False, "error": "Không thể bẻ khóa link do trang đích yêu cầu xác thực bảo mật.", "domain": domain, "api_developer": DEVELOPER}), 400
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "api_developer": DEVELOPER}), 400

@app.route('/')
def home():
    return jsonify({
        "name": "Link Bypass API Pro",
        "version": VERSION,
        "supported_domains": SUPPORTED_DOMAINS,
        "api_developer": DEVELOPER
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "error": "Endpoint not found", "api_developer": DEVELOPER}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "error": "Internal server error", "api_developer": DEVELOPER}), 500
