"""Bounded observations of an already-open serial descriptor; never reads data."""
from __future__ import annotations

import array
import fcntl
import os
import stat
import sys
import termios
import time


IS_LINUX = sys.platform.startswith("linux")
# Linux UAPI values; never used on another operating system.
TIOCOUTQ = 0x5411
TIOCINQ = 0x541B
TIOCGICOUNT = 0x545D
TIOCSERGETLSR = 0x5459
COUNTERS = ("cts", "dsr", "rng", "dcd", "rx", "tx", "frame", "overrun", "parity", "brk", "buf_overrun")
BAUD_RATES = {getattr(termios, name): int(name[1:]) for name in dir(termios)
              if name.startswith("B") and name[1:].isdigit()}


def unavailable(reason, error=None):
    result = {"available": False, "reason": reason}
    number = getattr(error, "errno", None)
    if type(number) is int:
        result["errno"] = number
    return result


def _query(work):
    try:
        return {"available": True, **work()}
    except Exception as error:  # Observability must never change transfer outcome.
        return unavailable("query_unavailable", error)


def _integer_query(fd, command, count=1):
    values = array.array("i", [0] * count)
    if values.itemsize != 4:
        raise ValueError("Unsupported integer ABI")
    fcntl.ioctl(fd, command, values, True)
    return values.tolist()


def _control_character(value):
    return value if type(value) is int else value[0]


def _termios(fd):
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(fd)
    size = cflag & termios.CSIZE
    data_bits = next((number for number in range(5, 9) if size == getattr(termios, "CS" + str(number))), None)
    parity = "N"
    if cflag & termios.PARENB:
        parity = "O" if cflag & termios.PARODD else "E"
        if cflag & getattr(termios, "CMSPAR", 0):
            parity = "M" if cflag & termios.PARODD else "S"
    return dict(iflag=int(iflag), oflag=int(oflag), cflag=int(cflag), lflag=int(lflag),
                ispeed=int(ispeed), ospeed=int(ospeed), data_bits=data_bits, parity=parity,
                input_baudrate=BAUD_RATES.get(ispeed), output_baudrate=BAUD_RATES.get(ospeed),
                stop_bits=2 if cflag & termios.CSTOPB else 1,
                ixon=bool(iflag & termios.IXON), ixoff=bool(iflag & termios.IXOFF),
                ixany=bool(iflag & getattr(termios, "IXANY", 0)),
                crtscts=bool(cflag & getattr(termios, "CRTSCTS", 0)),
                vstart=int(_control_character(cc[termios.VSTART])),
                vstop=int(_control_character(cc[termios.VSTOP])))


def _is_ftdi(fd):
    details = os.fstat(fd)
    if not stat.S_ISCHR(details.st_mode):
        return False
    path = "/sys/dev/char/{0}:{1}/device/driver".format(os.major(details.st_rdev), os.minor(details.st_rdev))
    return os.path.basename(os.readlink(path)) == "ftdi_sio"


def read_open_port(ser):
    """Caller holds the same lock used to retire the descriptor before close.

    No open/dup/read/write/flush/tcsetattr/tcflow or USB control request occurs.
    Driver-dependent queries are limited to FTDI's cached implementations.
    """
    result = {"captured_monotonic": time.monotonic()}
    if not IS_LINUX:
        return {**result, **unavailable("unsupported_platform")}
    try:
        fd = ser.fileno()
        if type(fd) is not int or fd < 0:
            raise ValueError("Descriptor unavailable")
    except Exception as error:
        return {**result, **unavailable("descriptor_unavailable", error)}
    try:
        ftdi = _is_ftdi(fd)
    except Exception:
        ftdi = False
    result.update(available=True, driver="ftdi_sio" if ftdi else "unverified",
                  termios=_query(lambda: _termios(fd)),
                  in_queue=_query(lambda: {"bytes": _integer_query(fd, TIOCINQ)[0]}))
    for field in ("out_queue", "counters", "transmitter_empty"):
        result[field] = unavailable("driver_not_verified")
    if ftdi:
        result["out_queue"] = _query(lambda: {"bytes": _integer_query(fd, TIOCOUTQ)[0]})
        result["counters"] = _query(lambda: dict(zip(COUNTERS, _integer_query(fd, TIOCGICOUNT, 20))))
        result["transmitter_empty"] = _query(lambda: {
            "empty": bool(_integer_query(fd, TIOCSERGETLSR)[0] & 1), "source": "driver_cached"})
    return result
