# OrbitScope on a Raspberry Pi 5

OrbitScope runs entirely on one Raspberry Pi 5 (8 GB): the backend, the web site, a full-screen kiosk on the Pi's own display, and its own Wi-Fi network that visitors join with their phones. With the demo data downloaded once, it keeps working **without internet**, showing only real archive data saved earlier, each item labelled with its date.

```
 phones / laptops ──Wi-Fi "OrbitScope"──┐
                                         ▼
                          ┌──────── Raspberry Pi 5 ────────┐
 Pi's screen (kiosk) ───► │ nginx :80 ──► backend :8000     │ ──Ethernet (optional)──► IRSA, JPL, ESA, CDS
                          │  /opt/orbitscope/www   uvicorn  │
                          │  /var/lib/orbitscope (cache+db) │
                          └─────────────────────────────────┘
```

## What you need

| Item | Notes |
|---|---|
| Raspberry Pi 5, 8 GB | 4 GB also works (lower `MAX_CONCURRENT_JOBS` to 1). |
| Official 27 W USB-C supply + active cooler | Under-voltage or heat slows the pipeline; `orbitscope-check` reports both. |
| microSD card, 64 GB (A2 class recommended) | The cutout cache is capped at 6 GB; logs are kept in RAM to spare the card. |
| Raspberry Pi OS **Bookworm 64-bit, Desktop** | The desktop is needed for the kiosk; Lite works with `--no-kiosk`. |
| Screen (HDMI or DSI, touch optional) | Any size: the kiosk layout scales from 800×480 to 4K and enlarges buttons on touchscreens. |
| Ethernet cable (optional) | Internet while the Wi-Fi radio serves the access point. |

## Install (native, recommended)

On the Pi, logged in as your normal desktop user (with internet for the install):

```bash
git clone https://github.com/mmisovcahid-cmyk/OrbitScopePI.git
cd OrbitScopePI
sudo deploy/pi/install.sh --prewarm
sudo reboot
```

The script:

1. Installs the system packages: Python, nginx, Node.js (to build the web site), Chromium, NetworkManager and nftables.
2. Creates the `orbitscope` system user.
3. Sets up the Python environment in `/opt/orbitscope/venv`.
4. Builds the frontend into `/opt/orbitscope/www`.
5. Installs the `orbitscope` systemd service and the nginx site.
6. Writes `/etc/orbitscope/orbitscope.env`, which holds the Pi settings, a generated review token and the Wi-Fi password.
7. Keeps the system journal in RAM.
8. Sets the Wi-Fi country to **AZ** and opens the access point.
9. Enables desktop auto-login, turns off screen blanking and adds the kiosk autostart.
10. With `--prewarm`, downloads the demo data. This takes about 10 minutes and needs internet.

Options: `--no-ap` keeps Wi-Fi as a normal client; `--no-kiosk` is for a headless server; `WIFI_COUNTRY=TR sudo -E deploy/pi/install.sh` sets another country. Re-run the script after `git pull` to update; settings, data and the Wi-Fi password are kept.

## Install with Docker

```bash
curl -fsSL https://get.docker.com | sh       # Docker + compose plugin (arm64)
sudo deploy/pi/install.sh --docker --prewarm
```

Same settings file, access point and kiosk. The backend and nginx run from `docker-compose.pi.yml`:

- **Web server:** nginx uses the host network, so the kiosk is recognised as the Pi itself.
- **Backend:** published on `127.0.0.1:8000` only.
- **Data:** stays in `/var/lib/orbitscope`.

To build the images on a PC instead of on the Pi:

```bash
docker buildx build --platform linux/arm64 -t orbitscope-backend ./backend
docker buildx build --platform linux/arm64 -t orbitscope-frontend ./frontend
```

## The Wi-Fi access point

```bash
sudo orbitscope-net ap        # wlan0 = access point "OrbitScope", Pi at http://10.42.0.1
sudo orbitscope-net client    # wlan0 back to a normal Wi-Fi client
orbitscope-net status
```

- **Joining:** the kiosk screen shows two QR codes. The first joins the Wi-Fi network; its password is only ever sent to the Pi's own screen, never to visitors. The second opens the site. `http://orbitscope.local` also works.
- **One radio:** the Pi 5 has a single Wi-Fi radio. While it is an access point, internet must come over **Ethernet**; without a cable the app runs offline.
- **Visitor firewall:** visitors on the access point can reach only the web site, DHCP and DNS.
  - **SSH** is blocked on Wi-Fi; use Ethernet, or `sudo orbitscope-net ap --allow-ssh-wifi`.
  - **Internet sharing** to visitors is off; turn it on with `sudo ORBITSCOPE_SHARE_INTERNET=yes orbitscope-net ap`.
