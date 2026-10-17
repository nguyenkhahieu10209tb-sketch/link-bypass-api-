import os
import re
import html
import json
import uuid
import random
import time
import threading
from urllib.parse import unquote, urlparse
from flask import Flask, request, jsonify, redirect, Response
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


# ============================================================
# LẤY MÃ KIỂU "GIAO VIỆC RỒI XEM TIẾN ĐỘ"
# Vì thời gian chờ của link4m có thể 45 / 60 / 120 giây, một request không chờ nổi.
# /getcode?domain=...  -> bắt đầu chạy nền, chuyển sang trang /view để xem trực tiếp
# /view?id=...         -> trang tự làm mới: ảnh chụp trang + nhật ký + kết quả
# ============================================================
JOBS = {}
JOB_LOCK = threading.Lock()


def run_job(job_id, domain, max_wait):
    job = JOBS[job_id]

    def log(msg):
        job["log"].append(str(round(time.time() - job["t0"])) + "s | " + str(msg)[:300])
        del job["log"][:-80]

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

                def pause(sec):
                    # wait_for_timeout vẫn xử lý sự kiện của trình duyệt (khác time.sleep)
                    page.wait_for_timeout(int(sec * 1000))

                def shot():
                    try:
                        job["shot"] = page.screenshot(type="jpeg", quality=45)
                    except Exception:
                        pass

                def all_lines():
                    out = []
                    for fr in page.frames:
                        try:
                            t = fr.inner_text("body", timeout=1500)
                        except Exception:
                            continue
                        out.extend(l.strip() for l in t.splitlines() if l.strip())
                    return out

                def new_lines(baseline):
                    return [l[:100] for l in all_lines() if l not in baseline][:8]

                def code_like(lines):
                    return [
                        l for l in lines
                        if 5 <= len(l) <= 20 and re.fullmatch(r'[A-Za-z0-9_\-]+', l)
                        and any(c.isdigit() for c in l) and any(c.isalpha() for c in l)
                    ][:5]

                def wait_countdown(baseline, label):
                    """Chờ linh hoạt: lướt như người đọc, ghi lại chữ mới, dừng khi có dấu hiệu xong."""
                    start = time.time()
                    saw_new = False
                    last = None
                    direction = 1
                    while time.time() - start < max_wait:
                        try:
                            page.mouse.move(random.randint(100, 900), random.randint(100, 600))
                            page.mouse.wheel(0, 350 * direction)
                        except Exception:
                            pass
                        direction = -direction
                        pause(3)
                        shot()
                        nl = new_lines(baseline)
                        if nl != last:
                            log(label + " | chữ mới: " + (" / ".join(nl) if nl else "(không còn)"))
                            last = nl
                        if code_like(nl):
                            log("Thấy dòng giống mã: " + str(code_like(nl)))
                            return "code"
                        if nl:
                            saw_new = True
                        elif saw_new:
                            log(label + " | chữ đếm ngược đã biến mất, coi như xong")
                            return "gone"
                    log(label + " | hết thời gian chờ tối đa (" + str(max_wait) + "s)")
                    return "timeout"

                def click_lay_ma():
                    try:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    except Exception:
                        pass
                    pause(1.5)
                    for selector in [
                        'text=LẤY MÃ', 'a:has-text("LẤY MÃ")', 'button:has-text("LẤY MÃ")',
                        'img[alt*="LẤY MÃ" i]', '[id*="l4m" i]', '[class*="l4m" i]',
                        '[onclick*="l4m" i]'
                    ]:
                        try:
                            el = page.locator(selector).first
                            if el.count() > 0 and el.is_visible():
                                el.scroll_into_view_if_needed(timeout=3000)
                                el.click(timeout=3000)
                                return selector
                        except Exception:
                            continue
                    return None

                log("Mở trang " + domain + " (nguồn đến: Google)")
                page.goto("https://" + domain, timeout=30000,
                          wait_until="domcontentloaded",
                          referer="https://www.google.com/")
                pause(4)
                shot()
                orig_url = page.url
                deadline = time.time() + max_wait
                last_state = None
                link_attempts = 0
                last_link_time = 0
                code = None

                def button_text():
                    """Đọc chữ trên nút đỏ của link4m (đếm ngược, hướng dẫn, hoặc mã)."""
                    try:
                        return page.evaluate("""() => {
                            const re = /(Vui lòng chờ|Lấy mã sau|LẤY MÃ|Vui lòng click|Mã KM)/i;
                            let best = null;
                            for (const el of document.querySelectorAll('a,button,div,span,p')) {
                                if (el.children.length > 3) continue;
                                const t = (el.innerText || '').trim();
                                if (t && t.length < 160 && re.test(t) && (!best || t.length < best.length)) best = t;
                            }
                            return best;
                        }""")
                    except Exception:
                        return None

                def click_any_link():
                    """Bấm một link bất kỳ của trang (ưu tiên link nội bộ), rồi quay lại nếu bị chuyển trang."""
                    try:
                        links = page.evaluate("""() => Array.from(document.querySelectorAll('a[href]'))
                            .filter(a => a.offsetParent !== null)
                            .map(a => ({h: a.getAttribute('href'), t: (a.innerText || '').trim().slice(0, 30),
                                        host: a.hostname, path: a.pathname}))""")
                        host = urlparse(page.url).hostname or ""
                        cands = [
                            l for l in links
                            if l["h"] and not l["h"].startswith(("#", "javascript", "mailto", "tel"))
                            and l["host"] == host and l["path"] not in ("", "/")
                        ]
                        if cands:
                            pick = cands[0]
                            page.locator('a[href="' + pick["h"] + '"]:visible').first.click(timeout=4000, no_wait_after=True)
                            log("Đã bấm link nội bộ: '" + pick["t"] + "'")
                        else:
                            page.locator('a[href]:visible').nth(2).click(timeout=4000, no_wait_after=True)
                            log("Không có link nội bộ, đã bấm link thứ 3")
                    except Exception as e:
                        log("Không bấm được link: " + str(e)[:100])
                    pause(4)
                    # đóng tab quảng cáo nếu có
                    for extra in context.pages[1:]:
                        try:
                            extra.close()
                        except Exception:
                            pass
                    if page.url.split('#')[0] != orig_url.split('#')[0]:
                        log("Trang đã chuyển sang " + page.url + ", quay lại")
                        try:
                            page.go_back(timeout=8000)
                        except Exception:
                            try:
                                page.goto(orig_url, timeout=20000, wait_until="domcontentloaded")
                            except Exception:
                                pass
                        pause(3)

                while time.time() < deadline:
                    txt = button_text() or ""
                    if txt != last_state:
                        log("Nút: " + (txt if txt else "(không thấy nút)"))
                        last_state = txt
                        shot()
                    m = re.search(r'Mã KM:\s*([A-Za-z0-9]+)', txt)
                    if m:
                        code = m.group(1)
                        log("ĐÃ CÓ MÃ: " + code)
                        shot()
                        break
                    low = txt.lower()
                    if "vui lòng chờ" in low or "lấy mã sau" in low:
                        # đang đếm ngược: lướt nhẹ như người đang đọc
                        try:
                            page.mouse.move(random.randint(100, 900), random.randint(100, 600))
                            page.mouse.wheel(0, random.choice([-120, 120]))
                        except Exception:
                            pass
                        pause(2)
                        if int(time.time()) % 10 < 2:
                            shot()
                    elif "click vào link" in low:
                        if link_attempts < 3 and time.time() - last_link_time > 20:
                            link_attempts += 1
                            last_link_time = time.time()
                            click_any_link()
                        log("Lướt xuống và bấm nút: " + str(click_lay_ma()))
                        pause(3)
                    elif "lấy mã" in low:
                        log("Bấm nút LẤY MÃ: " + str(click_lay_ma()))
                        pause(3)
                    else:
                        try:
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        except Exception:
                            pass
                        pause(2)

                if not code:
                    log("Hết thời gian tối đa (" + str(max_wait) + "s) mà chưa có mã. Link4m sắp/đã hết phiên 600s và có thể đã đổi sang trang khác, hãy mở lại link4m để xem từ khóa mới")
                job["result"] = {"code": code, "last_button_text": last_state, "url": page.url}
                shot()
            finally:
                browser.close()
    except Exception as e:
        job["result"] = {"exception": str(e)[:500]}
        log("LỖI: " + str(e)[:200])
    finally:
        job["status"] = "done"
        log("Kết thúc")


