import os
import re
import uuid
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


class Stop(Exception):
    """Dừng tiến trình có chủ đích, kèm lời giải thích hiện cho người dùng."""


# ---- Các đoạn JavaScript chạy trong trang đích ----

# Tìm nút "LẤY MÃ" SÂU NHẤT (nút thật ưu tiên nút L4M Lấy mã), không phải khung bao bên ngoài chứa chữ đó.
FIND_JS = """
const vis=e=>{const r=e.getBoundingClientRect();return e.offsetParent!==null&&r.width>25&&r.height>12};
const txt=e=>((e.innerText||e.value||'')+'').trim().toLowerCase();
const hit=[...document.querySelectorAll('a,button,[role=button],input[type=button],input[type=submit],img,div,span,p')]
  .filter(e=>{const t=txt(e);return vis(e)&&((t&&t.length<60&&/lấy mã|get code/.test(t))||(e.tagName==='IMG'&&/l4m|link4m|lay-?ma|get-?code/.test(((e.alt||'')+' '+(e.title||'')+' '+(e.src||'')).toLowerCase())))});
const el=hit.find(e=>!hit.some(o=>o!==e&&e.contains(o)))||null;
"""
CLICK_JS = "()=>{" + FIND_JS + "if(!el)return null;el.scrollIntoView({block:'center'});el.click();return el.tagName+': '+txt(el).slice(0,40)}"
SCROLL_JS = "()=>{" + FIND_JS + "if(el)el.scrollIntoView({block:'center'});return !!el}"

# Ưu tiên dòng có đếm ngược (vd 'Vui lòng chờ 60s'); không có thì lấy dòng ngắn nhất liên quan nút/lấy mã(ưu tiên) hoặc biểu tượng nút start(hình tam giác xoay ngang sang bên phải)
BTN_JS = r"""()=>{
  const re=/(Vui lòng chờ|Lấy mã sau|LẤY MÃ|lấy mã|Vui lòng click|Mã KM|L4M Lấy Mã|Code)/i,cd=/\b\d+\s*(?:s\b|giây)/i;
  let a=null,b=null;
  for(const el of document.querySelectorAll('a,button,div,span,p')){
    if(el.children.length>3)continue;
    const t=(el.innerText||'').trim();
    if(!t||t.length>=160||!re.test(t))continue;
    if(cd.test(t)){if(!a||t.length<a.length)a=t}else if(!b||t.length<b.length)b=t;
  }
  return a||b;}"""

# Đọc mã theo nhãn "Mã KM / Mã xác nhận / Mã nhận được / Code:".
READ_JS = r"""()=>{
  const t=document.body?document.body.innerText:'';
  const m=t.match(/(?:mã\s*km|mã\s*xác\s*nhận|mã\s*nhận\s*được|your\s*code)\s*[:：]?\s*([A-Za-z0-9]{4,15})\b|\bcode\s*[:：]\s*([A-Za-z0-9]{4,15})\b/i);
  return m?(m[1]||m[2]):null;}"""

# Bấm một link nội bộ ( đăng ký, đăng nhập, nạp, rút, tải app, link ngoài trang).
MENU_JS = r"""()=>{
  const bad=/đăng ký|đăng nhập|nạp|rút|register|login|deposit|withdraw|tải|download/i;
  const ok=a=>a.offsetParent!==null&&a.origin===location.origin&&a.href!==location.href&&!a.href.includes('#')&&!bad.test((a.innerText||'')+' '+a.href);
  const links=[...document.querySelectorAll('a[href]')].filter(ok);
  const keys=['giới thiệu','chính sách','quyền riêng tư','điều khoản','liên hệ','tin tức','bài viết'];
  for(const k of keys){const a=links.find(x=>(x.innerText||'').toLowerCase().includes(k));if(a){a.scrollIntoView({block:'center'});a.click();return k}}
  const a=links.find(x=>(x.getAttribute('href')||'').length>1);
  if(a){a.scrollIntoView({block:'center'});a.click();return 'link bất kỳ'}
  return null;}"""
