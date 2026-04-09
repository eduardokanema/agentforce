from __future__ import annotations

import json
from pathlib import Path

AGENTFORCE_HOME = Path("~/.agentforce").expanduser()


def is_review_enabled() -> bool:
    config_file = AGENTFORCE_HOME / "config.json"
    if not config_file.exists():
        return True
    return json.loads(config_file.read_text()).get("review_enabled", True)
