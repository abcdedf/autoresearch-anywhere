"""SSH/SCP helpers for remote execution — shared across all cloud providers."""

import os
import re
import time

import paramiko


class RemoteRunner:
    """SSH connection to a cloud VM. Runs commands and transfers files."""

    def __init__(self, host: str, user: str = "ubuntu", key_path: str = None, log=None):
        self.host = host
        self.user = user
        self.key_path = key_path
        self.log = log
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def connect(self, retries: int = 12, delay: int = 10):
        """Connect with retries (VM may take a minute to boot)."""
        for attempt in range(1, retries + 1):
            try:
                kwargs = {"hostname": self.host, "username": self.user}
                if self.key_path:
                    kwargs["key_filename"] = self.key_path
                self.client.connect(**kwargs, timeout=10)
                if self.log:
                    self.log.log(f"[ssh] Connected to {self.user}@{self.host}")
                return
            except Exception as e:
                if self.log:
                    self.log.log(f"[ssh] Attempt {attempt}/{retries}: {e}")
                if attempt < retries:
                    time.sleep(delay)
        raise ConnectionError(f"Failed to SSH into {self.host} after {retries} attempts")

    def run(self, cmd: str, stream: bool = True, timeout: int = None,
            abort_event=None) -> tuple[int, str]:
        """Run a command over SSH. Streams output to log if stream=True.

        Args:
            timeout: Max seconds to wait. Command is killed if exceeded.
            abort_event: threading.Event — if set externally, kills the command.

        Returns (exit_code, full_output). Exit code -1 means timeout/aborted.
        """
        if self.log:
            self.log.log(f"  $ {cmd}")

        _, stdout, stderr = self.client.exec_command(cmd, get_pty=True)
        channel = stdout.channel
        output_lines = []
        start = time.time()
        timed_out = False
        aborted = False

        if stream:
            # Read with periodic timeout/abort checks
            channel.settimeout(5.0)  # 5s read timeout for checking abort/timeout
            while not channel.exit_status_ready():
                # Check abort event
                if abort_event and abort_event.is_set():
                    aborted = True
                    break
                # Check timeout
                if timeout and (time.time() - start) > timeout:
                    timed_out = True
                    break
                try:
                    data = channel.recv(4096)
                    if not data:
                        break
                    for line in data.decode(errors="replace").splitlines():
                        line = line.rstrip("\n\r")
                        line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                        if line:
                            output_lines.append(line)
                            if self.log:
                                self.log.raw(line)
                except Exception:
                    pass  # socket timeout — loop back and check abort/timeout

            if timed_out or aborted:
                reason = "timeout" if timed_out else "budget exceeded"
                if self.log:
                    self.log.log(f"  [ssh] Killing command ({reason})")
                channel.close()
                return -1, "\n".join(output_lines)

            # Drain remaining output
            try:
                channel.settimeout(5.0)
                while True:
                    data = channel.recv(4096)
                    if not data:
                        break
                    for line in data.decode(errors="replace").splitlines():
                        line = line.rstrip("\n\r")
                        line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                        if line:
                            output_lines.append(line)
                            if self.log:
                                self.log.raw(line)
            except Exception:
                pass
        else:
            output_lines = stdout.read().decode().splitlines()

        exit_code = stdout.channel.recv_exit_status()

        # Capture stderr if command failed
        if exit_code != 0:
            err = stderr.read().decode().strip()
            if err and self.log:
                self.log.error(err)

        return exit_code, "\n".join(output_lines)

    def upload(self, local_path: str, remote_path: str):
        """Upload a file via SFTP."""
        sftp = self.client.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()
        if self.log:
            self.log.log(f"[scp] Uploaded {os.path.basename(local_path)} → {remote_path}")

    def download(self, remote_path: str, local_path: str):
        """Download a file via SFTP."""
        sftp = self.client.open_sftp()
        sftp.get(remote_path, local_path)
        sftp.close()
        if self.log:
            self.log.log(f"[scp] Downloaded {remote_path} → {os.path.basename(local_path)}")

    def close(self):
        self.client.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()
