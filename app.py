import os
import re
import gc
import sys
import time
import uuid
import signal
import resource
import threading
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from playwright.sync_api import sync_playwright

app = Flask(__name__)
CORS(app)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--disable-software-rasterizer',
    '--disable-extensions',
    '--disable-blink-features=AutomationControlled',
    '--disable-features=IsolateOrigins,site-per-process',
    '--window-size=1280,800',
    '--renderer-process-limit=1',
    '--js-flags=--max-old-space-size=192',
]

MEMORY_LIMIT_MB = 410.0
MEMORY_HARD_ABORT_MB = 470.0
SCREENSHOT_MIN_INTERVAL = 3.0
MUTATION_DEBOUNCE_MS = 1200
NO_SEEN_LIMIT_SEC = 45.0
DEADLINE_BUFFER_SEC = 50.0
PREEMPTION_WAIT_SEC = 3.0
MEMORY_CHECK_CACHE_SEC = 0.3

JOBS = {}
JOB_LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hell-worker")

_last_valid_rss = 45.0

def current_rss_mb():
    global _last_valid_rss
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    parts = line.split()
                    if len(parts) >= 2:
                        val = int(parts[1]) / 1024.0
                        if val > 0:
                            _last_valid_rss = val
                            return val
    except Exception:
        pass

    try:
        with open('/proc/self/stat', 'r') as f:
            data = f.read().split()
            if len(data) > 23:
                rss_pages = int(data[23])
                page_size = os.sysconf('SC_PAGE_SIZE')
                val = (rss_pages * page_size) / (1024.0 * 1024.0)
                if val > 0:
                    _last_valid_rss = val
                    return val
    except Exception:
        pass

    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if usage > 0:
            val = usage / (1024.0 * 1024.0) if sys.platform == 'darwin' else usage / 1024.0
            if val > 0:
                _last_valid_rss = val
                return val
    except Exception:
        pass

    return _last_valid_rss


def sweep_zombie_chromium():
    """Dọn dẹp tiến trình Chromium mồ côi hoàn toàn bằng Python thuần quét thư mục /proc (Không cần pgrep)"""
    self_pid = os.getpid()
    try:
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid == self_pid:
                continue
            try:
                cmdline_path = f"/proc/{pid}/cmdline"
                if os.path.exists(cmdline_path):
                    with open(cmdline_path, 'rb') as f:
                        cmdline = f.read().decode('utf-8', errors='ignore').lower()
                        if 'chromium' in cmdline or 'chrome' in cmdline or 'chrome-sandbox' in cmdline:
                            os.kill(pid, signal.SIGKILL)
            except (PermissionError, ProcessLookupError, OSError):
                continue
    except Exception:
        pass


class JobContext:
    def __init__(self, job_id, domain):
        self.job_id = job_id
        self.domain = domain
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self.done_event = threading.Event()
        self.cancelled = False
        self.memory_emergency = False
        self.t0 = time.time()
        self.absolute_deadline = self.t0 + DEADLINE_BUFFER_SEC
        self.last_shot_at = 0.0
        self.shot_buffer = None
        self.result = None
        self.log_lines = []
        self._last_mem_check = 0.0
        self._last_mem_mb = 0.0

    def log(self, msg):
        line = str(int(time.time() - self.t0)) + "s | " + str(msg)[:300]
        with self._lock:
            self.log_lines.append(line)
            if len(self.log_lines) > 80:
                del self.log_lines[:-80]

    def cancel(self):
        with self._lock:
            self.cancelled = True
        self._cancel_event.set()

    def is_cancelled(self):
        return self._cancel_event.is_set()

    def check_memory(self):
        now = time.time()
        with self._lock:
            if now - self._last_mem_check < MEMORY_CHECK_CACHE_SEC:
                return self._last_mem_mb > MEMORY_LIMIT_MB
        try:
            mb = current_rss_mb()
        except Exception:
            mb = _last_valid_rss
        with self._lock:
            self._last_mem_check = now
            self._last_mem_mb = mb
            if mb > MEMORY_LIMIT_MB:
                self.memory_emergency = True
                return True
        return False

    def mark_done(self):
        self.done_event.set()

    def wait_done(self, timeout):
        return self.done_event.wait(timeout)

    def is_running(self):
        return not self.done_event.is_set()

    def snapshot(self):
        with self._lock:
            return {
                "status": "done" if self.done_event.is_set() else "running",
                "elapsed": round(time.time() - self.t0),
                "log": list(self.log_lines),
                "result": self.result,
                "rss_mb": round(self._last_mem_mb, 1),
                "memory_emergency": self.memory_emergency,
                "cancelled": self.cancelled,
            }


