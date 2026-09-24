"""Linux exec launcher: terminate the managed host if its owning worker dies."""
import ctypes
import os
import signal
import sys


def main():
    expected_parent = int(sys.argv[1])
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    # The worker might have died before prctl installed the signal.
    if os.getppid() != expected_parent:
        return 125
    os.execv(sys.argv[2], sys.argv[2:])


if __name__ == '__main__':
    sys.exit(main())
