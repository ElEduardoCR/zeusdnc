from __future__ import annotations

import json
import signal
import sys

from .controller import ProvisioningController


BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
AGENT_MANAGER_IFACE = "org.bluez.AgentManager1"
AGENT_IFACE = "org.bluez.Agent1"

SERVICE_UUID = "7c1e0001-7a6b-4f8a-9d0e-5e7a45555a31"
STATUS_UUID = "7c1e0002-7a6b-4f8a-9d0e-5e7a45555a31"
COMMAND_UUID = "7c1e0003-7a6b-4f8a-9d0e-5e7a45555a31"
VISIBLE_NAME = "zeuz"


def _imports():
    try:
        import dbus
        import dbus.mainloop.glib
        import dbus.service
        from gi.repository import GLib
    except ImportError as exc:
        raise RuntimeError("Faltan dbus-python/PyGObject para iniciar BLE") from exc
    return dbus, GLib


def _adapter_path(bus, interface: str) -> str:
    objects = bus.get_object(BLUEZ_SERVICE_NAME, "/").GetManagedObjects(
        dbus_interface=DBUS_OM_IFACE
    )
    for path, interfaces in objects.items():
        if interface in interfaces:
            return str(path)
    raise RuntimeError(f"BlueZ no expone {interface}")


def main() -> int:
    dbus, GLib = _imports()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter_path = _adapter_path(bus, GATT_MANAGER_IFACE)
    adapter = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
    properties = dbus.Interface(adapter, DBUS_PROP_IFACE)
    properties.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
    properties.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
    properties.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True))

    controller = ProvisioningController()
    application = Application(bus, controller, dbus)
    advertisement = Advertisement(bus, 0, VISIBLE_NAME, dbus)
    agent = PairingAgent(bus, dbus)

    agent_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez"), AGENT_MANAGER_IFACE
    )
    try:
        agent_manager.RegisterAgent(agent.path, "NoInputNoOutput")
    except dbus.exceptions.DBusException as exc:
        if "AlreadyExists" not in str(exc):
            raise
    agent_manager.RequestDefaultAgent(agent.path)

    gatt_manager = dbus.Interface(adapter, GATT_MANAGER_IFACE)
    ad_manager = dbus.Interface(adapter, LE_ADVERTISING_MANAGER_IFACE)
    loop = GLib.MainLoop()
    registration = {"gatt": False, "advertisement": False, "error": False}

    def registration_failed(stage: str, error) -> None:
        registration["error"] = True
        print(f"No se pudo registrar {stage} en BlueZ: {error}", file=sys.stderr)
        loop.quit()

    def advertisement_failed(error) -> None:
        # El anuncio y la aplicación GATT son registros independientes. Si el
        # controlador rechaza temporalmente el anuncio, conservar GATT permite
        # que un central que ya conoce el nombre de la Pi se conecte y evita el
        # ciclo registrar/desregistrar que dejaba visible sólo el servicio 180A.
        print(f"No se pudo registrar el anuncio BLE en BlueZ: {error}", file=sys.stderr)

    def advertisement_registered() -> None:
        registration["advertisement"] = True
        print("Anuncio BLE Zeuz registrado", flush=True)

    def gatt_registered() -> None:
        registration["gatt"] = True
        print("Aplicación GATT Zeuz registrada", flush=True)
        ad_manager.RegisterAdvertisement(
            advertisement.path,
            {},
            reply_handler=advertisement_registered,
            error_handler=advertisement_failed,
        )

    def begin_registration() -> bool:
        # RegisterApplication hace introspección de vuelta hacia este proceso.
        # Debe ser asíncrono y ejecutarse con el GLib loop activo para evitar
        # que BlueZ y dbus-python se esperen mutuamente.
        gatt_manager.RegisterApplication(
            application.path,
            {},
            reply_handler=gatt_registered,
            error_handler=lambda error: registration_failed("la aplicación GATT", error),
        )
        return False

    def stop_after_provisioning(snapshot):
        if snapshot.get("state") == "connected":
            # Deja tiempo para que iOS reciba la IP y cambie a la API de red.
            GLib.timeout_add_seconds(60, lambda: (loop.quit(), False)[1])

    controller.add_listener(stop_after_provisioning)
    signal.signal(signal.SIGTERM, lambda *_: loop.quit())
    signal.signal(signal.SIGINT, lambda *_: loop.quit())
    GLib.idle_add(begin_registration)
    loop.run()
    if registration["advertisement"]:
        try:
            ad_manager.UnregisterAdvertisement(advertisement.path)
        except Exception:
            pass
    if registration["gatt"]:
        try:
            gatt_manager.UnregisterApplication(application.path)
        except Exception:
            pass
    return 1 if registration["error"] else 0