INIT_JS = r"""
(function () {
    if (window.__l4m_initialized) return;
    window.__l4m_initialized = true;

    // Capped Rolling Buffer cho Shadow Roots để chống rò rỉ V8 Heap (Max 25 items)
    window.__l4m_shadow_roots = [];
    try {
        const origAttach = Element.prototype.attachShadow;
        Element.prototype.attachShadow = function (init) {
            const root = origAttach.apply(this, arguments);
            try {
                if (init && init.mode === 'closed') {
                    window.__l4m_shadow_roots.push(root);
                    if (window.__l4m_shadow_roots.length > 25) {
                        window.__l4m_shadow_roots.shift();
                    }
                }
            } catch (e) {}
            return root;
        };
    } catch (e) {}

    window.__l4m_last_mutation = Date.now();
    window.__l4m_dirty = true;

    const DEBOUNCE_MS = 1200;
    const OBS_OPTS = {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
        attributeFilter: ['class', 'style', 'id', 'disabled', 'href', 'value']
    };

    const observed = new WeakSet();
    const visitedDocs = new WeakSet();

    function markDirty() {
        window.__l4m_last_mutation = Date.now();
        window.__l4m_dirty = true;
    }

    function observeRoot(root) {
        if (!root) return;
        try {
            if (observed.has(root)) return;
            observed.add(root);
        } catch (e) { return; }
        try {
            const obs = new MutationObserver(markDirty);
            obs.observe(root, OBS_OPTS);
        } catch (e) {}
    }

    function traverse(root, depth) {
        if (!root || depth > 8) return;
        try {
            if (visitedDocs.has(root)) return;
            visitedDocs.add(root);
        } catch (e) {}
        observeRoot(root);
        try {
            if (root.querySelectorAll) {
                const elems = root.querySelectorAll('*');
                for (let i = 0; i < elems.length; i++) {
                    const el = elems[i];
                    if (el.shadowRoot) {
                        try { traverse(el.shadowRoot, depth + 1); } catch (e) {}
                    }
                }
                const iframes = root.querySelectorAll('iframe');
                for (let i = 0; i < iframes.length; i++) {
                    try {
                        const d = iframes[i].contentDocument;
                        if (d) traverse(d, depth + 1);
                    } catch (e) {}
                }
            }
        } catch (e) {}
    }

    function start() {
        traverse(document, 0);
        try {
            for (let i = 0; i < window.__l4m_shadow_roots.length; i++) {
                traverse(window.__l4m_shadow_roots[i], 1);
            }
        } catch (e) {}
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

    window.__l4m_consume_screenshot_flag = function () {
        if (window.__l4m_dirty && (Date.now() - window.__l4m_last_mutation) >= DEBOUNCE_MS) {
            window.__l4m_dirty = false;
            return true;
        }
        return false;
    };
})();
"""

DEEP_QUERY_JS = r"""
const deepQuery = (sel) => {
    const out = [];
    const seen = new Set();
    const walk = (root) => {
        if (!root || seen.has(root)) return;
        seen.add(root);
        try {
            if (root.querySelectorAll) {
                const nodes = root.querySelectorAll(sel);
                for (let i = 0; i < nodes.length; i++) out.push(nodes[i]);
            }
        } catch (e) {}
        try {
            if (root.querySelectorAll) {
                const all = root.querySelectorAll('*');
                for (let i = 0; i < all.length; i++) {
                    if (all[i].shadowRoot) walk(all[i].shadowRoot);
                }
            }
        } catch (e) {}
    };
    walk(document);
    try {
        const roots = window.__l4m_shadow_roots || [];
        for (let i = 0; i < roots.length; i++) walk(roots[i]);
    } catch (e) {}
    return out;
};
"""

