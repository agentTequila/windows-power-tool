import subprocess
from typing import NamedTuple, Sequence

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

POWERSHELL: list[str] = [
    "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
]


class Result(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


def _decode(data) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def run(args: Sequence[str], timeout: int = 120) -> Result:
    try:
        cp = subprocess.run(list(args), capture_output=True, timeout=timeout,
                            creationflags=CREATE_NO_WINDOW)
        return Result(cp.returncode, _decode(cp.stdout), _decode(cp.stderr))
    except subprocess.TimeoutExpired:
        return Result(-1, "", f"Command timed out after {timeout}s")
    except OSError as exc:
        return Result(-1, "", str(exc))


def run_powershell(script: str, timeout: int = 300) -> Result:
    return run(POWERSHELL + [script], timeout=timeout)


def start_detached(args: Sequence[str]) -> int:
    proc = subprocess.Popen(list(args))
    return proc.pid
