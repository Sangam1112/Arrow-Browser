# Changelog

All notable changes to Arrow Browser. Versions follow `MAJOR.MINOR.PATCH`.
Releases are signed; the in-app updater only installs a release whose signature verifies.
Notes from before 1.0.0 (Bharat Browser, and Arrow up to 1.6.9 in the old repository) are in [docs/HISTORY.md](docs/HISTORY.md).

## [1.0.6] - 2026-10-27

### Changed
- **Pages with videos use less memory and data.** Arrow told every video on every page to start downloading at once, even ones you never play, and watched every change on every page to do so. Videos now load the way the site asks. With 4 news and reference tabs open this saved about 30 MB. AV1 stays turned down as before, and the fix for videos that froze after leaving fullscreen stays too.
- **Hiding cookie banners is now off by default.** Its list of about 1 MB is applied to every page and cost about 6 MB per tab. Turn it on in Settings → Privacy → Hide cookie banners. If you had it on, it stays on. While it's off, Arrow no longer downloads the cookie-banner list.

## [1.0.5] - 2026-10-26

### Added
- **Arrow can now be built as a Flatpak, for Flathub.** The recipe and store page are in `flatpak/`. Inside a Flatpak, Arrow keeps its profile in the app's own folder (`~/.var/app/io.github.Sangam1112.Arrow-Browser`), every web page runs in its own Flatpak sandbox, and Flathub delivers the updates, so the built-in updater stays off there. Screenshots go to Downloads, because a Flatpak can't reach the Desktop folder. The Flatpak uses the GNOME runtime's WebKit, which usually gets security fixes sooner than Ubuntu's.

### Fixed
- **The mouse wheel and touchpad didn't scroll some sites at all**, such as mindrift.ai. A page that turns off the bounce at its ends and also listens for the wheel froze scrolling in the engine. Arrow now keeps up-and-down scrolling working on such pages; sideways stays as the site set it.

### Changed
- **File pickers use your desktop's own file chooser.** Importing, backing up, Save Page As and choosing the download folder now open the same chooser as your other apps (in the Flatpak, the only one that can reach every folder).

## [1.0.4] - 2026-10-26

### Added
- **Sites are told not to sell or share your data (Global Privacy Control).** Every page and frame sees `navigator.globalPrivacyControl` set to on, the signal that laws such as California's CCPA make sites honour. Arrow can only send it to the page's scripts, not as the `Sec-GPC` request header.

### Changed
- **The toolbar's buttons got a cleaner, matching set of icons.** They came from your desktop's icon theme, so back, forward and reload were thin outlines while the camera, bookmarks and new-tab icons were heavy and filled, and they looked different on every Linux desktop. All toolbar buttons now use Arrow's own line icons, the same family as in Settings, and they follow the light and dark theme and hover.
- **The shield button shows a real shield.** It was a small emoji that was hard to see, especially in the dark theme.
- **The Bookmark Manager button no longer looks like the address bar's star.** Two identical stars sat side by side; the manager now has a bookmark-book icon, and the star in the address bar still bookmarks the page.

### Fixed
- **Clicking a link could quietly report the click to a tracker.** A link with a `ping` attribute sends a report to an address the page picks when you click it. The engine's switch for turning this off no longer does anything, so Arrow's tracker blocker now stops every such report. It follows "Block ads and trackers", like the rest of the blocker.

## [1.0.3] - 2026-10-25

### Fixed
- **Links you click in a page now get the same protection as addresses you type.** Before, only the address bar, bookmarks and new tabs were cleaned: a link clicked inside a page went out over plain `http://` and kept its `utm_`, `fbclid` and other tracking tags, because the request is sent before Arrow hears of the click. Now `http://` links are switched to HTTPS before anything is sent (local devices such as routers and printers excepted), and tracking tags are removed from a link the moment you click it, with the same rules as the address bar. A site with no secure version shows the usual "Secure connection unavailable" page with "Continue to HTTP".
- **The fake bank site warning missed links you clicked**, for the same reason: it only caught addresses you typed or opened in a new tab. Clicked links, redirects and frames inside a page are now checked too, before the page is asked for.
- **Some sites couldn't be opened at all**, such as sentry.io, hotjar.com, mixpanel.com and criteo.com: the built-in tracker list blocked visiting them, not just their trackers on other sites. They open now; their trackers are still blocked everywhere else.
- **A hidden frame could save a file without a click** when the page couldn't show it. Only the page you open can turn into a download now; frames follow the normal rules (only files the server sends as downloads).
- **Typing a `file://` address didn't open the file.** It now opens, as a file passed from another app does.
- **Turning off "Keep the block lists up to date" kept using the downloaded lists**, and a refreshed list that was shorter than the old one was never used. The newest choice now always takes effect.
- **Pop-ups lost their password prompts and blocked-items count** once the tab that opened them was closed.
- **Closing the keyring's unlock window during a passwords import asked again for every login** (300 times for 300 logins). The import now stops and says the keyring stayed locked.
- **Switching on "Hide cookie banners" could download all the block lists again (about 10 MB).** It now downloads only the cookie list, and only if it's missing.
- **Block lists only updated when Arrow started.** A browser left open for days now checks every 6 hours.

### Changed
- **The fake site and HTTPS warning pages can no longer be read by the site they warn about**, so a frame from that site can't press "Open anyway" for you. The address bar still shows the address that was stopped.

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
