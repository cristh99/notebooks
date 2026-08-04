from __future__ import annotations

import json
import sys
from pathlib import Path

from .contracts import load_and_validate


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("receipts.json")
    result = load_and_validate(path)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
