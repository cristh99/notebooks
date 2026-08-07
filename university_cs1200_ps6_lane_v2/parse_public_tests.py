from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def parse(path: Path) -> dict:
    raw = path.read_text(errors="replace")
    text = ANSI.sub("", raw)
    matches = re.findall(r"Tests Passed\s+(\d+)/(\d+)", text)
    if len(matches) != 1:
        raise SystemExit(
            f"expected one final test count in {path}, found {len(matches)}"
        )
    passed, total = map(int, matches[0])
    timeout_lines = [line for line in text.splitlines() if "Timeout" in line]
    failed_lines = [
        line for line in text.splitlines() if re.search(r":\s+Failed(?:\s|$)", line)
    ]
    return {
        "path": str(path),
        "passed": passed,
        "total": total,
        "timeouts": len(timeout_lines),
        "functional_failures": len(failed_lines),
        "timeout_lines": timeout_lines,
        "failed_lines": failed_lines,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--two", type=Path, required=True)
    parser.add_argument("--three", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    two = parse(args.two)
    three = parse(args.three)
    accepted = (
        two["passed"] == two["total"]
        and two["timeouts"] == 0
        and two["functional_failures"] == 0
        and three["functional_failures"] == 0
        and three["passed"] + three["timeouts"] == three["total"]
    )
    report = {
        "schema": "university-cs1200-ps6/public-tests/1",
        "status": "PASS_PUBLIC_TESTS_WITH_DECLARED_TIMEOUTS" if accepted else "FAIL",
        "two_coloring": two,
        "three_coloring": three,
        "acceptance_rule": (
            "2-color tests must all pass; 3-color functional failures are forbidden, "
            "while official one-second timeouts remain in the denominator because "
            "the assignment explicitly says some timeouts are expected."
        ),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not accepted:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
