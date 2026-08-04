from __future__ import annotations

import hashlib
import json
from pathlib import Path

SOURCE_SHA256 = "ff77eb2e5ce1957303c07f76a0d9ad278622fc4f1504455b322a533d466d455d"
TARGET_SHA256 = "28e5031b452a457cf0c643a32c73941ec43e5c179469b05a2f3f9b6d4f3673ea"
OLD_IMPORT = "import math\nimport time\n"
NEW_IMPORT = "import math\nimport sys\nimport time\n"
OLD_LOAD = "    module = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(module)\n    return module\n"
NEW_LOAD = "    module = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = module\n    spec.loader.exec_module(module)\n    return module\n"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path("data_science_dominance/tabarena_portfolio")
    path = root / "dominance.py"
    if digest(path) != SOURCE_SHA256:
        raise SystemExit("unexpected frozen dominance source")
    text = path.read_text(encoding="utf-8")
    if text.count(OLD_IMPORT) != 1 or text.count(OLD_LOAD) != 1:
        raise SystemExit("repair anchors are not unique")
    text = text.replace(OLD_IMPORT, NEW_IMPORT).replace(OLD_LOAD, NEW_LOAD)
    path.write_text(text, encoding="utf-8")
    if digest(path) != TARGET_SHA256:
        raise SystemExit("repaired dominance hash mismatch")
    receipt = {
        "schema": "data-science-dominance/tabarena-legacy-loader-repair/1",
        "source_sha256": SOURCE_SHA256,
        "target_sha256": TARGET_SHA256,
        "scope": "register a fixed local module in sys.modules before exec_module",
        "candidate_or_selection_semantics_changed": False,
        "external_task_values_accessed": False,
    }
    (root / "legacy-loader-repair-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