- **Review token:** `REVIEW_TOKEN` is set, so visitors can look at candidates but cannot change their review status.

## Offline operation

| Page | Without internet |
|---|---|
| Blink, Comparison, spectrum | Fields downloaded before, e.g. the five challenge targets after `--prewarm`. New fields: clear error. |
| Detection | The three saved example runs and every run saved before; new runs only on cached fields. |
| Gaia / CatWISE overlay | Fields loaded before (fixed catalog releases, so old copies are exact). |
| Planet X | The last real JPL orbit sample, labelled "offline copy, saved <date>". |
| Catalog | Objects looked up before (prewarm saves the quick-link objects and 626 Notburga). Ephemerides and "known objects in field" need internet, because an old answer would be for another date. |
| Sky context (Aladin) | Not available. The panel says so. |

How it works:

- **Snapshots:** every real answer from JPL, Sesame or NED is also written to `/var/lib/orbitscope/cache/offline/`. When the service is unreachable, the backend serves the last copy with `offline_snapshot.saved_at`.
- **Coverage lists:** a SPHEREx coverage list older than 6 hours is reused when IRSA cannot be reached, with `coverage.offline_cached_at` set.
- **Connection check:** a TCP probe (cached for 30 s) skips long network timeouts when the Pi is known to be offline.
- **Banner:** `/api/v1/system/status` reports `components.network.online`, and the UI shows an offline banner.
- **Fonts:** fonts are bundled, so nothing is fetched from Google.

Nothing is invented: without a saved copy the API still returns HTTP 502 with an explanation.

## Kiosk

`orbitscope-kiosk` waits for the backend, then runs Chromium in kiosk mode on `http://localhost/?kiosk=1` and restarts it if it closes. In kiosk mode the UI:

- scales with the screen (root font size about 14 px on 800×480, about 18 px on 1080p, capped at 20 px on 4K);
- uses 40 px touch targets when the screen is a touchscreen;
- shows the QR codes (they can be hidden with ×; a reload brings them back).

To leave the kiosk, press Alt+F4 or run `pkill -f orbitscope-kiosk; pkill chromium` over SSH. To stop it starting at login, remove `~/.config/autostart/orbitscope-kiosk.desktop`.

## Settings

`/etc/orbitscope/orbitscope.env` (template: `deploy/pi/orbitscope.env.example`):

| Setting | Pi default | Meaning |
|---|---|---|
| `MAX_CONCURRENT_JOBS` | 2 | Blink / detection / photometry jobs running at once |
| `SPHEREX_DOWNLOAD_CONCURRENCY` | 6 | Parallel IRSA cutout downloads |
| `SPHEREX_CACHE_MAX_MB` | 6000 | Cutout cache limit (oldest pruned first) |
| `OFFLINE_CACHE_DIR` | `/var/lib/orbitscope/cache/offline` | Offline snapshots |
| `RATE_LIMIT_PER_MINUTE` | 40 | Expensive requests per visitor |
| `PUBLIC_URL`, `WIFI_AP_SSID`, `WIFI_AP_PASSWORD` | written by `orbitscope-net` | Kiosk QR codes |
| `DEFAULT_LOCALE` | `az` | Default API language |

After editing:

- **Native:** `sudo systemctl restart orbitscope`.
- **Docker:** `sudo docker compose -f docker-compose.pi.yml up -d --force-recreate backend`.

## Checks and troubleshooting

```bash
orbitscope-check            # hardware, services, internet, cache, network mode (sudo for settings + logs)
journalctl -u orbitscope -f # backend log (native install)
```

| Symptom | Check |
|---|---|
| Kiosk shows "This site can't be reached" | `systemctl status orbitscope nginx`; the backend needs about 20 s after boot. |
| Phones cannot join | `orbitscope-net status`; the Wi-Fi country must be set (`sudo raspi-config` → Localisation). |
| Phones joined but the page does not open | Use `http://10.42.0.1` (some Android versions do not resolve `.local`). |
| Everything is slow, `throttled=0x...` | Power supply or cooling. |
| "No internet" banner with Ethernet plugged in | `ping -c1 irsa.ipac.caltech.edu`; check DNS on `eth0`. |
| SD card filling up | Lower `SPHEREX_CACHE_MAX_MB`; the cache is pruned at startup and every 50 downloads. |

What has not been verified on real hardware yet:

- the install script, the access point and the kiosk autostart (written for Raspberry Pi OS Bookworm with labwc / NetworkManager);
- the speed of the pipeline on the Pi.

Please run `orbitscope-check` after the first install and report its output.
