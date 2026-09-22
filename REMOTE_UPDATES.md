# Actualizaciones remotas de ZeuzDNC

La versión 0.7.0 agrega gestión OTA a Raspberry Pi y Orange Pi sin depender de una pantalla. Agent y el iPhone muestran la versión disponible, solicitan la instalación y consultan su avance. Después de aceptar la solicitud, la Pi termina el trabajo aunque el cliente se desconecte.

## Uso

1. En Agent, busca el equipo y usa **Vincular** si aún no autoriza a este Agent. La vinculación de actualizaciones conserva el origen de programas configurado.
2. Pulsa **Comprobar** y luego **Actualizar**. En el iPhone están en **Estado de Zeuz**, dentro de la tarjeta de cada equipo.
3. La Pi espera cualquier envío activo, descarga la revisión seleccionada, verifica su procedencia, instala y reinicia los servicios. Las interfaces vuelven a consultar el estado al reconectarse.
4. **Actualizar automáticamente** es una opción por equipo, desactivada de fábrica. Si se activa, la Pi comprueba el canal cada seis horas y prepara la instalación cuando está libre. Un fallo no produce un bucle de reinstalación de la misma revisión.

La primera instalación del firmware compatible es distinta de OTA: los equipos antiguos no tienen un endpoint capaz de instalar este servicio. Detectar una Pi 0.6.0 no permite introducirle OTA por HTTP. Requieren una imagen con el servicio o un acceso administrativo previamente habilitado; después operan desde Agent/iPhone sin terminal ni SSH.

## Contrato

`/api/info` publica `capabilities.remote_update = 1` y un resumen sin credenciales. La API de gestión exige el token del Agent originalmente vinculado, guardado en `runtime.json` como `paired_agent` (compatible con `program_source.token`). Una credencial móvil reemplazada no autoriza OTA. Cambiar la vinculación o las rutas del taller de un dispositivo ya vinculado también exige ese token. La información pública no expone el código móvil de vinculación.

- `GET /api/update/status`: estado, versiones, revisión disponible, descarga, política y actividad.
- `POST /api/update/check` con `{}`: búsqueda asíncrona.
- `POST /api/update/install` con `revision` de 40 dígitos hexadecimales y `request_id` UUID: instala la revisión anunciada; repetir la misma solicitud devuelve el mismo trabajo.
- `POST /api/update/policy` con `auto_install` booleano: cambia la opción explícita del equipo.

Agent expone los mismos comandos bajo `/v1/dnc/update/`, seleccionando el dispositivo mediante `machine_id`. El servidor de programas en la Pi mantiene ese contrato cuando la computadora no está. Un POST cuya respuesta se pierde no se reproduce automáticamente contra otro destino; primero se consulta el estado.

Fases: `idle`, `checking`, `available`, `waiting_idle`, `downloading`, `installing`, `restarting`, `succeeded`, `rolled_back`, `failed`. Los errores y la fase se conservan en `/var/lib/zeuz/update.json`; la política se guarda en `update-policy.json`. La interfaz conserva el último estado durante una pérdida de conexión.

## Instalación y recuperación

El canal predeterminado es `ElEduardoCR/zeusdnc`, rama `main`. El cliente no puede proporcionar repositorios, URL, scripts ni unidades systemd. El instalador privilegiado vuelve a comprobar el commit publicado y VERSION por HTTPS, rechaza retrocesos, descarga una copia privada del archivo oficial y compara SHA-256. No extrae el archivo mutable preparado por el API. Se rechazan rutas inseguras, enlaces, dispositivos, archivos incompletos y tamaños excesivos. Si main cambió desde la comprobación, se requiere comprobar de nuevo.

El servicio API permanece con el usuario `zeuz` y `NoNewPrivileges`. La regla de polkit permite únicamente iniciar `zeuz-update-apply.service`; no da acceso general a systemd ni a sudo. Todas las rutas de envío serial adquieren un bloqueo compartido entre procesos; la instalación necesita el bloqueo exclusivo. Así no reinicia servicios durante un envío ni permite iniciar un envío a mitad de la instalación.

Antes de sustituir código se guarda una copia root de código, unidades, versión y revisión en `/var/lib/zeuz-update-rollback`, con un marcador sólo después de sincronizar los datos a disco. El éxito requiere que la nueva API responda en localhost con su versión. Si falla, se restaura la copia anterior. Programas, perfiles, runtime, historial y credenciales quedan fuera del árbol de código reemplazado.

El runner root `/usr/local/lib/zeuz/update_runner.py` vive fuera del árbol sustituido. `zeuz-update-recover.service` restaura una instalación interrumpida antes de arrancar API/QT. API, QT y apply requieren recovery; recovery usa `RemainAfterExit=yes` para no deshacer una instalación en curso cuando el instalador arranca la API para comprobarla. La interfaz táctil sólo se reinicia si estaba activa.

Las imágenes deben instalar `polkitd`, la regla `packaging/49-zeuz-updates.rules`, el runner y las unidades de `systemd/`; habilitar recovery y API; guardar VERSION y el commit de origen en `/etc/zeuz`. La ruta inicial de Raspberry y la receta de Orange Pi incluyen estos archivos. Las dependencias nuevas de futuras versiones requieren una estrategia de imagen/paquetes: este actualizador sustituye código y unidades, no ejecuta apt ni scripts enviados por el cliente.

## Validación local

`tests/test_remote_updates.py` usa HTTP loopback real, archivos temporales y un proceso separado para los bloqueos. Comprueba autorización, protección de vinculación/rutas, rechazo de URL/revisión ajenas, opción automática, idempotencia, espera de envíos, continuación sin cliente, puente Agent/Pi, hashes, instalación sin pantalla, rollback completo y recuperación de arranque sin importar el código roto. GitHub, servicios y hardware se simulan: estas pruebas no reinician Pi ni envían programas CNC.

La validación física de polkit/systemd, corte de energía y reinstalación inicial sigue correspondiendo a una Pi de prueba con la imagen final. La compilación y las pruebas locales no sustituyen esa validación en hardware.
