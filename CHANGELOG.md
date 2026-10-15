# Changelog

All notable changes to Arrow Browser. Versions follow `MAJOR.MINOR.PATCH`.
Releases are signed; the in-app updater only installs a release whose signature verifies.
Notes from before 1.0.0 (Bharat Browser, and Arrow up to 1.6.9 in the old repository) are in [docs/HISTORY.md](docs/HISTORY.md).

## [1.0.0] - 2026-10-15

A fresh start: Arrow Browser has a new home at https://github.com/Sangam1112/Arrow-Browser, and its version numbers start again at 1.0.0.

### Upgrading from an earlier Arrow
- **Install the 1.0.0 package once.** Copies from the old repository (1.6.9 and earlier) look for updates there, so they won't offer this one. Install the `.deb` or `.rpm` from the Releases page. Your bookmarks, history, saved passwords and settings stay as they are. From then on Arrow updates itself again.

### Added
- **Search in Settings.** Type in the box above the page list and Settings shows only the options that mention it, on whichever page they are, with sections that have no match hidden. Clear the box to see everything again.
- **A new font: Lexend.** Arrow's tabs, menus, Settings, dialogs and its own pages (error pages, History, the Privacy Report) use Lexend, a font made to be easy to read. It ships with Arrow, so it looks the same on every computer; before, Arrow used whatever font the computer had.

### Changed
- **A new look that matches the logo.** The accent colour is now the logo's orange instead of indigo: switches, buttons, the selected tab and Settings page, and the address bar's outline. Settings, the welcome setup and Downloads use one set of line icons instead of emoji, which looked different on every computer. Switches and icon backgrounds are flat, without glow or gradients, and the Settings sidebar shows an icon for each page.
- **Even text sizes and spacing.** Menus, tabs and dialogs used your desktop's text size (often 16 px) while Settings used 10 to 13 px. Everything now starts from 13 px, with 12 px for hints and small print and lighter headings. Settings sections have more room between them, and the main menu is more compact, so on a 768 px high screen it opens below the ☰ button instead of covering the title bar.
- **The About page** no longer mentions the web engine.

### What's in Arrow
A short list for anyone new; the README has the details.
- Ad and tracker blocking (EasyList, EasyPrivacy), a pop-up blocker, hidden cookie banners, tracking tags removed from links, HTTPS everywhere, and a padlock that shows what was blocked on each page.
- Per-site controls under the padlock: ads, JavaScript, pop-ups, zoom, permissions, and clearing one site's data.
- Private windows, saved passwords in the system keyring, bookmarks and history import from other browsers, a first-start setup.
- Tab Memory, sleeping tabs and a Low Memory Mode for older computers; pausable downloads; dark and light themes and dark mode for websites.
- Digital Wellbeing: screen time, daily limits per site, break reminders and bedtime.
- Signed updates: Arrow only installs an update whose Ed25519 signature checks out.
