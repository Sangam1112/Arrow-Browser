# Changelog

All notable changes to Arrow Browser. Versions follow `MAJOR.MINOR.PATCH`.
Releases are signed; the in-app updater only installs a release whose signature verifies.
Notes from before 1.0.0 (Bharat Browser, and Arrow up to 1.6.9 in the old repository) are in [docs/HISTORY.md](docs/HISTORY.md).

## [1.0.2] - 2026-10-16

### Added
- **Warnings for fake bank and payment sites.** A page whose address copies SBI, HDFC, ICICI, Axis, Kotak, Paytm, PhonePe, IRCTC, Aadhaar, Income Tax, EPFO and other official sites (`sbi-kyc-update.in`, `hdfcbank.co`, `icic1bank.com`, `onlinesbi.sbi.verify.top`) is stopped before it opens, even after a short-link redirect. The warning offers the real site, or to open it anyway. Addresses that mix Latin letters with look-alike letters from other alphabets are flagged too. All of it is checked on your computer; no address is sent anywhere.
- **A warning when a page copies a command.** Fake "I'm not a robot" pages copy a command and ask you to paste it into a Terminal or the Run box. When a page puts a command that downloads and runs a program on your clipboard, Arrow shows it in full and offers to remove it. Text you copy yourself with Ctrl+C or Copy isn't flagged, unless the page swapped it for something else.
- **Skip sponsors in YouTube videos (SponsorBlock), off by default.** Turn it on in Settings → Privacy & Security to jump over paid promotions, self-promotion and subscribe reminders that [SponsorBlock](https://sponsor.ajay.app)'s users have marked. Arrow sends only 4 characters of a scrambled video ID, which match dozens of videos, so SponsorBlock can't tell which one you watch. It costs about 2 MB per YouTube tab and no measurable CPU.

### Changed
- **Settings → Privacy & Security is regrouped** into Your data, Blocking, Scam warnings, Block lists, Connections, Passwords and Sites, and starts with what matters most: Arrow collects no personal data.
- **Arrow's profile folders are now private to your user account.** Other accounts on the same computer can no longer read your cookies or cache.
- **The address bar only looks up a site early while you're typing in it**, not when another part of Arrow changes its text.

### Fixed
- **Ctrl+scroll on a touchpad didn't zoom.** Every smooth-scroll zoom raised an error; it now zooms one 10% step at a time.
- **A page that kept crashing or failing to load could be reloaded forever.** Crashes within 5 minutes now count together even when the page finishes loading in between, and a page whose connection drops partway no longer retries every 600 ms without end.
- **A retry could load an old page after you'd moved on**, or into a tab you had already closed.
- **Timers kept running after a window closed**, checking tabs that no longer existed.

## [1.0.1] - 2026-10-15

### Fixed
- **On a fresh Fedora, Arrow didn't start.** Its interface library needs a small GNOME component (`gobject-introspection`) that a full Fedora desktop usually has but a leaner install doesn't, and the `.rpm` didn't ask for it. It does now, so `dnf install` brings it along. Ubuntu, Debian and Mint weren't affected.

### Changed
- **Every release is now installed and started on fresh Ubuntu 24.04, Ubuntu 22.04 (the base of Linux Mint 21), Debian 12 and Fedora** before anyone else gets it: the test checks that a page loads, Settings opens, and the font and icons work.

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
