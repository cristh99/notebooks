from __future__ import annotations

import unittest

from .core import Candidate
from .final_partition import (
    CANARY_PARTITIONS,
    FINAL_PARTITIONS,
    assert_disjoint,
    choose_one_document_per_process,
    freeze_partition,
    process_key,
)


def candidate(
    url: str,
    ocid: str,
    institution: str = "1230",
) -> Candidate:
    return Candidate(
        url=url,
        document_type="contractSigned",
        process=ocid,
        ocid=ocid,
        institution_code=institution,
        institution_name=f"Institution {institution}",
        source_year=2025,
        source_line=1,
    )


class FinalPartitionTests(unittest.TestCase):
    def test_one_document_per_process(self) -> None:
        values = [
            candidate("https://example.test/a.pdf", "ocds-1"),
            candidate("https://example.test/b.pdf", "ocds-1"),
            candidate("https://example.test/c.pdf", "ocds-2"),
        ]
        selected = choose_one_document_per_process(values)
        self.assertEqual(len(selected), 2)
        self.assertEqual(len({process_key(item) for item in selected}), 2)

    def test_canary_and_final_are_process_disjoint(self) -> None:
        values = [
            candidate(
                f"https://example.test/{index}.pdf",
                f"ocds-{index}",
            )
            for index in range(500)
        ]
        canary = freeze_partition(values, partitions=CANARY_PARTITIONS)
        final = freeze_partition(values, partitions=FINAL_PARTITIONS)
        assert_disjoint(canary, final)
        self.assertEqual(
            int(canary["selected_processes"])
            + int(final["selected_processes"]),
            500,
        )

    def test_split_is_stable_under_input_reordering(self) -> None:
        values = [
            candidate(
                f"https://example.test/{index}.pdf",
                f"ocds-{index}",
            )
            for index in range(50)
        ]
        forward = freeze_partition(values, partitions=FINAL_PARTITIONS)
        reverse = freeze_partition(
            list(reversed(values)),
            partitions=FINAL_PARTITIONS,
        )
        self.assertEqual(forward["records"], reverse["records"])

    def test_duplicate_process_cannot_cross_split(self) -> None:
        values = [
            candidate("https://example.test/a.pdf", "ocds-same"),
            candidate("https://example.test/b.pdf", "ocds-same"),
        ]
        canary = freeze_partition(values, partitions=CANARY_PARTITIONS)
        final = freeze_partition(values, partitions=FINAL_PARTITIONS)
        self.assertLessEqual(
            int(canary["selected_processes"])
            + int(final["selected_processes"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
