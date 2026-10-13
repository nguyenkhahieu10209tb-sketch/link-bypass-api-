From flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import time
from urllib.parse import urlparse
from collections import OrderedDict

app = Flask(__name__)
CORS(app)

# ========== CONFIGURATION ==========
VALID_API_KEY = "Farhan"  # Only ONE key - No show valid keys
DEVELOPER = "@FarhanXMods"
VERSION = "1.0.0"

# Your specific links
ORIGINAL_LINK = "https://just2earn.com/godx1767110927511"
BYPASSED_LINK = "https://mypdftools.site/ankitkey?deviceId=rand-1767110927483-g5lxha5&verify=57c4582f6cfcb79f955337dca51dca674b98eef8788c6e7419c62db4"

# Supported domains
SUPPORTED_DOMAINS = ["vplink.in", "adsfly.in", "linksgo.in", "just2earn.com"]

# Stats tracking
request_count = 0
success_count = 0

def verify_key(api_key):
    """Simple key verification - only one key works"""
    return api_key == VALID_API_KEY

def extract_domain(url):
    """Extract domain from URL"""
    try:
        return urlparse(url).netloc
    except:
        return None

@app.route('/api', methods=['GET'])
def api_endpoint():
    global request_count, success_count
    
    # Get parameters
    bypass_url = request.args.get('bypass')
    api_key = request.args.get('key')
    
    # Start timing
    start_time = time.time()
    
    # 1. API Key validation (only ONE key, no showing valid keys)
    if not verify_key(api_key):
        return jsonify({
            "success": False,
            "error": "Invalid API key",
            "api_developer": DEVELOPER
        }), 401
    
    # 2. Check if URL provided
    if not bypass_url:
        return jsonify({
            "success": False,
            "error": "Missing 'bypass' parameter",
            "usage": "/api?bypass=YOUR_LINK_HERE&key=Farhan",
            "api_developer": DEVELOPER
        }), 400
    
    request_count += 1
    
    # 3. Get domain
    domain = extract_domain(bypass_url)
    
    # 4. Check if it's the specific original link
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
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "api_developer": DEVELOPER,
            "version": VERSION
        })
    
    # 5. Check if domain is supported
    is_supported = False
    for supported_domain in SUPPORTED_DOMAINS:
        if domain and supported_domain in domain:
            is_supported = True
            break
    
    if not is_supported:
        return jsonify({
            "success": False,
            "error": "Domain not supported",
            "domain": domain,
            "api_developer": DEVELOPER
        }), 400
    
    # 6. Basic bypass attempt for other links
    try:
        # Follow redirects
        response = requests.get(bypass_url, allow_redirects=True, timeout=15)
        final_url = response.url
        
        if final_url != bypass_url:
            success_count += 1
            processing_time = time.time() - start_time
            
            return jsonify({
                "success": True,
                "original_url": bypass_url,
                "bypassed_url": final_url,
                "domain": domain,
                "method": "redirect_follow",
                "processing_time": f"{processing_time:.2f}s",
                "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                "api_developer": DEVELOPER,
                "version": VERSION
            })
        else:
            # Try to extract from HTML
            html = response.text
            
            # Look for URLs in HTML
            url_patterns = [
                r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
                r'<meta.*?url=([^"\']+)["\']',
                r'<a[^>]*href=["\']([^"\']+)"[^>]*>Continue',
                r'data-url=["\']([^"\']+)["\']',
            ]
            
            for pattern in url_patterns:
                match = re.search(pattern, html)
                if match:
                    extracted_url = match.group(1)
                    if not extracted_url.startswith('http'):
                        extracted_url = 'https://' + extracted_url.lstrip('/')
                    
                    success_count += 1
                    processing_time = time.time() - start_time
                    
                    return jsonify({
                        "success": True,
                        "original_url": bypass_url,
                        "bypassed_url": extracted_url,
                        "domain": domain,
                        "method": "html_extract",
                        "processing_time": f"{processing_time:.2f}s",
                        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                        "api_developer": DEVELOPER,
                        "version": VERSION
                    })
            
            return jsonify({
                "success": False,
                "error": "Could not bypass link",
                "domain": domain,
                "api_developer": DEVELOPER
            }), 400
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "api_developer": DEVELOPER
        }), 400

