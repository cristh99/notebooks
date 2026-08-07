from __future__ import annotations

from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "ocr_real_risk_v1/openvino_full_gate_aggregate_v7.py"


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match, found {count}: {old[:100]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    old = '''    folds: list[dict[str, Any]] = []
    for held_out in range(MACROFOLD_COUNT):
        subset = [
            row for row in observations if int(row["macrofold_id"]) != held_out
        ]
        folds.append(
            {
                "held_out_macrofold": held_out,
                "summary": exact_summary(
                    subset,
                    minimum_selected=_scaled_minimum(
                        minimum_active, len(subset), len(observations)
                    ),
                ),
            }
        )
'''
    new = '''    folds: list[dict[str, Any]] = []
    for macrofold in range(MACROFOLD_COUNT):
        subset = [
            row for row in observations if int(row["macrofold_id"]) == macrofold
        ]
        partitions = list(
            range(
                macrofold * (PARTITION_COUNT // MACROFOLD_COUNT),
                (macrofold + 1) * (PARTITION_COUNT // MACROFOLD_COUNT),
            )
        )
        folds.append(
            {
                "macrofold": macrofold,
                "partitions": partitions,
                "summary": exact_summary(
                    subset,
                    minimum_selected=_scaled_minimum(
                        minimum_active, len(subset), len(observations)
                    ),
                ),
            }
        )
'''
    text = replace_once(text, old, new)
    text = replace_once(
        text,
        '                "semantics": "leave_one_macrofold_out",\n',
        '                "semantics": "each_preregistered_macrofold",\n',
    )
    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
