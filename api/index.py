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
VERSION = "1.1.0"

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
        # Giả lập trình duyệt thực tế để tránh bị chặn bot
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        }
        
        session = requests.Session()
        response = session.get(bypass_url, headers=headers, allow_redirects=True, timeout=20)
        final_url = response.url
        
        # Nếu URL sau khi request khác URL ban đầu (đã qua redirect tự động)
        if final_url != bypass_url and not "link4m" in final_url:
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
        else:
            html = response.text
            
            # Mở rộng danh sách regex tìm kiếm link chuyển hướng ẩn bên trong trang
            url_patterns = [
                r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
                r'<meta\s+http-equiv="refresh"\s+content="[^;]+;\s*url=([^"\']+)"',
                r'<meta.*?url=([^"\']+)["\']',
                r'<a[^>]*id="download-button"[^>]*href=["\']([^"\']+)"',
                r'<a[^>]*class="[^"]*btn[^"]*"[^>]*href=["\'](http[s]?://[^"\']+)["\']',
                r'data-url=["\']([^"\']+)["\']',
                r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            ]
            
            extracted_url = None
            for pattern in url_patterns:
                matches = re.findall(pattern, html)
                for match in matches:
                    url_candidate = match[0] if isinstance(match, tuple) else match
                    # Lọc bỏ các link nội bộ hoặc link rác của trang shortener
                    if url_candidate.startswith('http') and domain not in url_candidate and 'javascript' not in url_candidate:
                        extracted_url = url_candidate
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
            
            return jsonify({"success": False, "error": "Could not bypass link. Target page protected.", "domain": domain, "api_developer": DEVELOPER}), 400
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "api_developer": DEVELOPER}), 400

@app.route('/')
def home():
    return jsonify({
        "name": "Link Bypass API",
        "description": "Bypass URL shorteners easily",
        "version": VERSION,
        "endpoint": "/api?bypass=YOUR_URL&key=YOUR_KEY",
        "supported_domains": SUPPORTED_DOMAINS,
        "api_developer": DEVELOPER
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "error": "Endpoint not found", "api_developer": DEVELOPER}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "error": "Internal server error", "api_developer": DEVELOPER}), 500
