#!/bin/bash
# Runs inside a fresh distribution container (see workflows/install-test.yml): install Arrow the way the README
# says, then start it once as a normal user with tools/smoke-test.py.
# KIND=deb|rpm, SOURCE=true to build the packages from this checkout instead of downloading release WANT.
set -euo pipefail
cd /src

echo "== Tools for the test (not Arrow's own dependencies)"
if [ "$KIND" = deb ]; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends curl ca-certificates xvfb xauth dbus \
        python3 binutils xz-utils >/dev/null
else
    dnf install -y -q curl xorg-x11-server-Xvfb xauth dbus-daemon python3 rpm-build
fi

if [ "${SOURCE:-false}" = true ]; then
    echo "== Building the packages from this commit"
    if [ "$KIND" = deb ]; then OUTPUT_DIR="$PWD" bash build-deb.sh; PKG="$(ls "$PWD"/arrow-browser_*-1_all.deb)"
    else bash build-rpm.sh; PKG="$(ls "$PWD"/arrow-browser-*.noarch.rpm)"; fi   # Fedora tags it: -1.fc44
else
    V="${WANT#v}"
    if [ -z "$V" ]; then
        V="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p')"
    fi
    echo "== Downloading Arrow $V"
    if [ "$KIND" = deb ]; then F="arrow-browser_${V}-1_all.deb"; else F="arrow-browser-${V}-1.noarch.rpm"; fi
    curl -fsSLO "https://github.com/$REPO/releases/download/v$V/$F"
    PKG="$PWD/$F"
fi

echo "== Installing $(basename "$PKG")"
if [ "$KIND" = deb ]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$PKG" >/dev/null
else
    dnf install -y -q "$PKG"
fi
command -v arrow-browser

echo "== Starting it as a normal user"
useradd -m tester
cp tools/smoke-test.py /home/tester/ && chown tester /home/tester/smoke-test.py
su tester -c "cd ~ && dbus-run-session -- xvfb-run -a python3 smoke-test.py"
