# DNC — Transferencia de programas CNC vía RS232

Sistema para Raspberry Pi con pantalla táctil que transfiere programas
G-code desde una carpeta compartida (Samba) a una máquina CNC por
RS232/serial, en modo "punch" (transferencia completa a memoria, no
drip-feed).

## Estructura del proyecto

```
ZeuzDNC/
  app.py                  Backend Flask (rutas API + arranque de monitores)
  state.py                Estado compartido en memoria (thread-safe)
  machines.py             Carga de perfiles de máquina desde config/machines.json
  usb_monitor.py          Detección en tiempo real del adaptador USB-RS232 (pyudev)
  folder_monitor.py        Monitoreo en tiempo real de /home/eduardo/cnc-programs (watchdog)
  serial_transfer.py       Apertura de puerto serial + envío del archivo + progreso
  config/machines.json     Perfiles de máquina editables (JSON)
  templates/index.html     Interfaz táctil
  static/css/style.css
  static/js/app.js
  systemd/dnc-backend.service   Unit de systemd para el backend
  autostart/dnc-kiosk.desktop   Entrada de autostart del escritorio (labwc/XDG)
  autostart/kiosk.sh            Script que espera al backend y lanza Chromium en kiosko
```

## 1. Copiar el proyecto a la Raspberry Pi

Copia toda la carpeta `ZeuzDNC/` a `/home/eduardo/ZeuzDNC` (por ejemplo con
`scp -r ZeuzDNC eduardo@<ip-pi>:/home/eduardo/`).

Las dependencias de Python (`flask`, `pyserial`, `watchdog`, `pyudev`) ya
están instaladas según el entorno preparado. Si hiciera falta reinstalarlas:

```bash
pip3 install --break-system-packages -r /home/eduardo/ZeuzDNC/requirements.txt
```

## 2. Perfiles de máquina (`config/machines.json`)

Los valores de **Fanuc** (4800 baud, 7E2, XON/XOFF, CR) y **Fadal** (9600
baud, 8N1, XON/XOFF, CRLF) son valores típicos de referencia para dejar el
sistema funcionando de inmediato — **confírmalos contra el manual de cada
control antes de usarlos en producción**, y ajústalos editando el JSON
directamente (no hace falta tocar código):

```json
{
  "id": "fanuc",
  "name": "Fanuc",
  "baudrate": 4800,
  "bytesize": 7,
  "parity": "E",
  "stopbits": 2,
  "flow_control": "xonxoff",
  "line_terminator": "CR"
}
```

- `parity`: `"N"`, `"E"`, `"O"`, `"M"` o `"S"`.
- `stopbits`: `1` o `2`.
- `flow_control`: `"xonxoff"` o `"rtscts"`.
- `line_terminator`: `"CR"` o `"CRLF"`.

Para agregar una máquina nueva, agrega otro objeto al arreglo `machines`
con un `id` único. Los cambios se leen del disco en cada consulta, así que
no hace falta reiniciar el servicio para que aparezcan.

## 3. Instalar el servicio systemd del backend

```bash
sudo cp /home/eduardo/ZeuzDNC/systemd/dnc-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dnc-backend.service
sudo systemctl start dnc-backend.service
```

Verificar que corre y ver logs:

```bash
systemctl status dnc-backend.service
journalctl -u dnc-backend.service -f
```

El servicio arranca solo al boot (`enable`) y se reinicia solo si falla
(`Restart=always`).

## 4. Autostart de Chromium en modo kiosko

```bash
chmod +x /home/eduardo/ZeuzDNC/autostart/kiosk.sh
mkdir -p /home/eduardo/.config/autostart
cp /home/eduardo/ZeuzDNC/autostart/dnc-kiosk.desktop /home/eduardo/.config/autostart/
```

Al iniciar sesión en el escritorio, `kiosk.sh` espera a que
`http://localhost:5000` responda y luego abre Chromium en pantalla
completa sobre esa URL. Si el binario en tu instalación se llama
`chromium` en lugar de `chromium-browser`, edita esa línea en
`autostart/kiosk.sh`.

## 5. Probar todo el flujo

1. Reinicia la Pi (`sudo reboot`) o al menos la sesión de escritorio.
2. Debe aparecer Chromium en kiosko mostrando "Conecta el adaptador RS232".
3. Copia un programa a la carpeta compartida `cnc-programs` desde
   Windows/Mac (vía el share Samba) y confirma que aparece solo en la
   lista sin recargar la página.
4. Conecta el adaptador USB-RS232: la pantalla debe pasar de inmediato a
   pedir la máquina, mostrando los perfiles configurados como botones
   grandes.
5. Toca un perfil (p. ej. Fanuc): la pantalla pasa a la lista de
   archivos.
6. Selecciona un archivo, toca **ENVIAR**, confirma en el modal — recién
   ahí se transmite. Debe verse la barra de progreso y al final un
   mensaje de éxito o error.
7. Desconecta el adaptador USB: la interfaz debe volver a "Conecta el
   adaptador RS232" y olvidar la máquina activa.

Para pruebas de escritorio sin hardware serial real, se puede usar un par
de pseudo-terminales (`socat -d -d pty,raw,echo=0 pty,raw,echo=0`) para
simular un puerto serial y verificar que la transferencia y el progreso
funcionan antes de conectar una máquina real.

## Notas de diseño

- El adaptador USB-RS232 nunca se hardcodea a una ruta: se detecta por
  eventos udev (`usb_monitor.py`) cada vez que se conecta o desconecta,
  y cada conexión nueva vuelve a pedir la máquina (aunque sea el mismo
  adaptador).
- El envío es siempre una acción manual explícita del usuario
  (botón **ENVIAR** + confirmación); la app nunca transmite un archivo
  solo porque apareció en la carpeta.
- El control de flujo (XON/XOFF o RTS/CTS) lo maneja el driver serial del
  sistema operativo (vía pyserial/termios) al abrir el puerto con esos
  flags activados; la transmisión se pausa sola si la máquina manda XOFF.
- La conversión de fin de línea (CR o CRLF) se aplica al contenido del
  archivo justo antes de enviarlo, sin modificar el archivo original en
  la carpeta compartida.
