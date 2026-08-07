#!/usr/bin/env python3
"""Deterministic source-only preflight for Harvard CS1200 PS6–PS10.

The program inventories one frozen public problem-set directory, compiles Python
syntax without importing assignment dependencies, and extracts obligation
signals from LaTeX. It deliberately does not solve assignments or claim course
completion.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import py_compile
import re
from collections import Counter
from pathlib import Path
from typing import Any

OFFICIAL_COMMIT = "0b967fe320ecf2141a6f3b8165d3d096c99fb3ac"
PSETS = {6, 7, 8, 9, 10}
TEXT_SUFFIXES = {".py", ".tex", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"}
TODO_RE = re.compile(r"\b(?:TODO|FIXME|TBD)\b", re.IGNORECASE)
REFLECTION_RE = re.compile(r"\breflection\b", re.IGNORECASE)
SURVEY_RE = re.compile(r"forms\.gle|survey", re.IGNORECASE)
OPTIONAL_RE = re.compile(r"\b(?:optional|challenge|extra\s+credit)\b", re.IGNORECASE)
BEGIN_ENUM_RE = re.compile(r"\\begin\s*\{enumerate\}")
END_ENUM_RE = re.compile(r"\\end\s*\{enumerate\}")
ITEM_RE = re.compile(r"\\item(?:\s*\[[^\]]*\])?\s*")
COMMAND_RE = re.compile(r"\\(?:texttt|emph|textbf|label|ref|pageref)\s*\{([^{}]*)\}")
WHITESPACE_RE = re.compile(r"\s+")


def stable_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_tex(fragment: str) -> str:
    fragment = fragment.replace("\\\\", " ")
    fragment = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", fragment)
    fragment = COMMAND_RE.sub(r"\1", fragment)
    fragment = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", fragment)
    fragment = fragment.replace("{", " ").replace("}", " ")
    fragment = WHITESPACE_RE.sub(" ", fragment).strip(" .:-\n\t")
    return fragment


def extract_items(text: str) -> list[dict[str, Any]]:
    """Extract bounded snippets for every LaTeX item with approximate depth."""
    tokens: list[tuple[int, str, re.Match[str]]] = []
    for pattern, kind in ((BEGIN_ENUM_RE, "begin"), (END_ENUM_RE, "end"), (ITEM_RE, "item")):
        tokens.extend((match.start(), kind, match) for match in pattern.finditer(text))
    tokens.sort(key=lambda row: row[0])

    depth = 0
    items: list[dict[str, Any]] = []
    for index, (position, kind, match) in enumerate(tokens):
        if kind == "begin":
            depth += 1
            continue
        if kind == "end":
            depth = max(0, depth - 1)
            continue
        next_position = len(text)
        for later_position, later_kind, _ in tokens[index + 1 :]:
            if later_kind in {"item", "end"}:
                next_position = later_position
                break
        raw = text[match.end() : min(next_position, match.end() + 900)]
        snippet = clean_tex(raw)
        if snippet:
            items.append(
                {
                    "ordinal": len(items) + 1,
                    "enumerate_depth": depth,
                    "snippet": snippet[:500],
                    "reflection_signal": bool(REFLECTION_RE.search(raw)),
                    "survey_signal": bool(SURVEY_RE.search(raw)),
                    "optional_signal": bool(OPTIONAL_RE.search(raw)),
                }
            )
    return items


def python_signals(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    result: dict[str, Any] = {
        "syntax_ok": False,
        "syntax_error": None,
        "functions": 0,
        "classes": 0,
        "test_functions": 0,
        "assertions": 0,
        "pass_nodes": 0,
        "not_implemented": 0,
        "todo_markers": len(TODO_RE.findall(text)),
        "imports": [],
    }
    try:
        py_compile.compile(str(path), doraise=True)
        tree = ast.parse(text, filename=str(path))
    except Exception as exc:  # SyntaxError and PyCompileError are evidence, not crashes.
        result["syntax_error"] = {"type": type(exc).__name__, "message": str(exc)}
        return result

    imports: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"] += 1
            if node.name.startswith("test_") or node.name == "test":
                result["test_functions"] += 1
        elif isinstance(node, ast.ClassDef):
            result["classes"] += 1
        elif isinstance(node, ast.Assert):
            result["assertions"] += 1
        elif isinstance(node, ast.Pass):
            result["pass_nodes"] += 1
        elif isinstance(node, ast.Raise):
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name) and target.id == "NotImplementedError":
                result["not_implemented"] += 1
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.name.split(".", 1)[0]] += 1
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports[node.module.split(".", 1)[0]] += 1
    result["syntax_ok"] = True
    result["imports"] = sorted(imports)
    return result


def audit(repo: Path, pset: int) -> dict[str, Any]:
    root = repo / "psets" / f"ps{pset}"
    if not root.is_dir():
        raise SystemExit(f"Missing official directory: {root}")

    records: list[dict[str, Any]] = []
    obligations: list[dict[str, Any]] = []
    syntax_failures: list[dict[str, str]] = []
    suffix_counts: Counter[str] = Counter()
    total_todos = 0
    total_pass_nodes = 0
    total_not_implemented = 0
    test_files: list[str] = []

    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(repo).as_posix()
        suffix = path.suffix.lower()
        suffix_counts[suffix or "<none>"] += 1
        record: dict[str, Any] = {
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "suffix": suffix,
        }
        if suffix == ".py":
            signals = python_signals(path)
            record["python"] = signals
            total_todos += signals["todo_markers"]
            total_pass_nodes += signals["pass_nodes"]
            total_not_implemented += signals["not_implemented"]
            if not signals["syntax_ok"]:
                syntax_failures.append({"path": relative, "error": signals["syntax_error"]})
            if path.name == "tests.py" or "test" in path.stem.lower():
                test_files.append(relative)
        elif suffix == ".tex":
            text = path.read_text(encoding="utf-8", errors="replace")
            items = extract_items(text)
            record["tex"] = {
                "items": len(items),
                "reflection_signals": sum(item["reflection_signal"] for item in items),
                "survey_signals": sum(item["survey_signal"] for item in items),
                "optional_signals": sum(item["optional_signal"] for item in items),
            }
            obligations.extend({"source": relative, **item} for item in items)
            total_todos += len(TODO_RE.findall(text))
        elif suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            record["todo_markers"] = len(TODO_RE.findall(text))
            total_todos += record["todo_markers"]
        records.append(record)

    manifest = {
        "schema": "university-cs1200-pset/manifest/1",
        "official_commit": OFFICIAL_COMMIT,
        "pset": pset,
        "files": records,
    }
    manifest_bytes = stable_bytes(manifest)
    technical_obligations = [
        item
        for item in obligations
        if not item["reflection_signal"] and not item["survey_signal"]
    ]
    report = {
        "schema": "university-cs1200-pset/preflight/1",
        "status": "PASS_SCOPED_SOURCE_PREFLIGHT" if not syntax_failures else "FAIL_PYTHON_SYNTAX",
        "official_repository": "Harvard-CS-1200/2026-Spring",
        "official_commit": OFFICIAL_COMMIT,
        "pset": pset,
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "summary": {
            "files": len(records),
            "bytes": sum(record["size_bytes"] for record in records),
            "suffix_counts": dict(sorted(suffix_counts.items())),
            "python_files": sum(record["suffix"] == ".py" for record in records),
            "python_syntax_failures": syntax_failures,
            "test_files": sorted(test_files),
            "todo_markers": total_todos,
            "pass_nodes": total_pass_nodes,
            "not_implemented_raises": total_not_implemented,
            "latex_items": len(obligations),
            "technical_obligations": len(technical_obligations),
            "reflection_or_survey_items": len(obligations) - len(technical_obligations),
            "optional_items": sum(item["optional_signal"] for item in obligations),
        },
        "obligations": obligations,
        "scope_boundary": (
            "Frozen public-source inventory, obligation extraction and Python syntax only; "
            "not solutions, test execution, grader success, problem-set completion or course completion."
        ),
    }
    return {"manifest": manifest, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--pset", required=True, type=int, choices=sorted(PSETS))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    result = audit(args.repo.resolve(), args.pset)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    report_path = args.out / "scientific.json"
    manifest_path.write_bytes(stable_bytes(result["manifest"]))
    report_path.write_bytes(stable_bytes(result["report"]))
    (args.out / "scientific.sha256").write_text(
        f"{sha256_file(report_path)}  scientific.json\n", encoding="utf-8"
    )
    print(json.dumps(result["report"], indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["report"]["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
