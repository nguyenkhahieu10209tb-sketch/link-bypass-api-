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
                    '--disable-software-rasterizer',
                    '--disable-blink-features=AutomationControlled'
                ]
            )
            try:
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    locale="vi-VN",
                    timezone_id="Asia/Ho_Chi_Minh",
                    extra_http_headers={"Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"}
                )
                # Giấu dấu hiệu "trình duyệt tự động" mà các trang hay kiểm tra
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = window.chrome || { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN', 'vi', 'en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                """)
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


def get_code_from_domain(domain):
    """Thử làm đúng các bước link4m yêu cầu: vào trang đích như thể đến từ Google,
    kéo xuống, bấm nút LẤY MÃ, chờ, rồi báo lại những gì nhìn thấy."""
    steps = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-software-rasterizer',
                    '--disable-blink-features=AutomationControlled'
                ]
            )
            try:
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    locale="vi-VN",
                    timezone_id="Asia/Ho_Chi_Minh",
                    extra_http_headers={"Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"}
                )
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = window.chrome || { runtime: {} };
                """)
                page = context.new_page()

                # Bước 1-3: vào trang đích với "nguồn đến" là Google
                page.goto("https://" + domain, timeout=30000,
                          wait_until="domcontentloaded",
                          referer="https://www.google.com/")
                steps.append("Đã mở trang: " + page.url + " | tiêu đề: " + page.title())
                time.sleep(4)

                # Bước 4: kéo xuống cuối và bấm nút LẤY MÃ
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)
                clicked = None
                for selector in [
                    'img[alt*="LẤY MÃ" i]', 'img[src*="l4m" i]', 'img[src*="link4m" i]',
                    'text=LẤY MÃ', 'a:has-text("LẤY MÃ")', 'button:has-text("LẤY MÃ")',
                    '[id*="l4m" i]', '[class*="l4m" i]', '[onclick*="l4m" i]'
                ]:
                    try:
                        el = page.locator(selector).first
                        if el.count() > 0 and el.is_visible():
                            el.scroll_into_view_if_needed(timeout=3000)
                            el.click(timeout=3000)
                            clicked = selector
                            break
                    except Exception:
                        continue
                steps.append("Nút LẤY MÃ bấm bằng: " + str(clicked))

                time.sleep(20)  # chờ đếm ngược

                # Bước 5: bấm thử một link bất kỳ rồi quay lại vị trí đó
                try:
                    link = page.locator('a[href]:visible').first
                    link.click(timeout=3000, no_wait_after=True)
                    steps.append("Đã bấm 1 link bất kỳ")
                except Exception as e:
                    steps.append("Không bấm được link: " + str(e)[:80])
                time.sleep(5)
                steps.append("Địa chỉ hiện tại: " + page.url)

                # Báo lại những dòng chữ có vẻ liên quan đến mã
                body = ""
                try:
                    body = page.inner_text("body")
                except Exception:
                    pass
                lines = [l.strip() for l in body.splitlines() if l.strip()]
                hints = [l[:120] for l in lines if "mã" in l.lower() or "code" in l.lower()][:15]
                return {"steps": steps, "hints": hints, "tail": " | ".join(lines[-12:])[:600]}
            finally:
                browser.close()
    except Exception as e:
        return {"steps": steps, "exception": str(e)[:500]}


@app.route('/getcode', methods=['GET', 'OPTIONS'])
def getcode_endpoint():
    if request.method == 'OPTIONS':
        return '', 204
    domain = (request.args.get('domain') or '').strip()
    domain = domain.replace('https://', '').replace('http://', '').split('/')[0]
    if not domain:
        return jsonify({"error": "Thiếu tham số domain, ví dụ ?domain=zodii.co"}), 400
    return jsonify(get_code_from_domain(domain))


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
