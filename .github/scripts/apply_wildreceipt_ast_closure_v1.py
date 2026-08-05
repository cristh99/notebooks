from __future__ import annotations

from pathlib import Path


CANDIDATE = Path(
    "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py"
)
TEST = Path(
    "ocr_real_risk_v1/test_numeric_consensus_candidate_v4_wildreceipt.py"
)


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one target, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    replace_once(
        CANDIDATE,
        "import argparse\nimport json\n",
        "import argparse\nimport ast\nimport json\n",
        "ast import",
    )
    replace_once(
        CANDIDATE,
        'CANDIDATE_SCHEMA = "ocr-numeric-consensus-wildreceipt-candidate/7"\n'
        'CANDIDATE_ID = "numeric-consensus-v4-wildreceipt-schema-v4"\n',
        'CANDIDATE_SCHEMA = "ocr-numeric-consensus-wildreceipt-candidate/8"\n'
        'CANDIDATE_ID = "numeric-consensus-v4-wildreceipt-schema-v5"\n',
        "candidate AST-closure version",
    )
    old_sources = '''SOURCE_FILES = (
    "ocr_real_risk_v1/__init__.py",
    "ocr_real_risk_v1/core.py",
    "ocr_real_risk_v1/exact_bounds.py",
    "ocr_real_risk_v1/pixel_digit_alignment.py",
    "ocr_real_risk_v1/numeric_digit_forest.py",
    "ocr_real_risk_v1/numeric_digit_forest_deterministic.py",
    "ocr_real_risk_v1/sroie_natural_holdout.py",
    "ocr_real_risk_v1/cord_natural_holdout.py",
    "ocr_real_risk_v1/cord_consensus_detector_v4.py",
    "ocr_real_risk_v1/cord_detector_crops_v4.py",
    "ocr_real_risk_v1/coru_source_seal.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v4.py",
    "ocr_real_risk_v1/wildreceipt_source_seal.py",
    "ocr_real_risk_v1/wildreceipt_adapter.py",
    "ocr_real_risk_v1/wildreceipt_external.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py",
)
'''
    new_sources = '''PACKAGE_NAME = "ocr_real_risk_v1"
SOURCE_CLOSURE_ALGORITHM = "python-ast-local-import-closure-v1"
SOURCE_ROOTS = (
    "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py",
    "ocr_real_risk_v1/wildreceipt_adapter.py",
    "ocr_real_risk_v1/wildreceipt_external.py",
)


def _module_source_paths(repository_root: Path, module: str) -> tuple[str, ...]:
    if module != PACKAGE_NAME and not module.startswith(f"{PACKAGE_NAME}."):
        return ()
    parts = module.split(".")
    base = repository_root.joinpath(*parts)
    module_file = base.with_suffix(".py")
    package_init = base / "__init__.py"
    paths: set[str] = set()
    root_init = repository_root / PACKAGE_NAME / "__init__.py"
    if root_init.is_file():
        paths.add(root_init.relative_to(repository_root).as_posix())
    if module_file.is_file():
        paths.add(module_file.relative_to(repository_root).as_posix())
    elif package_init.is_file():
        paths.add(package_init.relative_to(repository_root).as_posix())
    else:
        raise RuntimeError(f"local import cannot be resolved: {module}")
    for index in range(1, len(parts)):
        parent_init = repository_root.joinpath(*parts[:index]) / "__init__.py"
        if parent_init.is_file():
            paths.add(parent_init.relative_to(repository_root).as_posix())
    return tuple(sorted(paths))


def _local_import_modules(relative: str, source: str) -> tuple[str, ...]:
    tree = ast.parse(source, filename=relative)
    module_name = relative.removesuffix(".py").replace("/", ".")
    if module_name.endswith(".__init__"):
        package_parts = module_name.removesuffix(".__init__").split(".")
    else:
        package_parts = module_name.split(".")[:-1]
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == PACKAGE_NAME or alias.name.startswith(
                    f"{PACKAGE_NAME}."
                ):
                    imported.add(alias.name)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            ascend = node.level - 1
            if ascend > len(package_parts):
                raise RuntimeError(
                    f"relative import escapes package in {relative}: level={node.level}"
                )
            base_parts = package_parts[: len(package_parts) - ascend]
            if node.module:
                imported.add(".".join([*base_parts, *node.module.split(".")]))
            else:
                for alias in node.names:
                    imported.add(".".join([*base_parts, alias.name]))
        elif node.module == PACKAGE_NAME or str(node.module or "").startswith(
            f"{PACKAGE_NAME}."
        ):
            imported.add(str(node.module))
    return tuple(sorted(imported))


def discover_source_files(repository_root: Path) -> tuple[str, ...]:
    repository_root = repository_root.resolve()
    discovered: set[str] = {f"{PACKAGE_NAME}/__init__.py", *SOURCE_ROOTS}
    pending = list(sorted(discovered))
    parsed: set[str] = set()
    while pending:
        relative = pending.pop(0)
        if relative in parsed:
            continue
        source_path = repository_root / relative
        if not source_path.is_file():
            raise RuntimeError(f"candidate source file missing: {relative}")
        parsed.add(relative)
        source = source_path.read_text(encoding="utf-8")
        for module in _local_import_modules(relative, source):
            for imported_path in _module_source_paths(repository_root, module):
                if imported_path not in discovered:
                    discovered.add(imported_path)
                    pending.append(imported_path)
        pending.sort()
    return tuple(sorted(discovered))


SOURCE_FILES = discover_source_files(Path(__file__).resolve().parents[1])
'''
    replace_once(CANDIDATE, old_sources, new_sources, "AST source closure")
    replace_once(
        CANDIDATE,
        '''            "self_contained_source_bundle": True,
            "neutral_workdir_import_required": True,
            "aggregate_recomputes_deduplication_and_all_exact_bounds": True,''',
        '''            "self_contained_source_bundle": True,
            "neutral_workdir_import_required": True,
            "source_bundle_closure_algorithm": SOURCE_CLOSURE_ALGORITHM,
            "source_bundle_roots": list(SOURCE_ROOTS),
            "aggregate_recomputes_deduplication_and_all_exact_bounds": True,''',
        "protocol AST closure identity",
    )
    replace_once(
        CANDIDATE,
        '''def _copy_sources(repository_root: Path, output_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in SOURCE_FILES:''',
        '''def _copy_sources(repository_root: Path, output_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    source_files = discover_source_files(repository_root)
    for relative in source_files:''',
        "copy discovered closure",
    )
    replace_once(
        CANDIDATE,
        '''            "requirements_sha256": sha256_file(requirements_path),
            "deterministic_threads": 1,
        },''',
        '''            "requirements_sha256": sha256_file(requirements_path),
            "deterministic_threads": 1,
            "source_closure_algorithm": SOURCE_CLOSURE_ALGORITHM,
            "source_roots": list(SOURCE_ROOTS),
            "source_file_count": len(source_records),
            "source_file_set_sha256": sha256_bytes(
                canonical_json([row["path"] for row in source_records]).encode(
                    "utf-8"
                )
            ),
        },''',
        "manifest AST closure evidence",
    )

    replace_once(
        TEST,
        "import copy\nimport unittest\n",
        "import copy\nimport unittest\nfrom pathlib import Path\n",
        "test Path import",
    )
    replace_once(
        TEST,
        '''    SOURCE_FILES,
    SOURCE_OBJECTS,
    SOURCE_SEAL_STABLE_SHA256,
    external_protocol,
    verify_manifest,
)''',
        '''    SOURCE_CLOSURE_ALGORITHM,
    SOURCE_FILES,
    SOURCE_OBJECTS,
    SOURCE_ROOTS,
    SOURCE_SEAL_STABLE_SHA256,
    discover_source_files,
    external_protocol,
    verify_manifest,
)''',
        "test closure imports",
    )
    old_test = '''    def test_frozen_sources_include_adapter(self) -> None:
        self.assertIn("ocr_real_risk_v1/wildreceipt_adapter.py", SOURCE_FILES)
        self.assertIn("ocr_real_risk_v1/wildreceipt_external.py", SOURCE_FILES)
        self.assertIn(
            "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py",
            SOURCE_FILES,
        )
        required_runtime_closure = {
            "ocr_real_risk_v1/cord_detector_crops_v4.py",
            "ocr_real_risk_v1/coru_source_seal.py",
            "ocr_real_risk_v1/numeric_consensus_candidate_v4.py",
            "ocr_real_risk_v1/wildreceipt_source_seal.py",
        }
        self.assertTrue(required_runtime_closure.issubset(set(SOURCE_FILES)))
        protocol = external_protocol()
        self.assertTrue(protocol["runtime"]["self_contained_source_bundle"])
        self.assertTrue(protocol["runtime"]["neutral_workdir_import_required"])
        self.assertEqual(len(SOURCE_SEAL_STABLE_SHA256), 64)
        self.assertEqual(len(DATASET_REVISION), 40)
        self.assertEqual(len(SOURCE_OBJECTS), 3)
        self.assertTrue(
            all(len(row["sha256"]) == 64 for row in SOURCE_OBJECTS.values())
        )
'''
    new_test = '''    def test_frozen_sources_are_ast_closed(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        discovered = discover_source_files(repository_root)
        self.assertEqual(SOURCE_FILES, discovered)
        self.assertEqual(
            SOURCE_CLOSURE_ALGORITHM, "python-ast-local-import-closure-v1"
        )
        self.assertEqual(
            set(SOURCE_ROOTS),
            {
                "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py",
                "ocr_real_risk_v1/wildreceipt_adapter.py",
                "ocr_real_risk_v1/wildreceipt_external.py",
            },
        )
        required_runtime_closure = {
            "ocr_real_risk_v1/cord_detector_crops_v4.py",
            "ocr_real_risk_v1/cord_source_seal.py",
            "ocr_real_risk_v1/coru_source_seal.py",
            "ocr_real_risk_v1/numeric_consensus_candidate_v4.py",
            "ocr_real_risk_v1/wildreceipt_source_seal.py",
        }
        self.assertTrue(required_runtime_closure.issubset(set(discovered)))
        self.assertTrue(
            all((repository_root / relative).is_file() for relative in discovered)
        )
        protocol = external_protocol()
        self.assertTrue(protocol["runtime"]["self_contained_source_bundle"])
        self.assertTrue(protocol["runtime"]["neutral_workdir_import_required"])
        self.assertEqual(
            protocol["runtime"]["source_bundle_closure_algorithm"],
            SOURCE_CLOSURE_ALGORITHM,
        )
        self.assertEqual(
            protocol["runtime"]["source_bundle_roots"], list(SOURCE_ROOTS)
        )
        self.assertEqual(len(SOURCE_SEAL_STABLE_SHA256), 64)
        self.assertEqual(len(DATASET_REVISION), 40)
        self.assertEqual(len(SOURCE_OBJECTS), 3)
        self.assertTrue(
            all(len(row["sha256"]) == 64 for row in SOURCE_OBJECTS.values())
        )
'''
    replace_once(TEST, old_test, new_test, "AST closure unit test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
