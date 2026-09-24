"""Bound simultaneous native cold starts without changing game requests or rules."""
import fcntl
from pathlib import Path
import time


class StartupSlots:
    def __init__(self, directory, count):
        self.directory = Path(directory)
        self.count = int(count)
        if not 1 <= self.count <= 256:
            raise ValueError("Native startup slot count must be between 1 and 256")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.held = None

    def acquire(self):
        if self.held is not None:
            raise RuntimeError("Startup slot is already held")
        while True:
            for index in range(self.count):
                stream = (self.directory / f"slot-{index}.lock").open("a+")
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    stream.close()
                    continue
                self.held = stream
                return
            time.sleep(0.2)

    def release(self):
        if self.held is not None:
            fcntl.flock(self.held, fcntl.LOCK_UN)
            self.held.close()
            self.held = None
