#!/usr/bin/env python3
"""Deterministic, source-only audit for Harvard CS1200 Spring 2026.

This tool inventories the frozen public repository and checks executable-source
syntax. It deliberately does not solve assignments or award course-completion
credit.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

EXPECTED = {
    "lecture_pdfs": 23,
    "sre_pdfs": 14,
    "pset_directories": 11,
    "pset_pdfs": 11,
}
EXPECTED_PSETS = tuple(f"ps{i}" for i in range(11))
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".tex",
    ".sty",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
}
TODO_RE = re.compile(r"\b(?:TODO|FIXME|TBD)\b", re.IGNORECASE)
SECTION_RE = re.compile(r"\\(?:sub)*section\*?\s*\{")
PROBLEM_SIGNAL_RES = (
    re.compile(r"\\begin\s*\{problem\}"),
    re.compile(r"\\problem\b"),
    re.compile(r"\\question\b"),
    re.compile(r"\\begin\s*\{exercise\}"),
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def lane_for(relpath: str) -> str:
    match = re.match(r"^psets/ps(\d+)(?:/|$)", relpath)
    if match:
        number = int(match.group(1))
        if number <= 3:
            return "psets_0_3"
        if number <= 7:
            return "psets_4_7"
        return "psets_8_10"
    if relpath.startswith("lectures/") or relpath.startswith("SRE/"):
        return "lectures_sre"
    return "other"


class PythonSignals(ast.NodeVisitor):
    def __init__(self) -> None:
        self.functions = 0
        self.async_functions = 0
        self.classes = 0
        self.test_functions = 0
        self.assert_nodes = 0
        self.pass_nodes = 0
        self.raise_not_implemented = 0
        self.imports: Counter[str] = Counter()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.functions += 1
        if node.name.startswith("test_"):
            self.test_functions += 1
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.async_functions += 1
        if node.name.startswith("test_"):
            self.test_functions += 1
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.classes += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:  # noqa: N802
        self.assert_nodes += 1
        self.generic_visit(node)

    def visit_Pass(self, node: ast.Pass) -> None:  # noqa: N802
        self.pass_nodes += 1

    def visit_Raise(self, node: ast.Raise) -> None:  # noqa: N802
        exc = node.exc
        if isinstance(exc, ast.Call):
            exc = exc.func
        if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
            self.raise_not_implemented += 1
        elif isinstance(exc, ast.Attribute) and exc.attr == "NotImplementedError":
            self.raise_not_implemented += 1
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.imports[alias.name.split(".", 1)[0]] += 1

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module:
            self.imports[node.module.split(".", 1)[0]] += 1


def analyze_python(path: Path, text: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "syntax_ok": False,
        "syntax_error": None,
        "functions": 0,
        "async_functions": 0,
        "classes": 0,
        "test_functions": 0,
        "assert_nodes": 0,
        "pass_nodes": 0,
        "raise_not_implemented": 0,
        "todo_markers": len(TODO_RE.findall(text)),
        "imports": {},
    }
    try:
        compile(text, path.as_posix(), "exec", dont_inherit=True, optimize=0)
        tree = ast.parse(text, filename=path.as_posix())
    except (SyntaxError, ValueError, UnicodeError) as exc:
        result["syntax_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "line": getattr(exc, "lineno", None),
            "offset": getattr(exc, "offset", None),
        }
        return result

    signals = PythonSignals()
    signals.visit(tree)
    result.update(
        {
            "syntax_ok": True,
            "functions": signals.functions,
            "async_functions": signals.async_functions,
            "classes": signals.classes,
            "test_functions": signals.test_functions,
            "assert_nodes": signals.assert_nodes,
            "pass_nodes": signals.pass_nodes,
            "raise_not_implemented": signals.raise_not_implemented,
            "imports": dict(sorted(signals.imports.items())),
        }
    )
    return result


def analyze_tex(text: str) -> dict[str, int]:
    return {
        "sections": len(SECTION_RE.findall(text)),
        "problem_signals": sum(len(pattern.findall(text)) for pattern in PROBLEM_SIGNAL_RES),
        "items": len(re.findall(r"\\item\b", text)),
        "todo_markers": len(TODO_RE.findall(text)),
    }


def inspect_file(path: Path, root: Path) -> dict[str, Any]:
    relpath = relative(path, root)
    payload = path.read_bytes()
    suffix = path.suffix.lower()
    record: dict[str, Any] = {
        "path": relpath,
        "lane": lane_for(relpath),
        "size_bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "suffix": suffix,
    }
    if suffix in TEXT_SUFFIXES:
        text = payload.decode("utf-8", errors="replace")
        record["replacement_characters"] = text.count("\ufffd")
        if suffix == ".py":
            record["python"] = analyze_python(path, text)
        elif suffix == ".tex":
            record["tex"] = analyze_tex(text)
        elif suffix in {".md", ".txt", ".sty"}:
            record["todo_markers"] = len(TODO_RE.findall(text))
    return record


def summarize(records: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    pset_dirs = sorted(
        (
            path.name
            for path in (root / "psets").iterdir()
            if path.is_dir() and re.fullmatch(r"ps\d+", path.name)
        ),
        key=lambda name: int(name[2:]),
    )
    lecture_pdfs = [
        record
        for record in records
        if record["path"].startswith("lectures/") and record["suffix"] == ".pdf"
    ]
    sre_pdfs = [
        record
        for record in records
        if record["path"].startswith("SRE/") and record["suffix"] == ".pdf"
    ]
    pset_pdfs = [
        record
        for record in records
        if re.fullmatch(
            r"psets/ps\d+/ps\d+\.pdf", record["path"], flags=re.IGNORECASE
        )
    ]
    python_records = [record for record in records if record["suffix"] == ".py"]
    tex_records = [record for record in records if record["suffix"] == ".tex"]
    test_files = [
        record
        for record in python_records
        if Path(record["path"]).name == "tests.py"
        or Path(record["path"]).name.endswith("_tests.py")
    ]
    syntax_failures = [
        {"path": record["path"], "error": record["python"]["syntax_error"]}
        for record in python_records
        if not record["python"]["syntax_ok"]
    ]
    imported_modules: Counter[str] = Counter()
    for record in python_records:
        imported_modules.update(record["python"].get("imports", {}))

    lanes: dict[str, dict[str, Any]] = {}
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["lane"]].append(record)
    for lane, lane_records in sorted(grouped.items()):
        lane_payload = [
            {
                "path": record["path"],
                "sha256": record["sha256"],
                "size_bytes": record["size_bytes"],
            }
            for record in sorted(lane_records, key=lambda item: item["path"])
        ]
        lanes[lane] = {
            "file_count": len(lane_records),
            "bytes": sum(record["size_bytes"] for record in lane_records),
            "python_files": sum(record["suffix"] == ".py" for record in lane_records),
            "pdf_files": sum(record["suffix"] == ".pdf" for record in lane_records),
            "tex_files": sum(record["suffix"] == ".tex" for record in lane_records),
            "payload_sha256": sha256_bytes(stable_json_bytes(lane_payload)),
        }

    observed = {
        "lecture_pdfs": len(lecture_pdfs),
        "sre_pdfs": len(sre_pdfs),
        "pset_directories": len(pset_dirs),
        "pset_pdfs": len(pset_pdfs),
    }
    expected_checks = {
        key: {
            "expected": expected,
            "observed": observed[key],
            "pass": observed[key] == expected,
        }
        for key, expected in EXPECTED.items()
    }
    pset_directory_check = {
        "expected": list(EXPECTED_PSETS),
        "observed": pset_dirs,
        "pass": pset_dirs == list(EXPECTED_PSETS),
    }

    return {
        "expected_checks": expected_checks,
        "pset_directory_check": pset_directory_check,
        "counts": {
            "all_files": len(records),
            "all_bytes": sum(record["size_bytes"] for record in records),
            "python_files": len(python_records),
            "python_syntax_pass": len(python_records) - len(syntax_failures),
            "python_syntax_fail": len(syntax_failures),
            "public_test_files": len(test_files),
            "static_test_functions": sum(
                record["python"]["test_functions"] for record in python_records
            ),
            "static_assert_nodes": sum(
                record["python"]["assert_nodes"] for record in python_records
            ),
            "pass_nodes": sum(record["python"]["pass_nodes"] for record in python_records),
            "not_implemented_raises": sum(
                record["python"]["raise_not_implemented"] for record in python_records
            ),
            "python_todo_markers": sum(
                record["python"]["todo_markers"] for record in python_records
            ),
            "tex_files": len(tex_records),
            "tex_problem_signals": sum(
                record["tex"]["problem_signals"] for record in tex_records
            ),
            "tex_sections": sum(record["tex"]["sections"] for record in tex_records),
            "lecture_pdfs": len(lecture_pdfs),
            "sre_pdfs": len(sre_pdfs),
            "pset_directories": len(pset_dirs),
            "pset_pdfs": len(pset_pdfs),
        },
        "test_files": sorted(record["path"] for record in test_files),
        "syntax_failures": syntax_failures,
        "imported_modules": dict(sorted(imported_modules.items())),
        "lanes": lanes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    root = args.repo.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not (root / "psets").is_dir() or not (root / "lectures").is_dir() or not (root / "SRE").is_dir():
        raise SystemExit("Expected psets/, lectures/, and SRE/ directories are missing")

    started = time.perf_counter()
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        records = list(executor.map(lambda path: inspect_file(path, root), files))
    records.sort(key=lambda item: item["path"])

    summary = summarize(records, root)
    manifest = {
        "schema": "university-cs1200-deep/manifest/1",
        "source_commit": "0b967fe320ecf2141a6f3b8165d3d096c99fb3ac",
        "files": records,
    }
    manifest_bytes = stable_json_bytes(manifest)
    (out / "manifest.json").write_bytes(manifest_bytes)

    gates = {
        "expected_counts": all(
            check["pass"] for check in summary["expected_checks"].values()
        ),
        "expected_pset_directories": summary["pset_directory_check"]["pass"],
        "python_syntax": not summary["syntax_failures"],
        "four_required_lanes_present": all(
            lane in summary["lanes"]
            for lane in ("psets_0_3", "psets_4_7", "psets_8_10", "lectures_sre")
        ),
        "duplicate_paths": len({record["path"] for record in records}) == len(records),
    }
    status = "PASS_SCOPED_SOURCE_INVENTORY" if all(gates.values()) else "FAIL"
    scientific = {
        "schema": "university-cs1200-deep/scientific-report/1",
        "status": status,
        "coordination_id": "COORD-2026-08-06-PARALLEL-V2",
        "official_repository": "Harvard-CS-1200/2026-Spring",
        "official_commit": "0b967fe320ecf2141a6f3b8165d3d096c99fb3ac",
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "gates": gates,
        "summary": summary,
        "scope_boundary": (
            "Complete public-source inventory and Python syntax compilation only; "
            "not problem-set solutions, grader success, course completion, or university mastery."
        ),
    }
    scientific_bytes = stable_json_bytes(scientific)
    (out / "scientific.json").write_bytes(scientific_bytes)
    runtime = {
        "elapsed_seconds": time.perf_counter() - started,
        "workers": max(1, args.workers),
        "file_count": len(records),
    }
    (out / "runtime.json").write_bytes(stable_json_bytes(runtime))
    (out / "scientific.sha256").write_text(
        f"{sha256_bytes(scientific_bytes)}  scientific.json\n", encoding="utf-8"
    )
    print(json.dumps({"status": status, **summary["counts"]}, indent=2, sort_keys=True))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
