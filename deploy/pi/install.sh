#!/usr/bin/env bash
# OrbitScope - install on a Raspberry Pi 5 (Raspberry Pi OS Bookworm 64-bit, Desktop)
#
#   git clone https://github.com/mmisovcahid-cmyk/OrbitScopePI.git && cd OrbitScopePI
#   sudo deploy/pi/install.sh                 # native: backend + web site + kiosk + Wi-Fi access point
#   sudo deploy/pi/install.sh --docker        # same, but backend and web server run in Docker
#   sudo deploy/pi/install.sh --no-ap         # keep wlan0 as a normal Wi-Fi client
#   sudo deploy/pi/install.sh --no-kiosk      # headless (no browser on the Pi's screen)
#   sudo deploy/pi/install.sh --prewarm       # also download the demo data now (needs internet)
#
# Re-running it updates the code and keeps settings, data and the Wi-Fi password.
# Layout: code /opt/orbitscope, settings /etc/orbitscope/orbitscope.env, data /var/lib/orbitscope.
# Native mode builds the frontend on the Pi with Debian's Node.js 18 (about 2 minutes); a
# frontend/dist built on a PC (cd frontend && npm ci && npm run build) is used if that fails.
# Docker mode needs Docker with the compose plugin (curl -fsSL https://get.docker.com | sh).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP=/opt/orbitscope
DATA=/var/lib/orbitscope
ETC=/etc/orbitscope
ENV_FILE="$ETC/orbitscope.env"
WIFI_COUNTRY="${WIFI_COUNTRY:-AZ}"
DO_AP=yes; DO_KIOSK=yes; DO_PREWARM=no; DO_DOCKER=no

for arg in "$@"; do
  case "$arg" in
    --docker) DO_DOCKER=yes ;;
    --no-ap) DO_AP=no ;;
    --no-kiosk) DO_KIOSK=no ;;
    --prewarm) DO_PREWARM=yes ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*" >&2; }

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
[[ "$(uname -m)" == "aarch64" ]] || warn "expected a 64-bit Raspberry Pi OS (aarch64), found $(uname -m)"
DESKTOP_USER="${SUDO_USER:-}"
[[ -n "$DESKTOP_USER" && "$DESKTOP_USER" != "root" ]] || { DO_KIOSK=no; warn "no desktop user (run with sudo from your user): kiosk skipped"; }
if [[ "$DO_DOCKER" == yes ]] && ! docker compose version >/dev/null 2>&1; then
  echo "Docker with the compose plugin is missing. Install it with:  curl -fsSL https://get.docker.com | sh" >&2
  exit 1
fi

# ----------------------------------------------------------------------------- packages
step "System packages"
apt-get update -qq
PKGS=(python3 curl rsync avahi-daemon nftables network-manager iw astrometry.net)
[[ "$DO_DOCKER" == no ]] && PKGS+=(python3-venv python3-dev build-essential nginx nodejs npm)
if [[ "$DO_KIOSK" == yes ]]; then
  if apt-cache show chromium-browser >/dev/null 2>&1; then PKGS+=(chromium-browser); else PKGS+=(chromium); fi
fi
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${PKGS[@]}"

step "User and directories"
id orbitscope >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin orbitscope
install -d -o orbitscope -g orbitscope -m 750 "$DATA" "$DATA/cache" "$DATA/cache/spherex" "$DATA/cache/offline" "$DATA/db"
install -d -m 750 -g orbitscope "$ETC"
usermod -aG video orbitscope   # Ground Node: the backend may use the Pi camera

step "Plate-solving index files (astrometry.net 4100 series, wide fields 0.1-30 deg+, ~60 MB)"
IDX=/usr/share/astrometry
install -d "$IDX"
for n in 4108 4109 4110 4111 4112 4113 4114 4115 4116 4117 4118 4119; do
  [[ -s "$IDX/index-$n.fits" ]] || curl -fsSL -o "$IDX/index-$n.fits" "http://data.astrometry.net/4100/index-$n.fits"     || warn "index-$n.fits could not be downloaded (internet?); plate solving of that scale will fail"
done

step "Settings ($ENV_FILE)"
if [[ ! -f "$ENV_FILE" ]]; then
  install -m 640 -g orbitscope "$REPO/deploy/pi/orbitscope.env.example" "$ENV_FILE"
  token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
  sed -i "s|^REVIEW_TOKEN=.*|REVIEW_TOKEN=${token}|" "$ENV_FILE"
  echo "Candidate review token (needed to mark candidates real/artifact): $token"
  echo "(it is kept in $ENV_FILE)"
else
  echo "keeping the existing settings"
fi

step "Helper commands"
install -m 755 "$REPO/deploy/pi/orbitscope-net.sh" /usr/local/bin/orbitscope-net
install -m 755 "$REPO/deploy/pi/kiosk.sh" /usr/local/bin/orbitscope-kiosk
install -m 755 "$REPO/deploy/pi/pi_check.sh" /usr/local/bin/orbitscope-check

