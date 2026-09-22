"""Cross-process exclusion: installation must never interrupt an RS232 send."""
import fcntl
import os
import pwd
from pathlib import Path

LOCK_PATH = Path(os.environ.get("ZEUZ_OPERATION_LOCK", "/var/lib/zeuz/operation.lock"))


class Busy(RuntimeError):
    status = 409


class OperationLease:
    def __init__(self, *, update=False, path=None):
        target = path or LOCK_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        self.handle = target.open("a+")
        if os.geteuid() == 0:
            try:
                account = pwd.getpwnam("zeuz")
                os.fchown(self.handle.fileno(), account.pw_uid, account.pw_gid)
                os.fchmod(self.handle.fileno(), 0o660)
            except KeyError:
                pass
        try:
            fcntl.flock(self.handle, (fcntl.LOCK_EX if update else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            raise Busy("Hay un envío o una actualización en curso; se esperará a que termine")

    def close(self):
        if not self.handle.closed:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def transfer_active():
    try:
        with OperationLease(update=True):
            return False
    except Busy:
        return True
