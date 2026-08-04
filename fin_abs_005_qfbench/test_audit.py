from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .audit import (
    EXPECTED_SELECTION_SHA256,
    TASKS,
    audit,
    digest,
    selection_payload,
)


class QFBenchBlindAuditTests(unittest.TestCase):
    def _workspace(self) -> tempfile.TemporaryDirectory[str]:
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        (root / "README.md").write_text("QFBench\n", encoding="utf-8")
        (root / "LICENSE").write_text("CC BY-NC 4.0\n", encoding="utf-8")
        for task in TASKS:
            task_root = root / "tasks" / task
            environment = task_root / "environment"
            environment.mkdir(parents=True)
            (task_root / "task.toml").write_text(
                "version = '1.0'\n"
                "[metadata]\n"
                f"name = '{task}'\n"
                "category = 'quantitative-finance'\n",
                encoding="utf-8",
            )
            (task_root / "instruction.md").write_text(
                (f"# {task}\n" + "Solve the supplied quantitative-finance task. " * 8),
                encoding="utf-8",
            )
            (environment / "Dockerfile").write_text(
                "FROM python:3.12-slim\n",
                encoding="utf-8",
            )
        return directory

    def test_selection_manifest_is_frozen(self) -> None:
        self.assertEqual(
            digest(selection_payload()), EXPECTED_SELECTION_SHA256
        )
        self.assertEqual(len(TASKS), 5)
        self.assertEqual(len(set(TASKS)), 5)

    def test_valid_sparse_workspace_passes(self) -> None:
        directory = self._workspace()
        try:
            report = audit(Path(directory.name))
        finally:
            directory.cleanup()
        self.assertEqual(report["payload"]["status"], "PASS_BLIND_STAGE0")
        self.assertTrue(all(report["payload"]["gate_checks"].values()))
        self.assertEqual(report["payload"]["absolute_score"]["after"], 423)
        self.assertEqual(report["payload"]["workspace"]["forbidden_paths"], [])

    def test_solution_or_test_path_blocks_cohort(self) -> None:
        directory = self._workspace()
        root = Path(directory.name)
        leaked = root / "tasks" / TASKS[0] / "tests" / "hidden_test.py"
        leaked.parent.mkdir(parents=True)
        leaked.write_text("raise AssertionError('oracle leak')\n", encoding="utf-8")
        try:
            report = audit(root)
        finally:
            directory.cleanup()
        self.assertEqual(
            report["payload"]["status"], "BLOCKED_BLIND_STAGE0"
        )
        self.assertIn(
            f"tasks/{TASKS[0]}/tests/hidden_test.py",
            report["payload"]["workspace"]["forbidden_paths"],
        )
        self.assertFalse(
            report["payload"]["gate_checks"]["zero_solution_or_test_files"]
        )


if __name__ == "__main__":
    unittest.main()
