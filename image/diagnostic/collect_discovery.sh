#!/bin/sh
# Read-only evidence, especially while Agent cannot see an already running Pi.
# No service restarts, network changes, packet transmission to CNC or credentials.
set -u
printf 'Captured UTC: '; date -u
printf 'Hostname: '; hostname
printf 'Uptime: '; cat /proc/uptime
printf 'Model: '; tr -d '\000' </proc/device-tree/model 2>/dev/null || true
printf '\nService status:\n'
systemctl show avahi-daemon zeuz-dnc-api NetworkManager -p Id -p ActiveState -p SubState -p ActiveEnterTimestamp -p NRestarts --no-pager
printf '\nAddresses and routes:\n'
ip -brief address
ip route
printf '\nMulticast memberships:\n'
ip maddr
printf '\nAvahi configuration and service definitions:\n'
cat /etc/avahi/avahi-daemon.conf /etc/avahi/services/zeuz-dnc.service 2>/dev/null || true
printf '\nBonjour sockets:\n'
ss -ulpn | grep ':5353' || true
printf '\nAPI identity (no state changes):\n'
curl --max-time 4 -sS http://127.0.0.1:5000/api/info || true
printf '\nService browse (bounded):\n'
timeout 12 avahi-browse --resolve --terminate _zeuz-dnc._tcp || true
printf '\nAvahi logs (last 24 hours):\n'
journalctl -u avahi-daemon --since '24 hours ago' --no-pager -n 300
printf '\nNetwork logs (last 24 hours):\n'
journalctl -u NetworkManager --since '24 hours ago' --no-pager -n 150
