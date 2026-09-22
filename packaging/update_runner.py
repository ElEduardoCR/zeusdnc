#!/usr/bin/python3
"""Root-owned bootstrap outside replaceable code; recovers interrupted installs."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

INSTALL = Path('/opt/zeuz/zeusdnc')
BACKUP = Path('/var/lib/zeuz-update-rollback')
METADATA = Path('/etc/zeuz')
SYSTEMD = Path('/etc/systemd/system')


def recover(*, install=INSTALL, backup=BACKUP, metadata=METADATA, systemd=SYSTEMD, report=None, run=subprocess.run):
    marker = backup / 'ready'
    restored = marker.exists()
    if restored:
        recovered = install.with_name(install.name + '.recover')
        shutil.rmtree(recovered, ignore_errors=True)
        shutil.copytree(backup / 'code', recovered)
        shutil.rmtree(install, ignore_errors=True)
        os.replace(recovered, install)
        units = json.loads(marker.read_text())['units']
        for name, target in [('version', metadata / 'version'), ('revision', metadata / 'revision')] + [(name, systemd / name) for name in units]:
            source = backup / name
            if source.exists(): shutil.copy2(source, target)
            else: target.unlink(missing_ok=True)
        # Before clearing the marker, flush all restored code and metadata.
        for root in (install, metadata, systemd):
            for path in root.rglob('*'):
                if path.is_file():
                    with path.open('rb') as handle: os.fsync(handle.fileno())
            for path in [p for p in root.rglob('*') if p.is_dir()] + [root]:
                descriptor = os.open(path, os.O_RDONLY)
                try: os.fsync(descriptor)
                finally: os.close(descriptor)
        marker.unlink()
    if report is None:
        sys.path.insert(0, str(install))
        from zeuz_core.deployment import phase
        from zeuz_core.updater import read_update_state
        if restored:
            phase('rolled_back', downloaded=False, available=True,
                  current_version=(metadata / 'version').read_text().strip(),
                  current_revision=(metadata / 'revision').read_text().strip(),
                  error='Se recuperó la versión anterior después de una instalación interrumpida')
        elif read_update_state().get('phase') in {'installing', 'restarting'}:
            phase('failed', downloaded=False, error='La instalación se interrumpió. Comprueba la versión antes de volver a intentar.')
    else:
        report(restored)
    if restored: run(['/usr/bin/systemctl', 'daemon-reload'], check=True)
    return restored


def main():
    if '--recover' in sys.argv:
        recover()
    else:
        sys.path.insert(0, str(INSTALL))
        from zeuz_core.deployment import apply_managed_update
        import signal
        def interrupted(signum, frame):
            raise RuntimeError("La instalación fue interrumpida por el sistema")
        previous = signal.signal(signal.SIGTERM, interrupted)
        try: print(json.dumps(apply_managed_update(), ensure_ascii=False))
        finally: signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__': main()