class Application:
    path = "/com/zeuz/provision"

    def __new__(cls, bus, controller, dbus):
        class Impl(dbus.service.Object):
            path = cls.path

            def __init__(self):
                super().__init__(bus, self.path)
                self.service = Service(bus, 0, controller, dbus)

            @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
            def GetManagedObjects(self):
                objects = {self.service.path: self.service.properties()}
                for characteristic in self.service.characteristics:
                    objects[characteristic.path] = characteristic.properties()
                return objects

        return Impl()


class Service:
    def __new__(cls, bus, index, controller, dbus):
        class Impl(dbus.service.Object):
            def __init__(self):
                self.path = f"/com/zeuz/provision/service{index}"
                super().__init__(bus, self.path)
                self.characteristics = [
                    StatusCharacteristic(bus, 0, self, controller, dbus),
                    CommandCharacteristic(bus, 1, self, controller, dbus),
                ]

            def properties(self):
                return {
                    GATT_SERVICE_IFACE: {
                        "UUID": dbus.String(SERVICE_UUID),
                        "Primary": dbus.Boolean(True),
                        "Includes": dbus.Array([], signature="o"),
                    }
                }

            @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):
                if interface != GATT_SERVICE_IFACE:
                    raise ValueError("Interfaz desconocida")
                return self.properties()[GATT_SERVICE_IFACE]

        return Impl()


def StatusCharacteristic(bus, index, service, controller, dbus):
    class Impl(dbus.service.Object):
        def __init__(self):
            self.path = f"{service.path}/char{index}"
            self.notifying = False
            super().__init__(bus, self.path)
            controller.add_listener(self._changed)

        def properties(self):
            return {
                GATT_CHRC_IFACE: {
                    "Service": dbus.ObjectPath(service.path),
                    "UUID": dbus.String(STATUS_UUID),
                    "Flags": dbus.Array(["read", "notify", "encrypt-read"], signature="s"),
                    "Descriptors": dbus.Array([], signature="o"),
                }
            }

        @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return self.properties()[GATT_CHRC_IFACE]

        @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
        def ReadValue(self, options):
            return dbus.Array(controller.encoded_snapshot(), signature="y")

        @dbus.service.method(GATT_CHRC_IFACE)
        def StartNotify(self):
            self.notifying = True
            self._emit(controller.encoded_snapshot())

        @dbus.service.method(GATT_CHRC_IFACE)
        def StopNotify(self):
            self.notifying = False

        @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
        def PropertiesChanged(self, interface, changed, invalidated):
            pass

        def _changed(self, snapshot):
            if self.notifying:
                payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
                self._emit(payload)

        def _emit(self, payload):
            self.PropertiesChanged(
                GATT_CHRC_IFACE,
                {"Value": dbus.Array(payload, signature="y")},
                [],
            )

    return Impl()


def CommandCharacteristic(bus, index, service, controller, dbus):
    class Impl(dbus.service.Object):
        def __init__(self):
            self.path = f"{service.path}/char{index}"
            super().__init__(bus, self.path)

        def properties(self):
            return {
                GATT_CHRC_IFACE: {
                    "Service": dbus.ObjectPath(service.path),
                    "UUID": dbus.String(COMMAND_UUID),
                    "Flags": dbus.Array(["write", "encrypt-write"], signature="s"),
                    "Descriptors": dbus.Array([], signature="o"),
                }
            }

        @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return self.properties()[GATT_CHRC_IFACE]

        @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
        def WriteValue(self, value, options):
            ok, message = controller.handle_command(bytes(value))
            if not ok:
                raise dbus.exceptions.DBusException(
                    "com.zeuz.InvalidProvisioningRequest", message
                )

    return Impl()


class Advertisement:
    def __new__(cls, bus, index, local_name, dbus):
        class Impl(dbus.service.Object):
            def __init__(self):
                self.path = f"/com/zeuz/provision/advertisement{index}"
                self.local_name = local_name
                super().__init__(bus, self.path)

            @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):
                # No combinar el nombre con el UUID de 128 bits: esa mezcla
                # llenaba el anuncio legado y algunos controladores la
                # rechazaban. iOS reconoce el nombre corto y descubre GATT al
                # conectarse.
                return {
                    "Type": dbus.String("peripheral"),
                    "LocalName": dbus.String(self.local_name),
                }

            @dbus.service.method(LE_ADVERTISEMENT_IFACE)
            def Release(self):
                pass

        return Impl()


class PairingAgent:
    path = "/com/zeuz/provision/agent"

    def __new__(cls, bus, dbus):
        class Impl(dbus.service.Object):
            path = cls.path

            def __init__(self):
                super().__init__(bus, self.path)

            @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="")
            def RequestAuthorization(self, device):
                return

            @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
            def AuthorizeService(self, device, uuid):
                return

            @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
            def Cancel(self):
                return

            @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
            def Release(self):
                return

        return Impl()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"No se pudo iniciar el aprovisionamiento BLE: {exc}", file=sys.stderr)
        raise
