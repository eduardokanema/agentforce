import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentforce.core.destructive_actions import parse_destructive_action_request


def test_parse_destructive_action_request_from_warning_fence():
    output = """
I need approval before continuing.

```agentforce-warning
{
  "type": "destructive_action_request",
  "summary": "Delete stale generated files",
  "risk": "This removes files from the workspace.",
  "proposed_action": "rm -rf dist",
  "targets": ["dist"],
  "action_key": "delete:dist"
}
```
"""

    request = parse_destructive_action_request(output)

    assert request == {
        "type": "destructive_action_request",
        "summary": "Delete stale generated files",
        "risk": "This removes files from the workspace.",
        "proposed_action": "rm -rf dist",
        "targets": ["dist"],
        "action_key": "delete:dist",
    }


def test_parse_destructive_action_request_ignores_non_matching_json():
    output = """
```json
{"approved": true, "feedback": "not a destructive request"}
```
"""

    assert parse_destructive_action_request(output) is None


def test_parse_destructive_action_request_rejects_missing_required_fields():
    output = """
```agentforce-warning
{"type": "destructive_action_request", "summary": "Delete files"}
```
"""

    assert parse_destructive_action_request(output) is None
