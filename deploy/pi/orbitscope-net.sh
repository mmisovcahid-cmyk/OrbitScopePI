#!/usr/bin/env bash
# OrbitScope - Wi-Fi access point for the Raspberry Pi demo (installed as /usr/local/bin/orbitscope-net)
#
#   sudo orbitscope-net ap        # wlan0 becomes the "OrbitScope" access point (10.42.0.1)
#   sudo orbitscope-net client    # wlan0 back to a normal Wi-Fi client (home / school network)
#   orbitscope-net status
#
# The Pi 5 has ONE Wi-Fi radio: while it is an access point it cannot also join another Wi-Fi.
# For internet in AP mode, plug in Ethernet; without it the app runs offline from its cache.
#
# In AP mode a firewall (nftables table "orbitscope") lets access-point visitors reach only the
# web site (HTTP), DHCP and DNS. SSH works over Ethernet only, unless --allow-ssh-wifi is given.
set -euo pipefail

CON="OrbitScope-AP"
IFACE="${ORBITSCOPE_WIFI_IFACE:-wlan0}"
ENV_FILE="/etc/orbitscope/orbitscope.env"
AP_ADDR="10.42.0.1"
DNSMASQ_CONF="/etc/NetworkManager/dnsmasq-shared.d/orbitscope.conf"

die() { echo "orbitscope-net: $*" >&2; exit 1; }
need_root() { [[ $EUID -eq 0 ]] || die "run with sudo"; }
env_get() { sed -n "s/^$1=//p" "$ENV_FILE" 2>/dev/null | tail -n1; }

env_set() {  # env_set KEY VALUE  (value must not contain newlines)
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    local esc; esc=$(printf '%s' "$val" | sed -e 's/[\/&|]/\\&/g')
    sed -i "s|^${key}=.*|${key}=${esc}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >>"$ENV_FILE"
  fi
}

firewall_on() {
  local allow_ssh="$1"
  command -v nft >/dev/null || { echo "nft not found: skipping the access-point firewall"; return; }
  nft delete table inet orbitscope 2>/dev/null || true
  local ssh_rule="" fwd="drop"
  [[ "$allow_ssh" == "yes" ]] && ssh_rule="tcp dport 22 accept"
  [[ "${ORBITSCOPE_SHARE_INTERNET:-no}" == "yes" ]] && fwd="accept"
  nft -f - <<EOF
table inet orbitscope {
  chain input {
    type filter hook input priority 0; policy accept;
    iifname != "$IFACE" accept
    ct state established,related accept
    iifname "$IFACE" ip protocol icmp accept
    iifname "$IFACE" udp dport { 53, 67, 5353 } accept
    iifname "$IFACE" tcp dport { 53, 80 } accept
    ${ssh_rule:+iifname "$IFACE" $ssh_rule}
    iifname "$IFACE" drop
  }
  chain forward {
    type filter hook forward priority 0; policy accept;
    # visitors may use the Pi's Ethernet internet only if ORBITSCOPE_SHARE_INTERNET=yes
    iifname "$IFACE" $fwd
  }
}
EOF
}

restart_backend() {  # new QR values are read at startup
  if [[ -f /etc/orbitscope/compose-file ]] && command -v docker >/dev/null; then
    docker compose -f "$(cat /etc/orbitscope/compose-file)" up -d --force-recreate backend >/dev/null 2>&1 || true
  else
    systemctl restart orbitscope.service 2>/dev/null || true
  fi
}

firewall_off() { command -v nft >/dev/null && nft delete table inet orbitscope 2>/dev/null || true; }

cmd_ap() {
  need_root
  local allow_ssh="no"
  [[ "${1:-}" == "--allow-ssh-wifi" ]] && allow_ssh="yes"
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found (run deploy/pi/install.sh first)"
  local ssid pass
  ssid="$(env_get WIFI_AP_SSID)"; ssid="${ssid:-OrbitScope}"
  pass="$(env_get WIFI_AP_PASSWORD)"
  if [[ ${#pass} -lt 8 ]]; then
    # 10 characters without 0/O/1/l/I, easy to type from the screen
    pass="$(python3 -c "import secrets; a='abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'; print(''.join(secrets.choice(a) for _ in range(10)))")"
    env_set WIFI_AP_PASSWORD "$pass"
  fi
  env_set WIFI_AP_SSID "$ssid"
  env_set PUBLIC_URL "http://${AP_ADDR}"

  # Phones that ask DNS (not mDNS) for orbitscope.local get the Pi as well.
  mkdir -p "$(dirname "$DNSMASQ_CONF")"
  printf 'address=/orbitscope.local/%s\naddress=/orbitscope.lan/%s\n' "$AP_ADDR" "$AP_ADDR" >"$DNSMASQ_CONF"

  nmcli connection delete "$CON" >/dev/null 2>&1 || true
  nmcli connection add type wifi ifname "$IFACE" con-name "$CON" autoconnect yes \
    connection.autoconnect-priority 100 ssid "$ssid" \
    802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
    ipv4.method shared ipv4.addresses "${AP_ADDR}/24" ipv6.method disabled \
    wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp \
    wifi-sec.psk "$pass" >/dev/null
  nmcli connection up "$CON" >/dev/null
  firewall_on "$allow_ssh"
  restart_backend
  echo "Access point '$ssid' is up on $IFACE: http://${AP_ADDR}  (password in $ENV_FILE)"
  [[ "$allow_ssh" == "yes" ]] || echo "SSH over the access point is blocked; use Ethernet (or: orbitscope-net ap --allow-ssh-wifi)."
}

cmd_client() {
  need_root
  firewall_off
  if nmcli -t -f NAME connection show | grep -qx "$CON"; then
    nmcli connection modify "$CON" connection.autoconnect no
    nmcli connection down "$CON" >/dev/null 2>&1 || true
  fi
  rm -f "$DNSMASQ_CONF"
  nmcli device wifi rescan ifname "$IFACE" >/dev/null 2>&1 || true
  nmcli device connect "$IFACE" >/dev/null 2>&1 || echo "No saved Wi-Fi network in range; connect with: nmcli device wifi connect <SSID> --ask"
  if [[ -f "$ENV_FILE" ]]; then
    env_set PUBLIC_URL "http://$(hostname).local"
    restart_backend
  fi
  echo "$IFACE is a Wi-Fi client again."
}

cmd_status() {
  nmcli -f GENERAL.DEVICE,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS device show "$IFACE" 2>/dev/null || true
  if nmcli -t -f NAME,DEVICE connection show --active | grep -q "^${CON}:"; then
    echo "mode: access point ($(env_get WIFI_AP_SSID)) - http://${AP_ADDR}"
  else
    echo "mode: client"
  fi
  if nft list table inet orbitscope >/dev/null 2>&1; then echo "firewall: on"; else echo "firewall: off"; fi
}

case "${1:-}" in
  ap) shift; cmd_ap "$@" ;;
  client) cmd_client ;;
  status) cmd_status ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
