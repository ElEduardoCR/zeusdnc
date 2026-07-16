#!/bin/bash
# Espera a que el backend Flask (servicio systemd dnc-backend) responda y
# entonces abre Chromium en modo kiosko apuntando a la interfaz DNC.

URL="http://localhost:5000"

# El binario de Chromium cambia de nombre segun la version de Raspberry Pi
# OS: en Bookworm suele ser "chromium", en versiones viejas
# "chromium-browser". Se detecta el que exista para no depender de un
# nombre fijo.
if command -v chromium >/dev/null 2>&1; then
  BROWSER=chromium
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER=chromium-browser
else
  echo "kiosk.sh: no se encontro 'chromium' ni 'chromium-browser'" >&2
  exit 1
fi

for i in $(seq 1 60); do
  if curl -s -o /dev/null "$URL"; then
    break
  fi
  sleep 1
done

# --disable-features=Translate quita el globo de "?Traducir esta pagina?" que
# Chromium muestra arriba a la derecha al detectar la interfaz en espanol; en
# kiosko no hay forma comoda de cerrarlo. --no-first-run evita los dialogos de
# bienvenida si el perfil se crea de cero.
exec "$BROWSER" --kiosk --incognito --disable-infobars --noerrdialogs \
  --disable-session-crashed-bubble --disable-features=Translate --no-first-run "$URL"
