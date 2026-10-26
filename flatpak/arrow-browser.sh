#!/bin/sh
# Starts Arrow inside the Flatpak the same way the system launcher does: through an import, so Python uses
# the code compiled at build time instead of compiling arrow_browser.py on every start.
exec python3 -c 'import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module("arrow_browser", run_name="__main__", alter_sys=True)' /app/share/arrow-browser "$@"
