#!/bin/bash
set -euo pipefail

exec >/var/log/zeuz-firstboot.log 2>&1
echo "==> Iniciando aprovisionamiento Zeuz"

BOOT=/boot
if [ -d /boot/firmware/zeuz ]; then
    BOOT=/boot/firmware
fi
PAYLOAD="$BOOT/zeuz"

if [ ! -d "$PAYLOAD" ]; then
    echo "ERROR: no existe $PAYLOAD"
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> Instalando dependencias ARM64 sin conexión"
apt-get --yes --no-download install "$PAYLOAD"/debs/*.deb

echo "==> Creando identidad local"
if ! id zeuz >/dev/null 2>&1; then
    useradd --uid 1000 --create-home --home-dir /var/lib/zeuz --shell /bin/bash zeuz
fi
passwd --lock zeuz
for group in dialout video render input; do
    if getent group "$group" >/dev/null; then
        usermod -a -G "$group" zeuz
    fi
done

SERIAL=""
if [ -r /proc/device-tree/serial-number ]; then
    SERIAL="$(tr -d '\000' </proc/device-tree/serial-number)"
fi
if [ -z "$SERIAL" ]; then
    SERIAL="$(awk -F: '/^Serial/ {gsub(/ /, "", $2); print $2}' /proc/cpuinfo)"
fi
SUFFIX="$(printf '%s' "${SERIAL:-000000}" | tail -c 7 | tr '[:upper:]' '[:lower:]')"
HOSTNAME="zeuz-dnc-${SUFFIX}"
hostnamectl set-hostname "$HOSTNAME"
sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts

echo "==> Instalando Zeuz DNC"
install -d -o root -g root -m 0755 /opt/zeuz
rm -rf /opt/zeuz/zeusdnc
tar -xzf "$PAYLOAD/zeusdnc.tar.gz" -C /opt/zeuz
chown -R root:root /opt/zeuz/zeusdnc
chmod -R a+rX /opt/zeuz/zeusdnc

install -d -o zeuz -g zeuz -m 0750 /var/lib/zeuz/programs
install -d -o root -g root -m 0755 /etc/zeuz
install -m 0644 "$PAYLOAD/zeuz-dnc-qt.service" /etc/systemd/system/zeuz-dnc-qt.service

echo "==> Ajustando el sistema para operación industrial"
install -d -m 0755 /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/zeuz.conf <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=32M
EOF

install -d -m 0755 /etc/systemd/system.conf.d
cat >/etc/systemd/system.conf.d/zeuz-watchdog.conf <<'EOF'
[Manager]
RuntimeWatchdogSec=30s
RebootWatchdogSec=2min
EOF

systemctl disable ssh.service 2>/dev/null || true
systemctl disable userconfig.service 2>/dev/null || true
systemctl enable avahi-daemon.service
systemctl enable zeuz-dnc-qt.service
systemctl set-default multi-user.target

echo "==> Limpiando el aprovisionamiento"
for CMDLINE in /boot/cmdline.txt /boot/firmware/cmdline.txt; do
    if [ -f "$CMDLINE" ]; then
        sed -i 's| systemd.run.*||g' "$CMDLINE"
    fi
done
rm -f /boot/firstrun.sh /boot/firmware/firstrun.sh
rm -rf "$PAYLOAD"
sync

echo "==> Imagen Zeuz lista; reiniciando"
exit 0
