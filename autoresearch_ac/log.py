"""Unified logging: every command writes to terminal AND timestamped log file."""

import os
import sys
from datetime import datetime
from pathlib import Path


class Logger:
    """Writes to both terminal and a log file simultaneously."""

    def __init__(self, log_dir: str = "./logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        self.log_path = self.log_dir / f"{timestamp}.log"
        self._file = open(self.log_path, "w")

        # Symlink run_latest.log → this log file
        latest = self.log_dir / "run_latest.log"
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        os.symlink(self.log_path.name, latest)

    def _ts(self):
        return datetime.now().strftime("[%H:%M:%S]")

    def log(self, msg: str = "", end: str = "\n"):
        """Write a timestamped message to both terminal and log file."""
        ts = self._ts()
        text = f"{ts} {msg}{end}" if msg else end
        sys.stdout.write(text)
        sys.stdout.flush()
        self._file.write(text)
        self._file.flush()

    def raw(self, msg: str):
        """Write a message as-is (no timestamp) — for subprocess output that has its own timestamps."""
        text = f"{msg}\n"
        sys.stdout.write(text)
        sys.stdout.flush()
        self._file.write(text)
        self._file.flush()

    def error(self, msg: str):
        """Write a timestamped error to both terminal (stderr) and log file."""
        ts = self._ts()
        text = f"{ts} ERROR: {msg}\n"
        sys.stderr.write(text)
        sys.stderr.flush()
        self._file.write(text)
        self._file.flush()

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
