#!/usr/bin/env bash
# OrbitScope kiosk: full-screen Chromium on the Pi's own display (installed as /usr/local/bin/orbitscope-kiosk).
# Started at desktop login by ~/.config/autostart/orbitscope-kiosk.desktop (install.sh).
# Waits until the backend answers, then opens http://localhost/?kiosk=1 and restarts the browser if it exits.
# Exit the kiosk with Alt+F4 (keyboard) or: pkill -f orbitscope-kiosk; pkill chromium
set -u

URL="${ORBITSCOPE_KIOSK_URL:-http://localhost/?kiosk=1}"
HEALTH="http://localhost/api/v1/system/health"

BROWSER=""
for b in chromium-browser chromium; do
  if command -v "$b" >/dev/null 2>&1; then BROWSER="$b"; break; fi
done
[[ -n "$BROWSER" ]] || { echo "orbitscope-kiosk: Chromium is not installed" >&2; exit 1; }

# Up to ~2 minutes for the backend (first boot imports astropy/scipy).
for _ in $(seq 1 60); do
  curl -fsS -o /dev/null --max-time 2 "$HEALTH" && break
  sleep 2
done

# A crash or power cut must not show the "restore pages?" bar on the next start.
PROFILE="$HOME/.config/chromium"
if [[ -f "$PROFILE/Default/Preferences" ]]; then
  sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"Crashed"/"exit_type":"Normal"/' \
    "$PROFILE/Default/Preferences" || true
fi

while true; do
  "$BROWSER" \
    --kiosk --noerrdialogs --disable-infobars --no-first-run \
    --disable-session-crashed-bubble --disable-features=Translate,TranslateUI \
    --check-for-update-interval=31536000 --password-store=basic \
    --overscroll-history-navigation=0 --disable-pinch \
    --ozone-platform-hint=auto \
    "$URL"
  sleep 3
done