# ----------------------------------------------------------------------------- application
if [[ "$DO_DOCKER" == no ]]; then
  install -d -m 755 "$APP" "$APP/www"

  step "Code -> $APP"
  rsync -a --delete --exclude '__pycache__' --exclude '.pytest_cache' --exclude 'cache/' --exclude 'data/' \
    --exclude '.env' --exclude 'tests/' "$REPO/backend/" "$APP/backend/"
  chown -R root:root "$APP/backend"

  step "Python environment (numpy / scipy / astropy wheels for aarch64)"
  [[ -x "$APP/venv/bin/python" ]] || python3 -m venv "$APP/venv"
  "$APP/venv/bin/pip" install -q --upgrade pip
  grep -vE '^(pytest|pytest-asyncio)' "$REPO/backend/requirements.txt" >/tmp/orbitscope-req.txt
  "$APP/venv/bin/pip" install -q -r /tmp/orbitscope-req.txt
  rm -f /tmp/orbitscope-req.txt

  step "Frontend"
  if command -v npm >/dev/null 2>&1 && [[ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)" -ge 18 ]]; then
    # Built as the desktop user, so node_modules stays theirs.
    sudo -u "${DESKTOP_USER:-root}" bash -c "cd '$REPO/frontend' && npm ci --no-audit --no-fund && npm run build" \
      || warn "frontend build on the Pi failed; using an existing frontend/dist if there is one"
  fi
  [[ -f "$REPO/frontend/dist/index.html" ]] || {
    echo "frontend/dist is missing: build it on a PC (cd frontend && npm ci && npm run build)," >&2
    echo "copy frontend/dist to this Pi, or install Node.js 18+, then run this script again." >&2
    exit 1
  }
  rsync -a --delete "$REPO/frontend/dist/" "$APP/www/"

  step "Backend service"
  install -m 644 "$REPO/deploy/pi/orbitscope.service" /etc/systemd/system/orbitscope.service
  rm -f "$ETC/compose-file"
  systemctl daemon-reload
  systemctl enable orbitscope.service
  systemctl restart orbitscope.service

  step "nginx"
  install -m 644 "$REPO/deploy/pi/nginx-orbitscope.conf" /etc/nginx/sites-available/orbitscope
  ln -sf /etc/nginx/sites-available/orbitscope /etc/nginx/sites-enabled/orbitscope
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable nginx
  systemctl restart nginx
else
  step "Docker (backend + nginx containers)"
  # A native install would hold port 80 / 8000: stop it (its files stay).
  systemctl disable --now orbitscope.service nginx 2>/dev/null || true
  sed 's|root /opt/orbitscope/www;|root /usr/share/nginx/html;|' "$REPO/deploy/pi/nginx-orbitscope.conf" >"$ETC/nginx-docker.conf"
  chmod 644 "$ETC/nginx-docker.conf"
  echo "$REPO/docker-compose.pi.yml" >"$ETC/compose-file"   # orbitscope-net recreates the backend with it
  docker compose -f "$REPO/docker-compose.pi.yml" up -d --build
fi

# ----------------------------------------------------------------------------- system
step "SD card care: logs in RAM (max 50 MB)"
install -d /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/orbitscope.conf <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=50M
EOF
systemctl restart systemd-journald

if [[ "$DO_AP" == yes ]]; then
  step "Wi-Fi access point (country $WIFI_COUNTRY)"
  if command -v raspi-config >/dev/null 2>&1; then raspi-config nonint do_wifi_country "$WIFI_COUNTRY" || true; fi
  iw reg set "$WIFI_COUNTRY" 2>/dev/null || true
  rfkill unblock wifi 2>/dev/null || true
  /usr/local/bin/orbitscope-net ap
fi

if [[ "$DO_KIOSK" == yes ]]; then
  step "Kiosk for $DESKTOP_USER"
  home="$(getent passwd "$DESKTOP_USER" | cut -d: -f6)"
  install -d -o "$DESKTOP_USER" -g "$DESKTOP_USER" "$home/.config" "$home/.config/autostart"
  cat >"$home/.config/autostart/orbitscope-kiosk.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=OrbitScope kiosk
Exec=/usr/local/bin/orbitscope-kiosk
X-GNOME-Autostart-enabled=true
EOF
  chown "$DESKTOP_USER:$DESKTOP_USER" "$home/.config/autostart/orbitscope-kiosk.desktop"
  if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_boot_behaviour B4 || true   # desktop, logged in automatically
    raspi-config nonint do_blanking 1 || true          # never blank the screen
  fi
fi

if [[ "$DO_PREWARM" == yes ]]; then
  step "Demo data (five targets, Detection examples, Planet X / catalog snapshots)"
  if [[ "$DO_DOCKER" == yes ]]; then
    docker compose -f "$REPO/docker-compose.pi.yml" exec -T backend python -m scripts.prewarm \
      || warn "prewarm incomplete (internet?)"
  else
    sudo -u orbitscope HOME="$DATA" \
      bash -c "set -a; . '$ENV_FILE'; set +a; cd '$APP/backend' && '$APP/venv/bin/python' -m scripts.prewarm" \
      || warn "prewarm incomplete (internet?)"
  fi
fi

step "Done"
sleep 3
/usr/local/bin/orbitscope-check --short || true
cat <<EOF

OrbitScope is installed ($( [[ "$DO_DOCKER" == yes ]] && echo Docker || echo native )).
  This screen:   http://localhost/?kiosk=1  (starts by itself after a reboot)
  Phones:        join the Wi-Fi shown on the screen, then scan the second QR code
  Settings:      $ENV_FILE   (then: sudo deploy/pi/install.sh again, or sudo orbitscope-net ap)
  Diagnostics:   orbitscope-check
  Wi-Fi mode:    sudo orbitscope-net ap | client | status
Reboot once to start the kiosk: sudo reboot
EOF
