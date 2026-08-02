# Imagen de fábrica Zeuz DNC

Este directorio genera una imagen reproducible a partir de Raspberry Pi OS
Lite ARM64 oficial. Es compatible con Raspberry Pi 3, 4, 5 y Zero 2 W.

La imagen contiene en su partición de arranque:

- Zeuz DNC y la interfaz Qt/QML;
- dependencias ARM64 de Debian Trixie para instalación sin Internet;
- servicio `systemd`;
- aprovisionamiento automático de primer arranque;
- manifiesto con versiones y checksums.

## Construcción

Desde el entorno virtual de desarrollo:

```powershell
.\.venv\Scripts\python.exe image\build_image.py
```

El resultado se guarda en `image/dist/` junto con su SHA-256.

## Primer arranque sin pantalla

1. Graba el `.img.xz` con Raspberry Pi Imager usando **Use custom**.
2. Inserta la microSD y enciende el dispositivo Zeuz.
3. El primer arranque instala Qt y Zeuz desde la propia microSD.
4. Zeuz se reinicia automáticamente.
5. En el segundo arranque abre **WI-FI** en la pantalla táctil, elige la red e
   introduce la contraseña con el teclado flotante.
6. La pantalla muestra la dirección IP asignada y Zeuz DNC queda disponible en
   la red local por el puerto 5000.

Zeuz publica `_zeuz-dnc._tcp` por Bonjour y mantiene una API headless para
seleccionar máquina y adaptador serial, iniciar el envío, consultar el progreso
y emparejarse con Zeuz Agent. La pantalla Qt es opcional.

SSH está desactivado y no existe contraseña predeterminada. La configuración
inicial se realiza íntegramente desde la pantalla. En cada reinicio, cuando hay
red, `zeuz-update-check.service` compara la revisión instalada con la rama
`main` de GitHub. La interfaz avisa si encuentra una revisión nueva y permite
descargarla e instalarla de forma transaccional.

Cada equipo recibe un hostname `zeuz-dnc-XXXXXX` derivado de su número de
serie.

La imagen arranca con programas locales vacíos. Desde **AJUSTES** puede
introducirse la dirección de ZeuzAgent y su código de seis dígitos. La
configuración se guarda en `/var/lib/zeuz/runtime.json` y se conserva entre
reinicios.