FIND_JS = (
    DEEP_QUERY_JS +
    r"""
const vis = (e) => {
    try {
        const r = e.getBoundingClientRect();
        return e.offsetParent !== null && r.width > 15 && r.height > 8;
    } catch (err) { return false; }
};
const txt = (e) => ((e.innerText || e.value || '') + '').trim().toLowerCase();

let hit = deepQuery('a, button, [role=button], input[type=button], input[type=submit], div, span, p')
    .filter((e) => {
        const t = txt(e);
        return vis(e) && t && t.length < 60 && /lấy mã|get code|tiếp tục|l4m lấy mã/.test(t);
    });
let el = hit.find((e) => !hit.some((o) => o !== e && e.contains(o))) || null;

if (!el) {
    const l4mElements = deepQuery('a, button, [role=button], div, span')
        .filter((e) => {
            if (!vis(e)) return false;
            try {
                if (['IMG', 'SVG', 'IFRAME'].includes(e.tagName)) return false;
            } catch (err) { return false; }
            let htmlContent = '';
            try { htmlContent = (e.outerHTML || '').toLowerCase(); } catch (err) {}
            return /l4m|link4m/.test(htmlContent);
        });
    el = l4mElements.find((e) => !l4mElements.some((o) => o !== e && e.contains(o))) || null;
}
el;
"""
)

CLICK_JS = (
    "()=>{" + FIND_JS +
    "if(!el)return null;"
    "try{el.scrollIntoView({block:'center'});el.click();}catch(e){return null;}"
    "return el.tagName+': '+txt(el).slice(0,40);}"
)

SCROLL_JS = (
    "()=>{" + FIND_JS +
    "if(!el)return false;"
    "try{el.scrollIntoView({block:'center'});return true;}catch(e){return false;}}"
)

BTN_JS = (
    "()=>{" + DEEP_QUERY_JS +
    r"""
    const re = /(Vui lòng chờ|Lấy mã sau|LẤY MÃ|lấy mã|Vui lòng click|Mã KM|L4M Lấy Mã|Code)/i;
    const cd = /\b\d+\s*(?:s\b|giây)/i;
    let a = null, b = null;
    const candidates = deepQuery('a,button,div,span,p');
    for (let i = 0; i < candidates.length; i++) {
        const el = candidates[i];
        try {
            if (el.children.length > 3) continue;
            const t = (el.innerText || '').trim();
            if (!t || t.length >= 160 || !re.test(t)) continue;
            if (cd.test(t)) {
                if (!a || t.length < a.length) a = t;
            } else if (!b || t.length < b.length) b = t;
        } catch (e) {}
    }
    return a || b;
}"""
)

READ_JS = (
    "()=>{" + DEEP_QUERY_JS +
    r"""
    const trash = /lấy mã|vui lòng|chờ|please|error|loading|barcode|đang tải|quảng cáo|wait/i;
    const selectors = ['#code', '.code', '.token', '.result-code', '[id*="code"]', '[class*="code"]'];
    for (let s = 0; s < selectors.length; s++) {
        const nodes = deepQuery(selectors[s]);
        for (let i = 0; i < nodes.length; i++) {
            try {
                const val = (nodes[i].innerText || nodes[i].value || '').trim();
                if (val.length >= 4 && val.length <= 25 && /^[A-Za-z0-9\-_]+$/.test(val) && !trash.test(val)) {
                    return val;
                }
            } catch (e) {}
        }
    }
    let bodyText = '';
    try { bodyText = document.body ? document.body.innerText : ''; } catch (e) { bodyText = ''; }
    const m = bodyText.match(/(?:mã\s*km|mã\s*xác\s*nhận|mã\s*nhận\s*được|your\s*code|code)\s*[:：]\s*([A-Za-z0-9\-_]{4,25})\b/i);
    if (m && !trash.test(m[1])) return m[1];
    return null;
}"""
)

MENU_JS = (
    "()=>{" + DEEP_QUERY_JS +
    r"""
    const bad = /đăng ký|đăng nhập|nạp|rút|register|login|deposit|withdraw|tải|download/i;
    const ok = (a) => {
        try {
            return a.offsetParent !== null
                && a.origin === location.origin
                && a.href !== location.href
                && !a.href.includes('#')
                && !bad.test((a.innerText || '') + ' ' + a.href);
        } catch (e) { return false; }
    };
    const links = deepQuery('a[href]').filter(ok);
    const keys = ['giới thiệu', 'chính sách', 'quyền riêng tư', 'điều khoản', 'liên hệ', 'tin tức', 'bài viết'];
    for (let k = 0; k < keys.length; k++) {
        for (let i = 0; i < links.length; i++) {
            try {
                if (((links[i].innerText || '').toLowerCase()).includes(keys[k])) {
                    links[i].scrollIntoView({block: 'center'});
                    links[i].click();
                    return keys[k];
                }
            } catch (e) {}
        }
    }
    return null;
}"""
)


