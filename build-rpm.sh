#!/bin/bash
# Build script to produce RPM package and standalone release tarball for Fedora / RHEL
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Refresh the updater checksum in package.json before packaging
bash tools/update-checksum.sh
python3 tools/check-version.py

VERSION="$(python3 -c 'import json; print(json.load(open("package.json"))["version"])')"
PKG_NAME="arrow-browser"
OUTPUT_DIR="${OUTPUT_DIR:-$HOME/Downloads}"
# A fresh private folder (not a fixed /tmp name another local user could create or swap first), made
# world-readable like the package tree it holds.
BUILD_ROOT="$(mktemp -d)"
chmod 755 "$BUILD_ROOT"
trap 'rm -rf "$BUILD_ROOT"' EXIT

echo "Building package for ${PKG_NAME} v${VERSION}..."

mkdir -p "${BUILD_ROOT}/usr/share/arrow-browser/assets"
mkdir -p "${BUILD_ROOT}/usr/bin"
mkdir -p "${BUILD_ROOT}/usr/share/applications"
mkdir -p "${BUILD_ROOT}/usr/share/icons/hicolor/256x256/apps"

cp arrow_browser.py "${BUILD_ROOT}/usr/share/arrow-browser/"
cp -r assets/* "${BUILD_ROOT}/usr/share/arrow-browser/assets/"
cp arrow-browser "${BUILD_ROOT}/usr/bin/arrow-browser"
cp arrow-browser.desktop "${BUILD_ROOT}/usr/share/applications/"
cp assets/arrow_icon.png "${BUILD_ROOT}/usr/share/icons/hicolor/256x256/apps/arrow-browser.png"
mkdir -p "${BUILD_ROOT}/usr/share/licenses/arrow-browser"
cp LICENSE "${BUILD_ROOT}/usr/share/licenses/arrow-browser/LICENSE"  # the GPL goes with every copy

chmod +x "${BUILD_ROOT}/usr/bin/arrow-browser" "${BUILD_ROOT}/usr/share/arrow-browser/arrow_browser.py"
# The command before the rename keeps working (menu entries, scripts, wrappers that call it).
ln -s arrow-browser "${BUILD_ROOT}/usr/bin/bharat-browser"

if command -v rpmbuild &> /dev/null; then
    mkdir -p ~/rpmbuild/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
    cat <<EOF > ~/rpmbuild/SPECS/arrow-browser.spec
Name:           arrow-browser
Version:        ${VERSION}
Release:        1%{?dist}
Summary:        Modern, Ultra-Fast, Multi-Tab, and Privacy-First Web Browser
License:        GPL-3.0-or-later
URL:            https://github.com/Sangam1112/Arrow-Browser
BuildArch:      noarch
# Fedora names the WebKit package webkit2gtk4.1; RHEL/Rocky/AlmaLinux/CentOS Stream call it webkit2gtk3.
Requires:       python3 python3-gobject gobject-introspection gtk3 (webkit2gtk4.1 or webkit2gtk3)
Suggests:       gnome-keyring hunspell-en
# Called Bharat Browser up to 1.5.19: installing this replaces that package.
Provides:       bharat-browser = %{version}-%{release}
Obsoletes:      bharat-browser < 1.6.0

%description
Arrow Browser is a modern, high-performance web browser designed with strict security, privacy protection, and site compatibility at its core.

%install
mkdir -p %{buildroot}
cp -r ${BUILD_ROOT}/* %{buildroot}/

%files
/usr/bin/arrow-browser
/usr/bin/bharat-browser
/usr/share/arrow-browser
/usr/share/applications/arrow-browser.desktop
%license /usr/share/licenses/arrow-browser/LICENSE
/usr/share/icons/hicolor/256x256/apps/arrow-browser.png

# Precompile on install so launches don't recompile arrow_browser.py each time (~0.25 s): users can't
# write a __pycache__ into /usr/share themselves. Removed again on uninstall (not on upgrade).
%post
python3 -m py_compile /usr/share/arrow-browser/arrow_browser.py >/dev/null 2>&1 || :

%preun
if [ \$1 -eq 0 ]; then rm -rf /usr/share/arrow-browser/__pycache__; fi

%changelog
* Sun Oct 25 2026 Arrow Browser Developer <Sangam1112@users.noreply.github.com> - 1.0.3-1
- Links you click are upgraded to HTTPS, cleaned and checked for fake bank sites; tracker companies' own sites open; review fixes
* Fri Oct 16 2026 Arrow Browser Developer <Sangam1112@users.noreply.github.com> - 1.0.2-1
- Scam warnings, YouTube sponsor skipping, a regrouped Privacy page and stability fixes
* Thu Oct 15 2026 Arrow Browser Developer <Sangam1112@users.noreply.github.com> - 1.0.1-1
- Fedora: Arrow didn't start on a fresh install
* Thu Oct 15 2026 Arrow Browser Developer <Sangam1112@users.noreply.github.com> - 1.0.0-1
- Arrow Browser 1.0.0: new home at github.com/Sangam1112/Arrow-Browser, Lexend font, new look, Settings search
EOF

    rpmbuild -bb ~/rpmbuild/SPECS/arrow-browser.spec
    cp ~/rpmbuild/RPMS/noarch/arrow-browser-${VERSION}-1*.noarch.rpm ./
fi

# Package standalone tarball for Fedora. install-fedora.sh copies arrow_browser.py,
# assets/ and arrow-browser.desktop from its OWN directory, so those must sit next to
# it at the top level (the usr/ tree alone is not enough: the script would fail with
# "cp: cannot stat 'arrow_browser.py'"). tests/test_installers.py guards this.
cp install-fedora.sh arrow_browser.py arrow-browser.desktop LICENSE "${BUILD_ROOT}/"
cp -r assets "${BUILD_ROOT}/assets"
chmod +x "${BUILD_ROOT}/install-fedora.sh"
tar -czf "arrow-browser_${VERSION}_fedora.tar.gz" -C "$BUILD_ROOT" .
mkdir -p "$OUTPUT_DIR"
cp "arrow-browser_${VERSION}_fedora.tar.gz" "$OUTPUT_DIR/arrow-browser_${VERSION}_fedora.tar.gz"
echo "Archive generated: arrow-browser_${VERSION}_fedora.tar.gz (copied to $OUTPUT_DIR)"