@app.route('/getcode', methods=['GET', 'OPTIONS'])
def getcode_endpoint():
    if request.method == 'OPTIONS':
        return '', 204
    domain = (request.args.get('domain') or '').strip()
    domain = domain.replace('https://', '').replace('http://', '').split('/')[0]
    if not domain:
        return jsonify({"error": "Thiếu tham số domain, ví dụ ?domain=zodii.co"}), 400
    try:
        max_wait = max(30, min(570, int(request.args.get('wait', 480))))
    except ValueError:
        max_wait = 480

    with JOB_LOCK:
        for j in JOBS.values():
            if j["status"] == "running":
                return redirect('/view?id=' + j["id"])  # đang có việc chạy, xem việc đó
        job_id = uuid.uuid4().hex[:8]
        JOBS[job_id] = {"id": job_id, "status": "running", "log": [], "result": None,
                        "shot": None, "t0": time.time(), "domain": domain}
        for old in list(JOBS.keys())[:-5]:
            del JOBS[old]
    threading.Thread(target=run_job, args=(job_id, domain, max_wait), daemon=True).start()
    return redirect('/view?id=' + job_id)


@app.route('/job', methods=['GET'])
def job_endpoint():
    job = JOBS.get(request.args.get('id', ''))
    if not job:
        return jsonify({"error": "Không tìm thấy việc này (máy có thể vừa khởi động lại)"}), 404
    return jsonify({"status": job["status"], "elapsed": round(time.time() - job["t0"]),
                    "log": job["log"], "result": job["result"]})