def pause(ctx, seconds):
    """Non-blocking preemption sleep: ngắt ngay lập tức khi có lệnh cancel/memory emergency mà không kẹt luồng"""
    if ctx.is_cancelled():
        return False
    slept = 0.0
    chunk = 0.2
    while slept < seconds:
        if ctx.is_cancelled() or ctx.memory_emergency:
            return False
        time.sleep(chunk)
        slept += chunk
    return not ctx.is_cancelled()


def evaluate_in_frames(page, js):
    try:
        frames = page.frames
    except Exception:
        return None
    for fr in frames:
        try:
            r = fr.evaluate(js)
            if r:
                return r
        except Exception:
            continue
    return None


def read_code(page):
    try:
        v = evaluate_in_frames(page, READ_JS)
        if v:
            return str(v).strip()
    except Exception:
        pass
    return None


def button_text(page):
    try:
        return evaluate_in_frames(page, BTN_JS)
    except Exception:
        return None


def consume_screenshot_flag(page):
    try:
        frames = page.frames
    except Exception:
        return False
    for fr in frames:
        try:
            r = fr.evaluate("() => (window.__l4m_consume_screenshot_flag && window.__l4m_consume_screenshot_flag()) || false")
            if r:
                return True
        except Exception:
            continue
    return False


def maybe_screenshot(ctx, page, force=False):
    now = time.time()
    with ctx._lock:
        if not force and (now - ctx.last_shot_at) < SCREENSHOT_MIN_INTERVAL:
            return
    if not force:
        if not consume_screenshot_flag(page):
            return
    try:
        evaluate_in_frames(page, SCROLL_JS)
        page.wait_for_timeout(200)
        img = page.screenshot(type='jpeg', quality=40)
        with ctx._lock:
            ctx.last_shot_at = time.time()
            ctx.shot_buffer = img
    except Exception:
        pass


def safe_url(page):
    try:
        return page.url
    except Exception:
        return ""


def should_stop(ctx):
    if ctx.is_cancelled():
        return True
    if ctx.memory_emergency:
        return True
    if time.time() > ctx.absolute_deadline:
        return True
    if ctx.check_memory():
        return True
    return False


def navigate(ctx, page, domain):
    if should_stop(ctx):
        return False
    try:
        page.goto("https://" + domain, timeout=35000,
                  wait_until="domcontentloaded",
                  referer="https://www.google.com/")
        return True
    except Exception as e:
        ctx.log("Lỗi mở trang: " + str(e)[:200])
        return False


def human_reading_scroll(ctx, page):
    if ctx.is_cancelled():
        return
    try:
        page.evaluate("() => window.scrollBy({top: window.innerHeight * 0.5, behavior: 'smooth'})")
    except Exception:
        return
    pause(ctx, 1.0)


def click_button(ctx, page, tries, gap):
    for i in range(tries):
        if should_stop(ctx):
            return None
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        r = evaluate_in_frames(page, CLICK_JS)
        if r:
            if not pause(ctx, 1.5):
                return None
            return r
        ctx.log("Không thấy nút, thử lại (%d/%d)" % (i + 1, tries))
        if not pause(ctx, gap):
            return None
    return None


def countdown_for_code(ctx, page, cap):
    t_start = time.time()
    seen = False
    quiet = 0
    last = None
    while (time.time() - t_start) < cap and time.time() < ctx.absolute_deadline:
        if ctx.is_cancelled() or ctx.check_memory():
            return None
        c = read_code(page)
        if c:
            return c
        txt = button_text(page) or ""
        if txt != last:
            ctx.log("Trạng thái: " + (txt if txt else "(không thấy chữ nào)"))
            last = txt
            maybe_screenshot(ctx, page)
        if re.search(r'\b\d+\s*(?:s\b|giây)', txt, re.IGNORECASE):
            seen = True
            quiet = 0
        else:
            quiet += 1
        if seen and quiet >= 2:
            break
        if (not seen) and (time.time() - t_start) > NO_SEEN_LIMIT_SEC:
            break
        human_reading_scroll(ctx, page)
        if not pause(ctx, 2.5):
            return None
    return read_code(page)


