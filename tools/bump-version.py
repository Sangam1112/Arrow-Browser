#!/usr/bin/env python3
"""Bump the release version everywhere in one go.

  tools/bump-version.py 1.4.1 "One-line summary of the changes"

Updates package.json, arrow_browser.py (header + APP_VERSION), the README
(badge and install examples), CHANGELOG.md, the RPM changelog and the Flathub
store page (flatpak/*.metainfo.xml). The build
scripts read the version from package.json, so nothing else needs editing.
Run the build scripts afterwards: they refresh the checksum and sign the release.
"""
import datetime
import html
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FLATPAK_ID = "io.github.Sangam1112.Arrow-Browser"


def path(name):
    return os.path.join(ROOT, name)


def read(name):
    with open(path(name), encoding="utf-8") as f:
        return f.read()


def write(name, text):
    with open(path(name), "w", encoding="utf-8") as f:
        f.write(text)


def main():
    if len(sys.argv) != 3 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit(__doc__)
    new, summary = sys.argv[1], sys.argv[2].strip()
    pkg = json.loads(read("package.json"))
    old = pkg["version"]
    if new == old:
        sys.exit(f"Already at {old}")

    pkg["version"] = new
    write("package.json", json.dumps(pkg, indent=2) + "\n")

    py = read("arrow_browser.py")
    py = py.replace(f"Arrow Browser v{old} - ", f"Arrow Browser v{new} - ", 1)
    py = py.replace(f'APP_VERSION = "{old}"', f'APP_VERSION = "{new}"', 1)
    write("arrow_browser.py", py)

    # Only the install commands carry a version; a blanket replace would also rewrite
    # true historical statements such as "supported since 1.4.2".
    write("README.md", re.sub(rf"^VERSION={re.escape(old)}$", f"VERSION={new}", read("README.md"), flags=re.M))

    now = datetime.datetime.now()
    rpm = read("build-rpm.sh")
    entry = f"* {now.strftime('%a %b %d %Y')} Arrow Browser Developer <Sangam1112@users.noreply.github.com> - {new}-1\n- {summary}\n"
    rpm = rpm.replace("%changelog\n", "%changelog\n" + entry, 1)
    write("build-rpm.sh", rpm)

    log = read("CHANGELOG.md")
    section = f"## [{new}] - {now.strftime('%Y-%m-%d')}\n\n- {summary}\n\n"
    first = re.search(r"^## ", log, re.M)
    write("CHANGELOG.md", log[:first.start()] + section + log[first.start():] if first else log + "\n" + section)

    # The store page (Flathub, GNOME Software, Discover) shows each release's notes.
    metainfo = f"flatpak/{FLATPAK_ID}.metainfo.xml"
    release = (f'    <release version="{new}" date="{now.strftime("%Y-%m-%d")}">\n'
               f"      <description>\n        <p>{html.escape(summary, quote=False)}</p>\n      </description>\n"
               f"    </release>\n")
    write(metainfo, read(metainfo).replace("  <releases>\n", "  <releases>\n" + release, 1))

    print(f"Bumped {old} -> {new}. Expand the notes in CHANGELOG.md and {metainfo}, "
          "then run build-deb.sh and build-rpm.sh.")


if __name__ == "__main__":
    main()