@app.route('/')
def home():
    """Home page - shows API info without exposing keys"""
    return jsonify({
        "name": "Link Bypass API",
        "description": "Bypass URL shorteners easily",
        "version": VERSION,
        "endpoint": "/api?bypass=YOUR_URL&key=YOUR_KEY",
        "supported_domains": SUPPORTED_DOMAINS,
        "example": f"/api?bypass={ORIGINAL_LINK}&key=YOUR_KEY",
        "api_developer": DEVELOPER,
        "note": "Contact @FarhanXMods for access"
    })

@app.route('/api/original', methods=['GET'])
def original_link():
    """Quick access to the specific original link bypass"""
    api_key = request.args.get('key')
    
    if not verify_key(api_key):
        return jsonify({
            "success": False,
            "error": "Invalid API key",
            "api_developer": DEVELOPER
        }), 401
    
    return jsonify({
        "success": True,
        "original_link": ORIGINAL_LINK,
        "bypassed_link": BYPASSED_LINK,
        "domain": "just2earn.com",
        "method": "direct",
        "api_developer": DEVELOPER,
        "version": VERSION
    })

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get API statistics (protected)"""
    api_key = request.args.get('key')
    
    if not verify_key(api_key):
        return jsonify({
            "success": False,
            "error": "Invalid API key",
            "api_developer": DEVELOPER
        }), 401
    
    return jsonify({
        "success": True,
        "total_requests": request_count,
        "successful_bypasses": success_count,
        "success_rate": f"{(success_count/request_count*100):.1f}%" if request_count > 0 else "0%",
        "supported_domains": SUPPORTED_DOMAINS,
        "api_developer": DEVELOPER,
        "version": VERSION
    })

@app.route('/api/check', methods=['GET'])
def check_domain():
    """Check if a domain is supported"""
    url = request.args.get('url')
    api_key = request.args.get('key')
    
    if not verify_key(api_key):
        return jsonify({
            "success": False,
            "error": "Invalid API key",
            "api_developer": DEVELOPER
        }), 401
    
    if not url:
        return jsonify({"error": "URL required"}), 400
    
    domain = extract_domain(url)
    is_supported = False
    
    for supported_domain in SUPPORTED_DOMAINS:
        if domain and supported_domain in domain:
            is_supported = True
            break
    
    return jsonify({
        "success": True,
        "url": url,
        "domain": domain,
        "is_supported": is_supported,
        "supported_domains": SUPPORTED_DOMAINS if is_supported else [],
        "api_developer": DEVELOPER
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Endpoint not found",
        "available_endpoints": ["/api", "/api/original", "/api/stats", "/api/check"],
        "api_developer": DEVELOPER
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error",
        "api_developer": DEVELOPER
    }), 500

if __name__ == '__main__':
    print(f"""
    ╔══════════════════════════════════════════════════╗
    ║         Link Bypass API - {DEVELOPER}              ║
    ╠══════════════════════════════════════════════════╣
    ║  Version: {VERSION}                                         ║
    ║  API Key: [HIDDEN - Contact Developer]           ║
    ║                                                  ║
    ║  Supported Domains:                              ║
    ║  • vplink.in                                     ║
    ║  • adsfly.in                                     ║
    ║  • linksgo.in                                    ║
    ║  • just2earn.com                                 ║
    ║                                                  ║
    ║  Original Link:                                  ║
    ║  {ORIGINAL_LINK[:50]}...  ║
    ║                                                  ║
    ║  Bypassed Link:                                  ║
    ║  {BYPASSED_LINK[:50]}...  ║
    ║                                                  ║
    ║  Test Commands:                                  ║
    ║  curl "http://localhost:5000/api?bypass={ORIGINAL_LINK[:30]}...&key=Farhan"  ║
    ║                                                  ║
    ║  curl http://localhost:5000/api/original?key=Farhan  ║
    ╚══════════════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)

