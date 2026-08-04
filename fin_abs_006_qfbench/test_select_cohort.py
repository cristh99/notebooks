from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .select_cohort import (
    CALIBRATION_TASKS,
    COHORT_SIZE,
    PUBLIC_FRONTIER_PASS_RATE,
    REQUIRED_PASSES,
    SOURCE_COMMIT,
    rank_key,
    select,
    wilson_lower,
)


class BreadthSelectionTests(unittest.TestCase):
    def _workspace(self) -> tempfile.TemporaryDirectory[str]:
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name) / "tasks"
        root.mkdir(parents=True)
        task_ids = sorted(
            CALIBRATION_TASKS
            | {f"untouched-task-{index:03d}" for index in range(100)}
        )
        for task_id in task_ids:
            task_root = root / task_id
            task_root.mkdir()
            (task_root / "task.toml").write_text(
                "version = '1.0'\n", encoding="utf-8"
            )
        return directory

    def test_wilson_promotion_bar_exceeds_public_frontier(self) -> None:
        self.assertGreater(
            wilson_lower(REQUIRED_PASSES, COHORT_SIZE),
            PUBLIC_FRONTIER_PASS_RATE,
        )
        self.assertLessEqual(
            wilson_lower(REQUIRED_PASSES - 1, COHORT_SIZE),
            PUBLIC_FRONTIER_PASS_RATE,
        )

    def test_selection_is_deterministic_and_excludes_calibration(self) -> None:
        directory = self._workspace()
        try:
            root = Path(directory.name)
            first = select(root, SOURCE_COMMIT)
            second = select(root, SOURCE_COMMIT)
        finally:
            directory.cleanup()
        selected = first["payload"]["selection"]["selected_tasks"]
        self.assertEqual(first, second)
        self.assertEqual(len(selected), COHORT_SIZE)
        self.assertFalse(set(selected) & CALIBRATION_TASKS)
        self.assertEqual(
            selected,
            sorted(selected, key=lambda task_id: (rank_key(task_id), task_id)),
        )
        self.assertEqual(first["payload"]["status"], "COHORT_FROZEN")
        self.assertEqual(first["payload"]["absolute_score"]["after"], 423)

    def test_wrong_source_commit_blocks_selection(self) -> None:
        directory = self._workspace()
        try:
            report = select(Path(directory.name), "0" * 40)
        finally:
            directory.cleanup()
        self.assertEqual(report["payload"]["status"], "BLOCKED_SELECTION")
        self.assertFalse(
            report["payload"]["gate_checks"]["source_commit_exact"]
        )


if __name__ == "__main__":
    unittest.main()
