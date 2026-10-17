import os
import re
import html
import json
import uuid
import random
import time
import threading
from urllib.parse import urlparse
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from playwright.sync_api import sync_playwright

app = Flask(__name__)
CORS(app)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# Cấu hình chống phát hiện bot và tối ưu chạy trên Render Docker
BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--disable-software-rasterizer',
    '--disable-blink-features=AutomationControlled',
    '--disable-features=IsolateOrigins,site-per-process',
    '--window-size=1280,800',
]

JOBS = {}
JOB_LOCK = threading.Lock()

def run_job(job_id, domain, max_wait):
    job = JOBS[job_id]

    def log(msg):
        job["log"].append(str(round(time.time() - job["t0"])) + "s | " + str(msg)[:300])
        del job["log"][:-80]

    try:
        with sync_playwright() as p:
            # Khởi động trình duyệt với cấu hình tàng hình
            browser = p.chromium.launch(headless=True, args=BROWSER_ARGS)
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    locale="vi-VN",
                    timezone_id="Asia/Ho_Chi_Minh",
                    extra_http_headers={
                        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"'
                    },
                )
                
                # Ép thuộc tính ẩn danh để qua mặt bộ lọc chống bot của trang đích
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = window.chrome || { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN', 'vi', 'en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                """)
                
                page = context.new_page()

                def pause(sec):
                    page.wait_for_timeout(int(sec * 1000))

                def shot():
                    try:
                        job["shot"] = page.screenshot(type="jpeg", quality=50)
                    except Exception:
                        pass

                def button_text():
                    try:
                        return page.evaluate("""() => {
                            const re = /(Vui lòng chờ|Lấy mã sau|LẤY MÃ|lấy mã|Vui lòng click|Mã KM)/i;
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

                def click_lay_ma():
                    try:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    except Exception:
                        pass
                    pause(1.5)
                    
                    # Danh sách bộ chọn linh hoạt, không phân biệt hoa thường để bắt trọn nút bấm
                    selectors = [
                        'text=/lấy mã/i',
                        'a:has-text("lấy mã")',
                        'button:has-text("lấy mã")',
                        'div:has-text("LẤY MÃ")',
                        'img[alt*="lấy mã" i]',
                        '[id*="l4m" i]',
                        '[class*="l4m" i]'
                    ]
                    
                    for selector in selectors:
                        try:
                            el = page.locator(selector).first
                            if el.count() > 0 and el.is_visible():
                                el.scroll_into_view_if_needed(timeout=3000)
                                el.click(timeout=3000)
                                return selector
                        except Exception:
                            continue
                    return None

                log("Mở trang đích: " + domain + " (với Referer Google)")
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

                def click_any_link():
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
                            log("Đã bấm link dự phòng")
                    except Exception as e:
                        log("Không bấm được link: " + str(e)[:100])
                    pause(4)
                    for extra in context.pages[1:]:
                        try:
                            extra.close()
                        except Exception:
                            pass
                    if page.url.split('#')[0] != orig_url.split('#')[0]:
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
                        log("Trạng thái nút: " + (txt if txt else "(đang đếm ngược)"))
                        last_state = txt
                        shot()
                        
                    m = re.search(r'Mã KM:\s*([A-Za-z0-9]+)', txt)
                    if m:
                        code = m.group(1)
                        log("ĐÃ TÌM THẤY MÃ: " + code)
                        shot()
                        break
                        
                    low = txt.lower()
                    if "vui lòng chờ" in low or "lấy mã sau" in low or not txt:
                        # Giả lập tương tác chuột ngẫu nhiên để chống đóng băng bộ đếm ngược
                        try:
                            page.mouse.move(random.randint(150, 850), random.randint(150, 550))
                            page.mouse.wheel(0, random.choice([-100, 100]))
                        except Exception:
                            pass
                        pause(2.5)
                        if int(time.time()) % 12 < 2:
                            shot()
                    elif "click vào link" in low:
                        if link_attempts < 3 and time.time() - last_link_time > 20:
                            link_attempts += 1
                            last_link_time = time.time()
                            click_any_link()
                        log("Cuộn trang và bấm: " + str(click_lay_ma()))
                        pause(3)
                    elif "lấy mã" in low:
                        log("Bấm nút lấy mã: " + str(click_lay_ma()))
                        pause(3)
                    else:
                        try:
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        except Exception:
                            pass
                        pause(2)

                if not code:
                    log("Hết thời gian (" + str(max_wait) + "s) mà chưa lấy được mã.")
                job["result"] = {"code": code, "last_button_text": last_state, "url": page.url}
                shot()
            finally:
                browser.close()
    except Exception as e:
        job["result"] = {"exception": str(e)[:500]}
        log("LỖI HỆ THỐNG: " + str(e)[:200])
    finally:
        job["status"] = "done"
        log("Hoàn thành tiến trình")


# --- API ENDPOINTS CHO FRONTEND CYBERPUNK ---

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "online"})


@app.route('/getcode', methods=['GET', 'OPTIONS'])
def getcode_endpoint():
    if request.method == 'OPTIONS':
        return '', 204
    domain = (request.args.get('domain') or '').strip()
    domain = domain.replace('https://', '').replace('http://', '').split('/')[0]
    if not domain:
        return jsonify({"error": "Thiếu tham số domain"}), 400
    try:
        max_wait = max(30, min(570, int(request.args.get('wait', 480))))
    except ValueError:
        max_wait = 480

    with JOB_LOCK:
        for j in list(JOBS.values()):
            if j["status"] == "running":
                return jsonify({"id": j["id"], "reused": True})
        
        job_id = uuid.uuid4().hex[:8]
        JOBS[job_id] = {
            "id": job_id, 
            "status": "running", 
            "log": [], 
            "result": None,
            "shot": None, 
            "t0": time.time(), 
            "domain": domain
        }
        for old in list(JOBS.keys())[:-5]:
            del JOBS[old]
            
    threading.Thread(target=run_job, args=(job_id, domain, max_wait), daemon=True).start()
    return jsonify({"id": job_id, "status": "running"})


@app.route('/job', methods=['GET'])
def job_endpoint():
    job = JOBS.get(request.args.get('id', ''))
    if not job:
        return jsonify({"error": "Không tìm thấy tiến trình"}), 404
    return jsonify({
        "status": job["status"], 
        "elapsed": round(time.time() - job["t0"]),
        "log": job["log"], 
        "result": job["result"]
    })


@app.route('/shot', methods=['GET'])
def shot_endpoint():
    job = JOBS.get(request.args.get('id', ''))
    if not job or not job.get("shot"):
        return "chưa có ảnh", 404
    resp = Response(job["shot"], mimetype="image/jpeg")
    resp.headers['Cache-Control'] = 'no-store'
    return resp


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