def click_menu_link(ctx, page):
    if should_stop(ctx):
        return False
    try:
        k = evaluate_in_frames(page, MENU_JS)
        if k:
            ctx.log("Đã bấm vào trang phụ: '" + str(k) + "'")
            pause(ctx, 3)
            return True
    except Exception as e:
        ctx.log("Lỗi bấm link phụ: " + str(e)[:80])
    return False


def diag(ctx, page):
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(400)
        info = page.evaluate("""() => ({
            t: document.title || '',
            h: document.body ? document.body.scrollHeight : 0,
            f: document.querySelectorAll('iframe').length
        })""")
        ctx.log("Chẩn đoán: tiêu đề='%s' | cao=%spx | iframe=%s" % (
            str(info["t"])[:40], info["h"], info["f"]))
        ctx.log("Địa chỉ hiện tại: " + safe_url(page)[:100])
    except Exception as e:
        ctx.log("Chẩn đoán lỗi: " + str(e)[:80])


def worker(job_id, domain, max_wait):
    with JOB_LOCK:
        ctx = JOBS.get(job_id)
    if ctx is None:
        return

    ctx.absolute_deadline = ctx.t0 + float(max_wait) + DEADLINE_BUFFER_SEC
    browser = None
    context = None

    try:
        sweep_zombie_chromium()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=BROWSER_ARGS)

            try:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    locale="vi-VN",
                    timezone_id="Asia/Ho_Chi_Minh",
                    device_scale_factor=1,
                    has_touch=False,
                    is_mobile=False,
                    extra_http_headers={
                        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                        "Sec-Ch-Ua-Platform": '"Windows"'
                    },
                )

                # 🔴 Chặn tài nguyên hung hãn tối đa để tiết kiệm RAM (Images, Fonts, Media, Stylesheets không thiết yếu)
                context.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot,mp4,webm,avi,mkv,mp3,wav,ogg,flac}",
                    lambda route: route.abort()
                )

                context.add_init_script(INIT_JS)
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = window.chrome || { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN', 'vi', 'en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'vendor', {get: () => 'Google Inc.'});
                """)

                page = context.new_page()
                primary_ref = {"page": page}

                page.on("dialog", lambda dialog: dialog.dismiss())
                context.on("page", lambda popup: popup.close() if primary_ref["page"] and popup is not primary_ref["page"] else None)

                ctx.log("Bước 1: Mở trang đích: " + domain)
                if not navigate(ctx, page, domain):
                    ctx.log("Dừng trước khi tải xong.")
                    return

                if not pause(ctx, 3):
                    ctx.log("Huỷ trong lúc chờ trang tải.")
                    return
                if ctx.check_memory():
                    ctx.log("Áp lực RAM sau khi mở trang.")
                    return
                maybe_screenshot(ctx, page, force=True)

                code = read_code(page)

                if not code:
                    ctx.log("Bước 2: Tìm nút LẤY MÃ (lần 1)...")
                    status, code = attempt_get_code(ctx, page, cap=50, tries=4)
                    if status == "stopped":
                        return
                    if status == "no_button":
                        diag(ctx, page)
                        maybe_screenshot(ctx, page, force=True)
                        with ctx._lock:
                            if ctx.result is None:
                                ctx.result = {"code": None, "exception": "no_button", "url": safe_url(page)}
                        return

                    if not code:
                        ctx.log("Bước 3: Bấm link phụ trong trang...")
                        click_menu_link(ctx, page)
                        if should_stop(ctx):
                            return
                        ctx.log("Bước 4: Tìm nút LẤY MÃ (lần 2)...")
                        status, code = attempt_get_code(ctx, page, cap=120, tries=3)
                        if status == "stopped":
                            return

                    tries = 0
                    while (not code) and tries < 3 and time.time() < ctx.absolute_deadline:
                        if should_stop(ctx):
                            break
                        tries += 1
                        ctx.log("Chưa thấy mã, quét lại (%d/3)..." % tries)
                        evaluate_in_frames(page, CLICK_JS)
                        if not pause(ctx, 6):
                            break
                        code = read_code(page)

                if code:
                    ctx.log("ĐÃ CÓ MÃ: " + code)
                else:
                    diag(ctx, page)
                    ctx.log("Hết thời gian chờ mà chưa thấy mã.")

                maybe_screenshot(ctx, page, force=True)

                with ctx._lock:
                    ctx.result = {"code": code, "url": safe_url(page)}
            except Exception as e:
                ctx.log("LỖI CHÍNH: " + str(e)[:200])
                with ctx._lock:
                    if ctx.result is None:
                        ctx.result = {"code": None, "exception": str(e)[:500]}
            finally:
                try:
                    if context:
                        context.close()
                except Exception:
                    pass
                try:
                    if browser:
                        browser.close()
                except Exception:
                    pass
    except Exception as e:
        ctx.log("LỖI KHỞI TẠO: " + str(e)[:200])
        with ctx._lock:
            if ctx.result is None:
                ctx.result = {"code": None, "exception": str(e)[:500]}
    finally:
        sweep_zombie_chromium()
        try:
            gc.collect(2)
        except Exception:
            pass
        if ctx.memory_emergency:
            with ctx._lock:
                if ctx.result is None:
                    ctx.result = {"code": None, "exception": "memory_emergency", "recovered": True}
                elif isinstance(ctx.result, dict):
                    ctx.result.setdefault("recovered", True)
        if ctx.is_cancelled():
            with ctx._lock:
                if ctx.result is None:
                    ctx.result = {"code": None, "exception": "cancelled"}
                elif isinstance(ctx.result, dict):
                    ctx.result.setdefault("cancelled", True)
        ctx.log("Hoàn tất | RSS=" + str(round(current_rss_mb(), 1)) + "MB")
        ctx.mark_done()


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "online", "rss_mb": round(current_rss_mb(), 1)})


@app.route('/getcode', methods=['GET', 'OPTIONS'])
def getcode_endpoint():
    if request.method == 'OPTIONS':
        return '', 204

    current_mem = current_rss_mb()
    
    # 🔴 Adaptive Gate: Từ chối cứng lập tức khi RAM vượt ngưỡng nguy hiểm
    if current_mem > MEMORY_HARD_ABORT_MB:
        return jsonify({
            "error": "Server under critical memory pressure. Please retry later.",
            "rss_mb": round(current_mem, 1)
        }), 530

    domain = (request.args.get('domain') or '').strip()
    domain = domain.replace('https://', '').replace('http://', '').split('/')[0]
    if not domain:
        return jsonify({"error": "Thiếu tham số domain"}), 400

    try:
        max_wait = max(30, min(500, int(request.args.get('wait', 420))))
    except ValueError:
        max_wait = 420

    obsolete_ctx = None
    job_id = None

    with JOB_LOCK:
        if current_mem > MEMORY_LIMIT_MB:
            for jid, jctx in list(JOBS.items()):
                if jctx.is_running():
                    obsolete_ctx = jctx
                    jctx.cancel()
                    break

        for jid, jctx in list(JOBS.items()):
            if jctx.is_running() and jctx.domain == domain:
                return jsonify({"id": jid, "reused": True})

        job_id = uuid.uuid4().hex[:8]
        new_ctx = JobContext(job_id=job_id, domain=domain)
        JOBS[job_id] = new_ctx

        done_ids = [jid for jid, jctx in JOBS.items() if jctx.done_event.is_set()]
        while len(JOBS) > 4 and done_ids:
            del JOBS[done_ids.pop(0)]

    if obsolete_ctx is not None:
        obsolete_ctx.wait_done(timeout=PREEMPTION_WAIT_SEC)

    EXECUTOR.submit(worker, job_id, domain, max_wait)
    return jsonify({"id": job_id, "status": "running", "rss_mb": round(current_mem, 1)})


@app.route('/cancel', methods=['GET'])
def cancel_endpoint():
    with JOB_LOCK:
        job = JOBS.get(request.args.get('id', ''))
    if job is not None:
        job.cancel()
    return jsonify({"ok": True})


@app.route('/job', methods=['GET'])
def job_endpoint():
    with JOB_LOCK:
        job = JOBS.get(request.args.get('id', ''))
    if not job:
        return jsonify({"error": "Không tìm thấy tiến trình"}), 404
    return jsonify(job.snapshot())


@app.route('/shot', methods=['GET'])
def shot_endpoint():
    with JOB_LOCK:
        job = JOBS.get(request.args.get('id', ''))
    if not job:
        return jsonify({"error": "Không tìm thấy tiến trình"}), 404
    with job._lock:
        img = job.shot_buffer
    if not img:
        return jsonify({"error": "chưa có ảnh"}), 404
    resp = Response(img, mimetype="image/jpeg")
    resp.headers['Cache-Control'] = 'no-store'
    return resp


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
