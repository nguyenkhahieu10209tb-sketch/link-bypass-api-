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
                
                # Vô hiệu hóa cờ kiểm soát tự động hóa của trình duyệt
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
                        page.evaluate("""() => {
                            const btn = Array.from(document.querySelectorAll('a,button,div')).find(el => /lấy mã|mã km/i.test(el.innerText));
                            if (btn) btn.scrollIntoView({behavior: 'smooth', block: 'center'});
                        }""")
                        pause(0.5)
                        job["shot"] = page.screenshot(type="jpeg", quality=50)
                    except Exception:
                        pass

                # Giả lập thao tác lướt đọc văn bản tự nhiên để kích hoạt các script đếm giây ẩn
                def human_reading_scroll():
                    try:
                        page.evaluate("""() => {
                            window.scrollBy({top: window.innerHeight * 0.5, behavior: 'smooth'});
                        }""")
                        pause(1.2)
                        page.evaluate("""() => {
                            window.scrollBy({top: -window.innerHeight * 0.25, behavior: 'smooth'});
                        }""")
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
                        # Lọc kích thước thật để né các nút giả mạo, banner rác
                        clicked = page.evaluate("""() => {
                            const elements = Array.from(document.querySelectorAll('a, button, div, span, p'));
                            for (const el of elements) {
                                const t = (el.innerText || '').trim().toLowerCase();
                                if (t.includes('lấy mã') && el.offsetParent !== null) {
                                    const rect = el.getBoundingClientRect();
                                    if (rect.width > 25 && rect.height > 12) {
                                        el.scrollIntoView({behavior: 'smooth', block: 'center'});
                                        el.click();
                                        return true;
                                    }
                                }
                            }
                            return false;
                        }""")
                        if clicked:
                            pause(2)
                            return "JS_Click_Success"
                    except Exception as e:
                        log("Lỗi click JS: " + str(e)[:50])
                    return None

                def click_random_menu_link():
                    try:
                        clicked = page.evaluate("""() => {
                            const links = Array.from(document.querySelectorAll('a[href]'));
                            const keywords = ['giới thiệu', 'chính sách', 'quyền riêng tư', 'điều khoản', 'đăng ký', 'đăng nhập', 'nạp tiền', 'rút tiền', 'tải app', 'khuyến mãi'];
                            for (const kw of keywords) {
                                for (const a of links) {
                                    if (a.offsetParent !== null && (a.innerText || '').toLowerCase().includes(kw)) {
                                        a.scrollIntoView({behavior: 'smooth', block: 'center'});
                                        a.click();
                                        return kw;
                                    }
                                }
                            }
                            for (const a of links) {
                                if (a.offsetParent !== null && (a.getAttribute('href') || '').length > 1) {
                                    a.scrollIntoView({behavior: 'smooth', block: 'center'});
                                    a.click();
                                    return 'random_link';
                                }
                            }
                            return null;
                        }""")
                        if clicked:
                            log(f"Đã bấm vào trang bất kỳ: '{clicked}'")
                            pause(4)
                            return True
                    except Exception as e:
                        log("Lỗi click trang bất kỳ: " + str(e)[:80])
                    return False

                log("Bước 1: Mở trang đích: " + domain)
                page.goto("https://" + domain, timeout=30000,
                          wait_until="domcontentloaded",
                          referer="https://www.google.com/")
                pause(4)
                shot()
                
                deadline = time.time() + max_wait
                last_state = None
                step_phase = "PRE_CHECK"
                timer_start_v2 = 0
                code = None

                while time.time() < deadline:
                    txt = button_text() or ""
                    if txt != last_state:
                        log("Trạng thái: " + (txt if txt else "(đang đếm ngược)"))
                        last_state = txt
                        shot()
                        
                    # Quét mã đích bất cứ lúc nào xuất hiện
                    m = re.search(r'Mã KM:\s*([A-Za-z0-9]+)', txt, re.IGNORECASE)
                    if m:
                        code = m.group(1)
                        log("ĐÃ TÌM THẤY MÃ: " + code)
                        shot()
                        break
                        
                    low = txt.lower()

                    # Cửa ải 0: Kiểm tra sơ bộ trang chủ
                    if step_phase == "PRE_CHECK":
                        if "lấy mã" in low or "vui lòng chờ" in low:
                            step_phase = "SCROLL_TO_BOTTOM_1"
                        else:
                            log("Không thấy nút ở trang chủ, đang tìm bài viết/chuyên mục...")
                            click_random_menu_link()
                            step_phase = "SCROLL_TO_BOTTOM_1"
                        pause(2)

                    # Bước 2 & 3: Lướt xuống cuối, ấn LẤY MÃ lần 1
                    elif step_phase == "SCROLL_TO_BOTTOM_1":
                        log("Bước 2: Lướt xuống cuối trang...")
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        pause(2)
                        log("Bước 3: Ấn nút lấy mã lần 1...")
                        click_lay_ma()
                        step_phase = "WAIT_TIMER_1"
                        pause(3)

                    # Đợi đếm ngược đợt 1
                    elif step_phase == "WAIT_TIMER_1":
                        sec_match = re.search(r'(\d+)\s*(?:s|giây)', txt, re.IGNORECASE)
                        if sec_match:
                            wait_secs = int(sec_match.group(1))
                            log(f"Đang đợi đếm ngược vòng 1 ({wait_secs}s)...")
                            for _ in range(max(1, wait_secs // 3)):
                                human_reading_scroll()
                                pause(3)
                        else:
                            step_phase = "CHECK_NEXT_ACTION"

                    # Bước 4: Kiểm tra xem có bắt bấm link bất kỳ không
                    elif step_phase == "CHECK_NEXT_ACTION":
                        if "click vào link" in low or "vui lòng click" in low:
                            log("Bước 4: Bắt buộc ấn vô trang bất kỳ theo yêu cầu...")
                            click_random_menu_link()
                            step_phase = "SCROLL_TO_BOTTOM_2"
                        else:
                            step_phase = "SCROLL_TO_BOTTOM_2"
                        pause(2)

                    # Bước 5: Lướt xuống cuối ấn LẤY MÃ lần 2
                    elif step_phase == "SCROLL_TO_BOTTOM_2":
                        log("Bước 5: Lướt xuống cuối trang để lấy mã lần 2...")
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        pause(2)
                        log("Ấn nút lấy mã lần 2...")
                        click_lay_ma()
                        step_phase = "WAIT_TIMER_2"
                        timer_start_v2 = time.time() # Đánh dấu mốc bắt đầu vòng 2 chống treo
                        pause(3)

                    # Đợi đếm ngược đợt cuối (Có cơ chế chống treo cứng vòng 2)
                    elif step_phase == "WAIT_TIMER_2":
                        sec_match = re.search(r'(\d+)\s*(?:s|giây)', txt, re.IGNORECASE)
                        if sec_match:
                            wait_secs = int(sec_match.group(1))
                            log(f"Đang đợi đếm ngược vòng cuối ({wait_secs}s)...")
                            for _ in range(max(1, wait_secs // 3)):
                                human_reading_scroll()
                                pause(3)
                        else:
                            elapsed_v2 = time.time() - timer_start_v2
                            if elapsed_v2 < 65:
                                human_reading_scroll()
                                pause(3)
                            else:
                                log("Hết thời gian chờ vòng 2, tiến hành quét toàn trang lấy mã...")
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                pause(2)
                                # Quét sâu toàn bộ body text để tìm mã
                                code_found = page.evaluate("""() => {
                                    const bodyText = document.body.innerText;
                                    const match = bodyText.match(/Mã KM[:\\s]*([A-Za-z0-9]+)/i);
                                    return match ? match[1] : null;
                                }""")
                                if code_found:
                                    code = code_found
                                    log("ĐÃ TÌM THẤY MÃ (QUÉT TOÀN TRANG): " + code)
                                    shot()
                                    break
                                else:
                                    log("Đang ép làm mới cuộn trang để kích hoạt hiển thị mã...")
                                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                    pause(5)
                    else:
                        human_reading_scroll()
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
