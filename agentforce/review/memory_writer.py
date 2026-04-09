from __future__ import annotations

from agentforce.memory.memory import Memory
from agentforce.review.models import ReviewReport


_METRICS_PREFIX = "review:metrics:"


class ReviewMemoryWriter:
    """Persist approved action items into the Memory system."""

    def __init__(self, memory: Memory):
        self.memory = memory

    def write_approved_items(self, report: ReviewReport) -> int:
        """Write approved ActionItems to memory and return the number written."""

        written = 0
        for item in report.action_items:
            if not item.approved:
                continue

            if item.action_type == "memory_entry":
                if item.memory_scope == "global":
                    self.memory.global_set(item.memory_key, item.memory_value, item.memory_category)
                    written += 1
                elif item.memory_scope == "project":
                    self.memory.project_set(
                        report.mission_id,
                        item.memory_key,
                        item.memory_value,
                        item.memory_category,
                    )
                    written += 1
            elif item.action_type == "process_improvement":
                key = f"process:{report.mission_id}:{item.id}"
                self.memory.global_set(key, item.description, category="convention")
                written += 1
            elif item.action_type == "roadmap_feature":
                key = f"roadmap:{report.mission_id}:{item.id}"
                self.memory.project_set(report.mission_id, key, item.description, category="lesson")
                written += 1

        return written

    def approve_item(self, report: ReviewReport, item_id: str) -> bool:
        """Set approved=True on the matching ActionItem. Returns True if found."""

        for item in report.action_items:
            if item.id == item_id:
                item.approved = True
                return True
        return False

    def approve_all(self, report: ReviewReport) -> int:
        """Set approved=True on all ActionItems. Returns count approved."""

        count = 0
        for item in report.action_items:
            item.approved = True
            count += 1
        return count

    def prune_baselines(self, mission_id: str, keep: int = 5) -> None:
        """Keep only the most recent project baseline entries by key timestamp."""

        project_path = self.memory._project_file(mission_id)
        entries = self.memory._read_file(project_path)
        baselines = [entry for entry in entries if entry.key.startswith(_METRICS_PREFIX)]
        if len(baselines) <= keep:
            return

        keep_keys = {
            entry.key for entry in sorted(baselines, key=lambda entry: entry.key)[-keep:]
        }
        pruned_entries = [
            entry
            for entry in entries
            if not entry.key.startswith(_METRICS_PREFIX) or entry.key in keep_keys
        ]
        self.memory._write_file(project_path, pruned_entries)


__all__ = ["ReviewMemoryWriter"]
