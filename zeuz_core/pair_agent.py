from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from .settings import DEFAULT_SETTINGS_PATH


def pair(base_url: str, code: str) -> dict:
    url = base_url.rstrip("/") + "/v1/pair"
    payload = json.dumps({"code": code}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get("error", str(exc))
        except Exception:
            detail = str(exc)
        raise RuntimeError(detail) from exc
    except OSError as exc:
        raise RuntimeError(f"No se pudo contactar Zeuz Agent en {base_url}") from exc


def write_runtime(path: Path, base_url: str, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "program_source": {
                    "type": "agent",
                    "url": base_url.rstrip("/"),
                    "token": token,
                }
            },
            handle,
            indent=2,
            ensure_ascii=False,
        )
        handle.write("\n")
    tmp.replace(path)


def write_local_runtime(path: Path, local_path: str = "/var/lib/zeuz/programs") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "program_source": {
                    "type": "local",
                    "path": local_path,
                }
            },
            handle,
            indent=2,
            ensure_ascii=False,
        )
        handle.write("\n")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emparejar Zeuz DNC con Zeuz Agent")
    parser.add_argument("url", help="por ejemplo http://192.168.1.20:47820")
    parser.add_argument("code", help="código de seis dígitos mostrado por Zeuz Agent")
    parser.add_argument("--output", type=Path, default=DEFAULT_SETTINGS_PATH)
    args = parser.parse_args(argv)

    result = pair(args.url, args.code)
    write_runtime(args.output, args.url, result["token"])
    print(f"Emparejado con {result.get('agent_name', 'Zeuz Agent')}")
    print(f"Configuración guardada en {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
