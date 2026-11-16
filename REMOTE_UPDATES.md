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

## Reparación local Orange 0.7.2: reloj y diagnóstico

Esta copia conserva la base `641297a9a71be726c7feb47d25ec6090f30bd106` y no implica
una publicación en GitHub. Incluye un servicio de reloj limitado, independiente
de TLS, autorizado únicamente con el token del Agent vinculado:

- `GET /api/system/clock/status`: `supported`, `utc_unix`, `utc`, `phase`,
  `request_id`, `error`. Las fases son `idle`, `pending`, `succeeded`, `failed`.
- `POST /api/system/clock/sync`: cuerpo exacto
  `{"utc_unix": <segundos UTC enteros>, "request_id": "<UUID>"}`. Un identificador
  repetido con la misma hora devuelve su resultado sin volver a ajustar el reloj.
- `GET /api/system/diagnostics`: estado del envío y hasta 32 KiB / 200 líneas del
  registro serial actual y su primera rotación; nunca configuración o credenciales.

La API escribe únicamente una solicitud pequeña en el buzón fijo y solicita
iniciar `zeuz-clock-sync.service`. El helper root vuelve a validar el archivo
regular, propietario, tamaño, UUID, mismo arranque y antigüedad monotónica menor
de 60 segundos. Acepta años 2020 a 2099, adelantos máximos de cinco años y
retrocesos máximos de cinco minutos. Adquiere el bloqueo exclusivo de operación,
por lo que no cambia la hora durante envío o instalación. Sólo confirma éxito
después de ajustar el reloj y sincronizar a disco `fake-hwclock.data` y el estado
de timesync. TLS siempre conserva la validación de certificados.

Instalación controlada sobre la SD identificada y respaldada:

1. Instalar `packaging/clock_runner.py` como
   `/usr/local/lib/zeuz/clock_runner.py`, root:root, 0755; su directorio padre
   tampoco debe ser escribible por `zeuz`.
2. Crear `/var/lib/zeuz-clock` root:root 0755, `inbox` zeuz:zeuz 0700 y
   `results.json` con `[]`, root:root 0644. Conservar propietario y modo del
   `/var/lib/zeuz/operation.lock` existente; debe ser archivo regular accesible
   para escritura por `zeuz`. El helper no lo crea ni cambia su propietario.
3. Instalar la unidad fija y la regla polkit limitada. La unidad es oneshot y no
   se habilita al inicio. Para la API Orange real, que usa `ProtectSystem=strict`,
   añadir un drop-in que amplíe `ReadWritePaths` sólo con
   `/var/lib/zeuz-clock/inbox`; conservar su unidad y demás restricciones.
4. Sembrar con UTC actual los archivos regulares `/etc/fake-hwclock.data` y
   `/var/lib/systemd/timesync/clock`, conservando sus propietarios. Mantener NTP
   habilitado. Estos archivos deben existir antes de ejecutar la unidad.
5. Tras arrancar, comprobar autorización, resultado del reloj, persistencia,
   bloqueo durante un envío simulado y consulta OTA con certificados válidos.

El helper, la unidad y polkit quedan fuera del árbol reemplazado por OTA. Una
versión futura del firmware debe conservar las rutas de administración para
seguir exponiendo esta capacidad. No se modifica la preferencia de instalación
automática del usuario. Un fallo anterior al comprobar actualizaciones ya no
oculta una comprobación posterior exitosa; los fallos de instalación se conservan
para evitar reintentos automáticos de la misma revisión.

## Diagnóstico local 0.7.3: envío detenido

Preparación local del 16 de noviembre de 2026 sobre la reparación 0.7.2, sin
publicación ni instalación implícita. Conserva los bytes preparados, parámetros
seriales, bloques de 256 bytes, timeout de escritura de 120 segundos, pausas,
comportamiento de cancelación y margen de cierre anteriores.

El GET autenticado `/api/system/diagnostics` añade `serial`:

- `phase`: `idle`, `prepare`, `open`, `control_lines`, `write`, `drain`, `closing`
  o `finished`; `transfer_id`, `bytes_queued`, `total_bytes` y `outcome`.
- Tiempos monotónicos de inicio, última escritura aceptada o reducción de cola,
  comienzo de la escritura actual, detección de error e inicio/fin del cierre.
  `failure_phase` conserva la fase del error aunque la fase actual sea `closing`.
- `observation`, `baseline` y `last_observation`: configuración leída con
  `tcgetattr` (TCGETS en Linux), cola de entrada TIOCINQ, y, sólo al verificar
  `ftdi_sio` en sysfs, cola de salida TIOCOUTQ, contadores TIOCGICOUNT y TEMT
  cacheado del driver mediante TIOCSERGETLSR. Los códigos de velocidad originales
  se acompañan de su baudrate cuando termios permite identificarlos.

Las consultas usan exclusivamente el descriptor abierto por el envío. No abren
otro puerto, duplican descriptores, consumen RX, modifican atributos, fuerzan XON,
vacían buffers ni envían consultas USB de control como TIOCMGET. Un ioctl ausente
o fallido se representa como `available: false` con razón fija y errno numérico;
no modifica el resultado del envío. El esquema tiene campos fijos y no contiene
programas, rutas de programas ni credenciales. Si la observación está ocupada,
la consulta retorna `busy` tras un máximo de 20 ms esperando el bloqueo.

Antes del cierre se toma la última observación, se retira el descriptor bajo el
mismo bloqueo y se publica `closing`. El log acotado registra ese punto y un
timeout ya detectado antes de entrar a `Serial.__exit__`; el cierre y el log no
retienen el bloqueo de observación/cancelación. El registro conserva sólo tres
eventos por envío abierto: inicio, precierre y resultado terminal, sin sondeo
periódico ni eventos por bloque. Un cierre aún bloqueado conserva la evidencia
de precierre para la siguiente consulta remota.

Estos datos no confirman recepción de la CNC: `bytes_queued` cuenta escrituras
aceptadas por el sistema; la cola y TEMT son información del driver; los errores
de paridad RX corresponden a CNC→adaptador. Ninguno demuestra por sí solo que la
pausa sea causada por XOFF. La distribución sigue requiriendo revisar el canal
OTA y las unidades instaladas del equipo; esta preparación no los cambia.