@app.route('/shot', methods=['GET'])
def shot_endpoint():
    job = JOBS.get(request.args.get('id', ''))
    if not job or not job.get("shot"):
        return "chưa có ảnh", 404
    resp = Response(job["shot"], mimetype="image/jpeg")
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/view', methods=['GET'])
def view_endpoint():
    job_id = request.args.get('id', '')
    job = JOBS.get(job_id)
    if not job:
        return "Không tìm thấy việc này (máy có thể vừa khởi động lại). Hãy mở lại /getcode?domain=...", 404
    refresh = '<meta http-equiv="refresh" content="5">' if job["status"] == "running" else ''
    log_text = html.escape("\n".join(job["log"]))
    result_text = html.escape(json.dumps(job["result"], ensure_ascii=False, indent=1)) if job["result"] else "(chưa có)"
    page_html = (
        '<!doctype html><html><head><meta charset="utf-8">' + refresh +
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>body{background:#111;color:#eee;font-family:sans-serif;padding:10px}'
        'pre{white-space:pre-wrap;word-break:break-word;background:#1b1b1b;padding:8px;border-radius:8px;font-size:12px}'
        'img{width:100%;border-radius:8px}</style></head><body>'
        '<h3>' + html.escape(job["domain"]) + ' — ' + job["status"] + ' (' + str(round(time.time() - job["t0"])) + 's)</h3>'
        + ('<h2 style="color:#4ade80">MÃ: ' + html.escape(str(job["result"].get("code"))) + '</h2>'
           if job["result"] and job["result"].get("code") else '') +
        '<img src="/shot?id=' + job_id + '&t=' + str(int(time.time())) + '" alt="(chưa có ảnh)">'
        '<h4>Kết quả</h4><pre>' + result_text + '</pre>'
        '<h4>Nhật ký</h4><pre>' + log_text + '</pre></body></html>'
    )
    return page_html


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
