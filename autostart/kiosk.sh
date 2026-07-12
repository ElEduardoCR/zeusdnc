#!/bin/bash
# Espera a que el backend Flask (servicio systemd dnc-backend) responda y
# entonces abre Chromium en modo kiosko apuntando a la interfaz DNC.

URL="http://localhost:5000"

for i in $(seq 1 60); do
  if curl -s -o /dev/null "$URL"; then
    break
  fi
  sleep 1
done

exec chromium-browser --kiosk --incognito --disable-infobars --noerrdialogs --disable-session-crashed-bubble "$URL"
