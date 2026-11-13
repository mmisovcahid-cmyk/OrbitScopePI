#!/usr/bin/env bash
# OrbitScope diagnostics on the Raspberry Pi (installed as /usr/local/bin/orbitscope-check).
#   orbitscope-check           # full report: paste the output when asking for help
#   orbitscope-check --short   # one-screen summary
set -u
SHORT=no; [[ "${1:-}" == "--short" ]] && SHORT=yes
ok() { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
info() { printf '       %s\n' "$*"; }
hdr() { printf '\n\033[1m%s\033[0m\n' "$*"; }

hdr "Hardware / OS"
info "$(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo 'unknown model')"
info "$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-?}") / $(uname -m) / kernel $(uname -r)"
info "RAM: $(free -h | awk '/^Mem:/ {print $3 " used of " $2}')"
info "Disk /: $(df -h / | awk 'NR==2 {print $3 " used, " $4 " free (" $5 ")"}')"
if command -v vcgencmd >/dev/null; then
  info "Temperature: $(vcgencmd measure_temp | cut -d= -f2)"
  thr="$(vcgencmd get_throttled | cut -d= -f2)"
  if [[ "$thr" == "0x0" ]]; then ok "no under-voltage / throttling"; else bad "throttled=$thr (power supply too weak or too hot? use the official 27 W supply and a cooler)"; fi
fi

hdr "Services"
if [[ -f /etc/orbitscope/compose-file ]]; then
  SERVICES=(NetworkManager avahi-daemon docker)
  info "Docker install: $(cat /etc/orbitscope/compose-file)"
  docker compose -f "$(cat /etc/orbitscope/compose-file)" ps 2>/dev/null | sed 's/^/       /'     || info "(run with sudo to list the containers)"
else
  SERVICES=(orbitscope nginx NetworkManager avahi-daemon)
fi
for s in "${SERVICES[@]}"; do
  if systemctl is-active --quiet "$s"; then ok "$s running"; else bad "$s not running (sudo systemctl status $s)"; fi
done

hdr "Web / API"
if curl -fsS -o /dev/null --max-time 5 http://localhost/; then ok "web site on http://localhost/"; else bad "web site not reachable (nginx?)"; fi
status="$(curl -fsS --max-time 15 http://localhost/api/v1/system/status 2>/dev/null)"
if [[ -n "$status" ]]; then
  ok "backend answers"
  python3 - "$status" <<'EOF'
import json, sys
d = json.loads(sys.argv[1]).get("data", {}).get("components", {})
net = d.get("network", {})
cut = d.get("spherex_cutout_cache", {})
print(f"       internet: {'online' if net.get('online') else 'OFFLINE (cached data only)'}")
print(f"       cutout cache: {cut.get('cutouts')} cutouts, {cut.get('size_mb')} / {cut.get('limit_mb')} MB")
print(f"       offline snapshots: {net.get('snapshots')}")
print(f"       jobs: {d.get('jobs')}")
EOF
else
  bad "backend does not answer (journalctl -u orbitscope -n 50)"
fi

hdr "Network"
command -v orbitscope-net >/dev/null && orbitscope-net status 2>/dev/null | sed 's/^/       /'
info "addresses: $(hostname -I 2>/dev/null)"

[[ "$SHORT" == yes ]] && exit 0

hdr "Settings (/etc/orbitscope/orbitscope.env, secrets hidden)"
sudo -n sed -E 's/^(WIFI_AP_PASSWORD|REVIEW_TOKEN)=.+/\1=<set>/' /etc/orbitscope/orbitscope.env 2>/dev/null | grep -v '^#' | grep -v '^$' | sed 's/^/       /' \
  || info "(run with sudo to show)"

hdr "Last backend log lines"
journalctl -u orbitscope -n 25 --no-pager 2>/dev/null | sed 's/^/       /' || info "(run with sudo to show)"
