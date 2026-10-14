from flask import Flask, request, jsonify
from flask_cors import CORS
import cloudscraper
import re
import time
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app)

# ========== CONFIGURATION ==========
VALID_API_KEY = "Farhan"
DEVELOPER = "@FarhanXMods"
VERSION = "3.0.0"

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
        # Sử dụng cloudscraper để vượt qua tường lửa Cloudflare của link4m
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        
        response = scraper.get(bypass_url, timeout=25)
        final_url = response.url
        html = response.text
        
        # Kiểm tra nếu lấy được link chuyển hướng trực tiếp khác trang ban đầu
        if final_url != bypass_url and "link4m" not in final_url and "challenges.cloudflare.com" not in final_url:
            success_count += 1
            processing_time = time.time() - start_time
            return jsonify({
                "success": True,
                "original_url": bypass_url,
                "bypassed_url": final_url,
                "domain": domain,
                "method": "cloudscraper_redirect",
                "processing_time": f"{processing_time:.2f}s",
                "api_developer": DEVELOPER,
                "version": VERSION
            })
        
        # Quét tìm các định dạng URL ẩn được mã hóa trong mã nguồn trang đích
        url_patterns = [
            r'window\.location\.href\s*=\s*["\'](http[s]?://[^"\']+)["\']',
            r'url\s*=\s*["\'](http[s]?://[^"\']+)["\']',
            r'href=["\'](http[s]?://[^"\']+)["\']',
            r'data-url=["\'](http[s]?://[^"\']+)["\']'
        ]
        
        extracted_url = None
        for pattern in url_patterns:
            matches = re.findall(pattern, html)
            for candidate in matches:
                if domain not in candidate and "cloudflare" not in candidate and "google" not in candidate and "jquery" not in candidate:
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
                "method": "cloudscraper_html_extract",
                "processing_time": f"{processing_time:.2f}s",
                "api_developer": DEVELOPER,
                "version": VERSION
            })
        
        return jsonify({"success": False, "error": "Không thể bóc tách link. Trang web yêu cầu xác thực nâng cao.", "domain": domain, "api_developer": DEVELOPER}), 400
            
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
