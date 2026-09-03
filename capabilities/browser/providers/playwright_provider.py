"""Playwright provider. The only file in AI-OS permitted to know a browser engine.

The session survives between CLI invocations: the browser is launched as its own process
with a debugging endpoint, and later operations attach to that endpoint. Without this a
"multi-step browser task" would mean a new browser per step, which is not a session.
"""
import json, os, socket, subprocess, time, urllib.request
from pathlib import Path


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def detect():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return False, f"playwright python package not importable: {e}"
    try:
        with sync_playwright() as pw:
            exe = pw.chromium.executable_path
        return (True, exe) if exe and Path(exe).exists() else (False, "browser binary missing")
    except Exception as e:
        return False, f"provider unusable: {e}"


def launch(profile_dir, port=None):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        exe = pw.chromium.executable_path
    port = port or _free_port()
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    args = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
            "--no-first-run", "--no-default-browser-check", "--headless=new",
            "--disable-gpu", "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    endpoint = None
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                endpoint = json.load(r).get("webSocketDebuggerUrl")
            if endpoint:
                break
        except Exception:
            time.sleep(0.2)
    if not endpoint:
        proc.terminate()
        raise RuntimeError("browser did not expose a debugging endpoint")
    return {"pid": proc.pid, "port": port, "endpoint": endpoint, "profile": str(profile_dir)}


class _Handle:
    def __init__(self, pw, browser, page):
        self.pw, self.browser, self.page = pw, browser, page

    def release(self):
        try:
            self.pw.stop()
        except Exception:
            pass


def connect(session):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{session['port']}")
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return _Handle(pw, browser, page)


def close(session):
    try:
        os.kill(int(session["pid"]), 15)
    except Exception:
        pass
    return {"closed": True}


def state(h):
    return {"url": h.page.url, "title": h.page.title()}


def navigate(h, url, timeout=30000):
    h.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    return {"url": h.page.url, "title": h.page.title()}


def read_text(h):
    return {"url": h.page.url, "title": h.page.title(),
            "text": h.page.inner_text("body")[:20000]}


def observe(h):
    els = h.page.eval_on_selector_all(
        "a,button,input,select,textarea,[role=button]",
        """els => els.slice(0,120).map(e => ({
             tag: e.tagName.toLowerCase(), type: e.type || null,
             name: e.name || null, id: e.id || null,
             text: (e.innerText || e.value || '').trim().slice(0,80),
             visible: !!(e.offsetWidth || e.offsetHeight)
           }))""")
    return {"url": h.page.url, "title": h.page.title(), "elements": els}


def extract(h, selector, attr=None):
    if attr:
        vals = h.page.eval_on_selector_all(
            selector, "(els,a) => els.map(e => e.getAttribute(a))", attr)
    else:
        vals = h.page.eval_on_selector_all(
            selector, "els => els.map(e => (e.innerText || e.value || '').trim())")
    return {"selector": selector, "count": len(vals), "values": vals[:200]}


def click(h, selector, timeout=15000):
    before = h.page.url
    h.page.click(selector, timeout=timeout)
    h.page.wait_for_timeout(300)
    return {"selector": selector, "url_before": before, "url": h.page.url}


def type_text(h, selector, text, clear=True):
    if clear:
        h.page.fill(selector, "", timeout=15000)
    h.page.type(selector, text, timeout=15000)
    return {"selector": selector, "typed": len(text),
            "value": h.page.input_value(selector, timeout=5000)}


def select(h, selector, value):
    h.page.select_option(selector, value, timeout=15000)
    return {"selector": selector, "value": h.page.input_value(selector, timeout=5000)}


def scroll(h, dy=600):
    h.page.mouse.wheel(0, dy)
    h.page.wait_for_timeout(150)
    y = h.page.evaluate("() => Math.round(window.scrollY)")
    return {"scrollY": y}


def wait_for(h, selector=None, url_contains=None, timeout=15000):
    if selector:
        h.page.wait_for_selector(selector, timeout=timeout)
    if url_contains:
        h.page.wait_for_url(f"**{url_contains}**", timeout=timeout)
    return {"url": h.page.url, "selector": selector, "url_contains": url_contains}


def upload(h, selector, paths):
    h.page.set_input_files(selector, paths, timeout=15000)
    names = h.page.eval_on_selector(
        selector, "e => Array.from(e.files || []).map(f => f.name)")
    return {"selector": selector, "attached": names}


def download(h, selector, dest, timeout=60000):
    with h.page.expect_download(timeout=timeout) as info:
        h.page.click(selector, timeout=timeout)
    d = info.value
    target = Path(dest) / d.suggested_filename
    target.parent.mkdir(parents=True, exist_ok=True)
    d.save_as(str(target))
    return {"selector": selector, "path": str(target),
            "size": target.stat().st_size if target.exists() else 0}


def submit(h, selector, timeout=20000):
    before = h.page.url
    h.page.click(selector, timeout=timeout)
    try:
        h.page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    h.page.wait_for_timeout(400)
    return {"selector": selector, "url_before": before, "url": h.page.url}
