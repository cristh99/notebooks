from __future__ import annotations

import argparse
import json
from pathlib import Path

import resolve_canonical as base
from resolve_amounts_strict import resolve_amounts_strict
from resolve_runner_v2 import (
    resolve_entities_with_coexistence,
    resolve_legal_with_original_punctuation,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base.resolve_entities = resolve_entities_with_coexistence
    base.resolve_legal = resolve_legal_with_original_punctuation
    base.resolve_amounts = resolve_amounts_strict
    print(json.dumps(base.resolve_bundle(args.bundle, args.output), indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
