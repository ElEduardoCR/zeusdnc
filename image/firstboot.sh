#!/bin/bash
set -Eeuo pipefail

LOG=/var/log/zeuz-firstboot.log
exec > >(tee -a "$LOG") 2>&1
echo "==> Iniciando aprovisionamiento Zeuz"

BOOT=/boot
if [ -d /boot/firmware/zeuz ]; then
    BOOT=/boot/firmware
fi
PAYLOAD="$BOOT/zeuz"

report_failure() {
    STATUS=$?
    trap - ERR
    echo "ERROR: el aprovisionamiento Zeuz terminó con código $STATUS"
    cp "$LOG" "$BOOT/zeuz-firstboot-error.log" 2>/dev/null || true
    sync
    exit "$STATUS"
}
trap report_failure ERR

if [ ! -d "$PAYLOAD" ]; then
    echo "ERROR: no existe $PAYLOAD"
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> Desempaquetando dependencias ARM64 sin conexión"
# apt 3 aplica su sandbox de descarga incluso a archivos locales alojados en
# bootfs y puede rechazarlos con "Unable to fetch some archives". dpkg lee los
# paquetes directamente como root y configura después el grafo ya resuelto.
dpkg --unpack "$PAYLOAD"/debs/*.deb
echo "==> Configurando dependencias ARM64"
dpkg --configure -a
dpkg --audit

echo "==> Creando identidad local"
if ! id zeuz >/dev/null 2>&1; then
    if id pi >/dev/null 2>&1; then
        # Raspberry Pi OS conserva un usuario pi bloqueado con UID 1000. Se
        # reutiliza para no chocar con su UID durante el primer arranque.
        usermod --login zeuz --home /var/lib/zeuz --move-home --shell /bin/bash pi
        if getent group pi >/dev/null; then
            groupmod --new-name zeuz pi
        fi
    else
        # Si Imager ya creó otro usuario, Zeuz no necesita apropiarse del UID
        # 1000: un usuario de sistema dedicado es suficiente para los servicios.
        useradd --system --user-group --create-home --home-dir /var/lib/zeuz --shell /bin/bash zeuz
    fi
fi
passwd --lock zeuz
for group in dialout video render input; do
    if getent group "$group" >/dev/null; then
        usermod -a -G "$group" zeuz
    fi
done

echo "==> Habilitando configuración Wi-Fi y actualizaciones desde la pantalla"
cat >/etc/sudoers.d/90-zeuz-controls <<'EOF'
zeuz ALL=(root) NOPASSWD: /usr/bin/nmcli *, /usr/bin/systemctl start zeuz-update-apply.service
EOF
chmod 0440 /etc/sudoers.d/90-zeuz-controls

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
install -o root -g root -m 0644 /opt/zeuz/zeusdnc/VERSION /etc/zeuz/version
printf 'image-%s\n' "$(cat /etc/zeuz/version)" >/etc/zeuz/revision
if [ ! -f /var/lib/zeuz/machines.json ]; then
    install -o zeuz -g zeuz -m 0640 /opt/zeuz/zeusdnc/config/machines.json /var/lib/zeuz/machines.json
fi
for SERVICE in zeuz-dnc-qt.service zeuz-dnc-api.service \
    zeuz-update-check.service zeuz-update-apply.service; do
    install -m 0644 "$PAYLOAD/$SERVICE" "/etc/systemd/system/$SERVICE"
done

echo "==> Publicando Zeuz DNC por Bonjour"
install -d -m 0755 /etc/avahi/services
cat >/etc/avahi/services/zeuz-dnc.service <<'EOF'
<?xml version="1.0" standalone="no"?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">Zeuz DNC en %h</name>
  <service>
    <type>_zeuz-dnc._tcp</type>
    <port>5000</port>
    <txt-record>api=1</txt-record>
    <txt-record>provisioning=screen</txt-record>
  </service>
</service-group>
EOF

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

rm -f /etc/sudoers.d/90-zeuz-diagnostic
rm -f /etc/ssh/sshd_config.d/90-zeuz-diagnostic.conf
rm -f /etc/NetworkManager/system-connections/zeuz-diagnostic-hotspot.nmconnection
systemctl disable ssh.service 2>/dev/null || true
systemctl disable userconfig.service 2>/dev/null || true
systemctl enable avahi-daemon.service
systemctl disable bluetooth.service 2>/dev/null || true
systemctl disable zeuz-provisioning.service 2>/dev/null || true
systemctl enable zeuz-dnc-qt.service
systemctl enable zeuz-dnc-api.service
systemctl enable zeuz-update-check.service
systemctl set-default multi-user.target

echo "==> Limpiando el aprovisionamiento"
rm -f "$BOOT/zeuz-firstboot-error.log"
printf 'Zeuz DNC %s listo en %s\n' "$(cat /etc/zeuz/version)" \
    "$(date --iso-8601=seconds)" >"$BOOT/zeuz-firstboot-ok.txt"
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