# ---- end js ----


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

                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = window.chrome || { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN', 'vi', 'en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                """)

                page = context.new_page()
                hosts = {}

                def on_req(r):
                    h = urlparse(r.url).hostname or "?"
                    hosts[h] = hosts.get(h, 0) + 1

                page.on("request", on_req)

                def pause(sec):
                    page.wait_for_timeout(int(sec * 1000))
                    if job.get("cancel"):
                        raise Stop("Đã hủy theo yêu cầu.")

                def ev(js):
                    """Chạy JS ở trang chính rồi tới từng iframe; trả về kết quả có giá trị đầu tiên."""
                    for fr in page.frames:
                        try:
                            r = fr.evaluate(js)
                            if r:
                                return r
                        except Exception:
                            pass
                    return None

                def shot():
                    try:
                        ev(SCROLL_JS)
                        page.wait_for_timeout(400)
                        job["shot"] = page.screenshot(type="jpeg", quality=50)
                    except Exception:
                        pass

                def human_reading_scroll():
                    try:
                        page.evaluate("() => window.scrollBy({top: window.innerHeight * 0.5, behavior: 'smooth'})")
                        pause(1.2)
                        page.evaluate("() => window.scrollBy({top: -window.innerHeight * 0.25, behavior: 'smooth'})")
                    except Stop:
                        raise
                    except Exception:
                        pass

                def button_text():
                    return ev(BTN_JS)

                def read():
                    c = ev(READ_JS)
                    return c.strip() if c else None

                def click_btn(tries, gap=4):
                    """Tìm và bấm nút LẤY MÃ. Trả về mô tả nút đã bấm, hoặc None nếu không thấy."""
                    for _ in range(tries):
                        try:
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        except Exception:
                            pass
                        r = ev(CLICK_JS)
                        if r:
                            pause(2)
                            return r
                        pause(gap)
                    return None

                def click_menu_link():
                    try:
                        k = page.evaluate(MENU_JS)
                        if k:
                            log("Đã bấm vào trang phụ: '" + str(k) + "'")
                            pause(4)
                            return True
                    except Stop:
                        raise
                    except Exception as e:
                        if "destroyed" in str(e) or "navigat" in str(e):
                            log("Đã bấm vào một link, trang đang chuyển...")
                            pause(4)
                            return True
                        log("Lỗi bấm link phụ: " + str(e)[:80])
                    return False

                def click_link_and_return():
                    """Bấm một link trong trang rồi quay lại đúng trang cũ (bước 5 của Link4m)."""
                    origin = page.url
                    if not click_menu_link():
                        log("Không tìm được link phù hợp để bấm.")
                        return False
                    for extra in list(context.pages):
                        if extra != page:
                            try:
                                extra.close()
                            except Exception:
                                pass
                    if page.url != origin:
                        log("Đang quay lại trang cũ...")
                        try:
                            page.go_back(wait_until="domcontentloaded", timeout=20000)
                        except Exception as e:
                            log("Lỗi quay lại: " + str(e)[:80])
                            page.goto(origin, timeout=30000, wait_until="domcontentloaded")
                        pause(4)
                    return True

                def diag():
                    """Ghi vài số liệu thật của trang để biết vì sao không thấy nút / mã."""
                    try:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(500)
                        i = page.evaluate("""() => ({
                            t: document.title || '',
                            h: document.body ? document.body.scrollHeight : 0,
                            n: ((document.body ? document.body.innerText : '').toLowerCase().split('lấy mã').length - 1),
                            f: document.querySelectorAll('iframe').length,
                            x: [...document.querySelectorAll('body *')].filter(e=>{const t=(e.innerText||'').trim();return t&&t.length<120&&getComputedStyle(e).position==='fixed'}).slice(0,4).map(e=>e.innerText.trim().split(String.fromCharCode(10)).join(' ').slice(0,60)),
                            c: [...document.querySelectorAll('img,div,a,button')].filter(e=>/l4m|link4m|get-?code|lay-?ma/i.test((e.id||'')+' '+(typeof e.className==='string'?e.className:'')+' '+(e.alt||'')+' '+(e.src||''))).slice(0,6).map(e=>e.tagName+'#'+(e.id||'')+'.'+(typeof e.className==='string'?e.className:'').slice(0,40)+' '+Math.round(e.getBoundingClientRect().width)+'x'+Math.round(e.getBoundingClientRect().height))
                        })""")
                        log("Chẩn đoán: tiêu đề='%s' | cao=%spx | chữ 'lấy mã' xuất hiện %s lần | iframe=%s"
                            % (i["t"][:40], i["h"], i["n"], i["f"]))
                        log("Địa chỉ hiện tại: " + page.url[:100])
                        log("Phần tử nghi của Link4m: " + (" ; ".join(i["c"]) or "không có"))
                        log("Khung nổi trên trang: " + (" | ".join(i["x"]) or "không có"))
                        ext = sorted(h for h in hosts if h and h != domain and not h.endswith("." + domain))
                        hot = [h for h in ext if "link4m" in h or "l4m" in h]
                        log("Yêu cầu tới link4m: " + (", ".join(hot) or "KHÔNG có yêu cầu nào"))
                        txt = ", ".join(ext)
                        for k in range(0, min(len(txt), 840), 280):
                            log("Tên miền ngoài: " + txt[k:k + 280])
                    except Exception as e:
                        log("Chẩn đoán lỗi: " + str(e)[:80])

                def countdown(cap):
                    """Đợi đếm ngược,sao chép và thoát ngay khi thấy mã. Không đợi vô ích nếu không có đếm ngược."""
                    t_start = time.time()
                    seen = False
                    quiet = 0
                    last = None
                    while time.time() - t_start < cap and time.time() < deadline:
                        c = read()
                        if c:
                            return c
                        txt = button_text() or ""
                        if txt != last:
                            log("Trạng thái: " + (txt or "(không thấy chữ nào)"))
                            last = txt
                            shot()
                        if re.search(r'\b\d+\s*(?:s\b|giây)', txt, re.IGNORECASE):
                            seen = True
                            quiet = 0
                        else:
                            quiet += 1
                        if (seen and quiet >= 2) or (not seen and time.time() - t_start > 20):
                            break
                        human_reading_scroll()
                        pause(3)
                    return read()

                # ---------------- Luồng chính ----------------
                log("Bước 1: Mở trang đích: " + domain)
                page.goto("https://" + domain, timeout=30000,
                          wait_until="domcontentloaded",
                          referer="https://www.google.com/")
                pause(4)
                shot()

                deadline = time.time() + max_wait
                code = read()

                if not code:
                    log("Bước 2: Tìm nút LẤY MÃ (lần 1)...")
                    hit = click_btn(5)
                    if not hit:
                        diag()
                        shot()
                        raise Stop("Trang đích không hiện nút LẤY MÃ cho máy chủ (xem dòng chẩn đoán). "
                                   "Có thể trang chỉ hiện nút cho thiết bị đã mở link rút gọn.")
                    log("Đã bấm: " + hit)
                    code = countdown(60)

                    if not code:
                        log("Bước 3: Bấm một link trong trang rồi quay lại vị trí cũ...")
                        click_link_and_return()
                        log("Bước 4: Tìm nút LẤY MÃ (lần 2)...")
                        hit = click_btn(4)
                        if hit:
                            log("Đã bấm: " + hit)
                        else:
                            log("Không thấy nút lần 2, thử đợi mã tự hiện...")
                        code = countdown(140)

                    tries = 0
                    while not code and tries < 3 and time.time() < deadline:
                        tries += 1
                        log("Chưa thấy mã, quét lại (%d/3)..." % tries)
                        ev(CLICK_JS)
                        pause(8)
                        code = read()

                if code:
                    log("ĐÃ CÓ MÃ: " + code)
                else:
                    diag()
                    log("Hết thời gian chờ mà chưa thấy mã (đã dùng " + str(round(time.time() - job["t0"])) + "s).")
                shot()
                job["result"] = {"code": code, "url": page.url}
            finally:
                browser.close()
    except Stop as e:
        job["result"] = {"code": None, "exception": str(e)}
        log(str(e))
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
            "cancel": False,
            "t0": time.time(),
            "domain": domain
        }
        for old in list(JOBS.keys())[:-5]:
            del JOBS[old]

    threading.Thread(target=run_job, args=(job_id, domain, max_wait), daemon=True).start()
    return jsonify({"id": job_id, "status": "running"})


@app.route('/cancel', methods=['GET'])
def cancel_endpoint():
    job = JOBS.get(request.args.get('id', ''))
    if job and job["status"] == "running":
        job["cancel"] = True
    return jsonify({"ok": True})


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
