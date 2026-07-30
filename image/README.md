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

## Primer arranque

1. Graba el `.img.xz` con Raspberry Pi Imager usando **Use custom**.
2. Inserta la microSD y enciende la Raspberry.
3. El primer arranque instala Qt y Zeuz desde la propia microSD.
4. La Raspberry se reinicia automáticamente.
5. En el segundo arranque abre Zeuz DNC a pantalla completa.

No existe contraseña predeterminada y SSH está desactivado. El usuario local
`zeuz` está bloqueado y se usa únicamente para ejecutar el servicio. Cada
equipo recibe un hostname `zeuz-dnc-XXXXXX` derivado de su número de serie.

La imagen arranca con programas locales vacíos. Desde **AJUSTES** puede
introducirse la dirección de ZeuzAgent y su código de seis dígitos. La
configuración se guarda en `/var/lib/zeuz/runtime.json` y se conserva entre
reinicios.
