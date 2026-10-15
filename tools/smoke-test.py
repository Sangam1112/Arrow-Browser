#!/usr/bin/env python3
"""Start an installed Arrow once, with a throw-away profile, and check the basics: the window opens, a page loads
and runs its script, Settings opens, and the bundled font and icons are in use. Needs a display (xvfb-run works).
.github/workflows/install-test.yml runs it on fresh Ubuntu, Debian and Fedora after installing a release package.

  tools/smoke-test.py [path to arrow_browser.py]      (default: the package's, /usr/share/arrow-browser)
"""
import importlib.util
import json
import os
import sys
import tempfile
import time

os.environ["HOME"] = tempfile.mkdtemp(prefix="arrow-smoke-")  # before the module reads its paths
path = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/arrow-browser/arrow_browser.py"
spec = importlib.util.spec_from_file_location("arrow_browser", path)
bb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bb)
import gi  # noqa: E402
gi.require_version("PangoCairo", "1.0")
from gi.repository import GLib, Gtk, PangoCairo  # noqa: E402

os.makedirs(bb.CONFIG_DIR, exist_ok=True)
with open(bb.CONFIG_FILE, "w") as f:
    json.dump({"first_run_greeted": True, "tracker_lists_enabled": False}, f)
bb.ArrowBrowserWindow.start_auto_git_update_check = lambda self: False
page = os.path.join(os.environ["HOME"], "smoke.html")
with open(page, "w") as f:
    f.write("<html><head><title>loaded</title></head><body><script>document.title = 'script ran'</script></body></html>")

win = bb.ArrowBrowserWindow(startup_urls=[GLib.filename_to_uri(page)])
win.show_all()


def wait(condition, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if condition():
            return True
        time.sleep(0.05)
    return False


checks = {"version": bb.APP_VERSION}
view = win.get_active_webview()
checks["page loads and runs its script"] = wait(lambda: (view.get_title() or "") == "script ran", 60)
dialog = win.build_settings_dialog("privacy")
dialog.show_all()
checks["Settings opens"] = wait(lambda: dialog.get_mapped(), 10)
dialog.destroy()
checks["bundled font registered"] = bool(bb.UI_FONT_FILE)
checks["font usable by the interface"] = "Lexend" in {f.get_name() for f in PangoCairo.FontMap.get_default().list_families()}
checks["line icons draw"] = bb.ui_icon("shield") is not None
print(json.dumps(checks, indent=2))
win.destroy()
sys.exit(0 if all(v for k, v in checks.items() if k != "version") else 1)
