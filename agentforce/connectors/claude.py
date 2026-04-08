"""claude connector — runs prompts via the Claude Code CLI."""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path


def available() -> bool:
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run(
    prompt: str,
    workdir: str,
    timeout: int = 300,
    model: str = None,
    stream_path: Path = None,
    variant: str = None,
    session_id: str = None,
) -> tuple[bool, str, str, None]:
    """Run claude CLI non-interactively.

    Returns:
        (success, output, error, None)  — session_id always None (claude handles state internally)
    """
    cmd = ["claude", "--dangerously-skip-permissions", "-p", "--output-format", "text"]
    if model:
        cmd += ["--model", model]

    output_parts: list[str] = []
    timed_out = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workdir,
            env=os.environ.copy(),
        )

        def _kill():
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()
        sf = open(stream_path, "a", encoding="utf-8") if stream_path else None
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
            for line in proc.stdout:
                output_parts.append(line)
                if sf:
                    sf.write(line)
                    sf.flush()
            proc.wait()
        finally:
            timer.cancel()
            if sf:
                sf.close()

        if timed_out:
            return False, "".join(output_parts).strip(), "claude timed out", None
        stderr = proc.stderr.read()
        return proc.returncode == 0, "".join(output_parts).strip(), stderr.strip(), None
    except Exception as e:
        return False, "".join(output_parts).strip(), str(e), None
