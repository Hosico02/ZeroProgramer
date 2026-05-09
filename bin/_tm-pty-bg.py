#!/usr/bin/env python3
# _tm-pty-bg — daemonize, run cmd in a pty, tee output to a log file.
#
# claude CLI requires a TTY (renders status, model picker, etc). Plain
# `nohup ... &` gives it a pipe and it bails. This script forks twice,
# allocates a pty via pty.fork(), and forwards the pty master's bytes
# to a log file so the agent can run with no visible terminal.
#
# Usage:
#   _tm-pty-bg <log_file> <pid_file> <cmd> [args...]
#
# Lifecycle:
#   - parent invocation returns immediately (daemonized)
#   - <pid_file> contains the pid of the running cmd
#   - on cmd exit: pid_file is removed, log_file is closed
import os
import re
import sys
import pty
import select
import signal
import errno

# claude CLI repaints its statusline / progress UI with ANSI escapes
# (~hundreds per second). Under pty capture every redraw would land in
# the log, blowing up file size and breaking downstream consumers. Strip
# ESC sequences and stray CRs as bytes flow through.
_ANSI_RE = re.compile(
    rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][AB012]|[=>78@-Z\\-_])"
)


def _clean(buf: bytes) -> bytes:
    buf = _ANSI_RE.sub(b"", buf)
    buf = buf.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    # drop other C0 control chars except \n, \t
    return bytes(b for b in buf if b >= 0x20 or b in (0x0A, 0x09))


def daemonize():
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    # Replace 0/1/2 with /dev/null so any incidental writes don't surface.
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        try:
            os.dup2(null, fd)
        except OSError:
            pass
    os.close(null)


def main() -> int:
    if len(sys.argv) < 4:
        sys.stderr.write("usage: _tm-pty-bg <log_file> <pid_file> <cmd> [args...]\n")
        return 2

    log_path = sys.argv[1]
    pid_path = sys.argv[2]
    cmd = sys.argv[3:]

    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(pid_path) or ".", exist_ok=True)

    daemonize()

    log_fd = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)

    # Banner so the log is never empty + dates are visible on resume.
    banner = f"\n=== {os.path.basename(cmd[0])} starting at pid={os.getpid()} ===\n"
    os.write(log_fd, banner.encode())

    pid, master_fd = pty.fork()
    if pid == 0:
        # Child: become the actual command. pty.fork wired stdin/out/err
        # to the slave for us already.
        try:
            os.execvp(cmd[0], cmd)
        except Exception as e:
            sys.stderr.write(f"_tm-pty-bg: exec failed: {e}\n")
            os._exit(127)

    with open(pid_path, "w") as f:
        f.write(f"{pid}\n")

    # SIGTERM on us → propagate to child, drain pty, exit.
    def _term(_sig, _frm):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    try:
        while True:
            try:
                r, _, _ = select.select([master_fd], [], [], 1.0)
            except (InterruptedError, OSError) as e:
                if getattr(e, "errno", None) == errno.EINTR:
                    continue
                break

            if master_fd in r:
                try:
                    data = os.read(master_fd, 4096)
                except OSError as e:
                    # EIO on Linux when slave closes; treat as EOF.
                    if e.errno in (errno.EIO, errno.EBADF):
                        break
                    raise
                if not data:
                    break
                cleaned = _clean(data)
                if cleaned:
                    try:
                        os.write(log_fd, cleaned)
                    except OSError:
                        break

            try:
                wpid, _status = os.waitpid(pid, os.WNOHANG)
                if wpid != 0:
                    # Drain anything still buffered.
                    try:
                        while True:
                            data = os.read(master_fd, 4096)
                            if not data:
                                break
                            cleaned = _clean(data)
                            if cleaned:
                                os.write(log_fd, cleaned)
                    except OSError:
                        pass
                    break
            except ChildProcessError:
                break
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        os.write(log_fd, f"\n=== exited at {os.getpid()} ===\n".encode())
        try:
            os.close(log_fd)
        except OSError:
            pass
        try:
            os.remove(pid_path)
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
