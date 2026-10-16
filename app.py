import os
import time
from urllib.parse import unquote
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright

app = Flask(__name__)
CORS(app)


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response


def bypass_with_playwright(target_url):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-software-rasterizer'
                ]
            )
            try:
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = context.new_page()

                page.goto(target_url, timeout=35000, wait_until="domcontentloaded")

                start_time = time.time()
                final_url = None

                while time.time() - start_time < 25:
                    current_url = page.url

                    if (
                        current_url != target_url
                        and "challenges.cloudflare.com" not in current_url
                        and "link4m" not in current_url
                    ):
                        final_url = current_url
                        break

                    try:
                        for selector in [
                            'button:has-text("Lấy mã")',
                            'button:has-text("Tiếp tục")',
                            '#continue-btn',
                            '.get-link',
                            'a:has-text("Lấy mã")'
                        ]:
                            btn = page.locator(selector).first
                            if btn.is_visible():
                                btn.click(timeout=1000)
                                time.sleep(2)
                    except Exception:
                        pass

                    time.sleep(1)

                if not final_url:
                    final_url = page.url

                # Chụp lại trang trình duyệt đang thấy, để biết nó bị kẹt ở đâu
                debug = {"final_url": page.url}
                try:
                    debug["title"] = page.title()
                    debug["text"] = page.inner_text("body")[:400]
                except Exception as de:
                    debug["debug_error"] = str(de)
            finally:
                # Luôn đóng trình duyệt để không tốn RAM (gói free chỉ có 512MB)
                browser.close()

            if "challenges.cloudflare.com" in final_url or final_url == target_url:
                return None, debug
            return final_url, debug

    except Exception as e:
        print(f"Playwright Error: {e}")
        return None, {"exception": str(e)}


@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/bypass', methods=['GET', 'POST', 'OPTIONS'])
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
            "message": "Galaxy Bypass Playwright API is ready."
        }), 200

    url = unquote(str(url)).strip()

    bypassed, debug = bypass_with_playwright(url)

    if not bypassed:
        return jsonify({
            "success": False,
            "original_url": url,
            "error": "Không thể xử lý liên kết hoặc hết thời gian chờ.",
            "debug": debug
        }), 200

    return jsonify({
        "success": True,
        "original_url": url,
        "bypassed_url": bypassed,
        "destination": bypassed,
        "method": "playwright_browser"
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
