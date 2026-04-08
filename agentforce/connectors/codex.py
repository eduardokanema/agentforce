"""codex connector — runs prompts via the OpenAI Codex CLI."""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path


def available() -> bool:
    try:
        r = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=10)
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
    """Run codex CLI non-interactively.

    Uses quiet mode with full-auto approval so it runs without human interaction.

    Returns:
        (success, output, error, None)  — session_id always None (codex has no session API)
    """
    cmd = ["codex", "--approval-mode", "full-auto"]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)

    output_parts: list[str] = []
    timed_out = False
    try:
        proc = subprocess.Popen(
            cmd,
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
            return False, "".join(output_parts).strip(), "codex timed out", None

        error = proc.stderr.read()
        return proc.returncode == 0, "".join(output_parts).strip(), error.strip(), None
    except Exception as e:
        return False, "".join(output_parts).strip(), str(e), None
