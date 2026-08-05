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
        'CANDIDATE_SCHEMA = "ocr-numeric-consensus-wildreceipt-candidate/6"\n'
        'CANDIDATE_ID = "numeric-consensus-v4-wildreceipt-schema-v3"\n',
        'CANDIDATE_SCHEMA = "ocr-numeric-consensus-wildreceipt-candidate/7"\n'
        'CANDIDATE_ID = "numeric-consensus-v4-wildreceipt-schema-v4"\n',
        "candidate runtime-closure version",
    )
    replace_once(
        CANDIDATE,
        '''    "ocr_real_risk_v1/sroie_natural_holdout.py",
    "ocr_real_risk_v1/cord_natural_holdout.py",
    "ocr_real_risk_v1/cord_consensus_detector_v4.py",
    "ocr_real_risk_v1/wildreceipt_adapter.py",
    "ocr_real_risk_v1/wildreceipt_external.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py",''',
        '''    "ocr_real_risk_v1/sroie_natural_holdout.py",
    "ocr_real_risk_v1/cord_natural_holdout.py",
    "ocr_real_risk_v1/cord_consensus_detector_v4.py",
    "ocr_real_risk_v1/cord_detector_crops_v4.py",
    "ocr_real_risk_v1/coru_source_seal.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v4.py",
    "ocr_real_risk_v1/wildreceipt_source_seal.py",
    "ocr_real_risk_v1/wildreceipt_adapter.py",
    "ocr_real_risk_v1/wildreceipt_external.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py",''',
        "candidate transitive source closure",
    )
    replace_once(
        CANDIDATE,
        '''        "runtime": {
            "source_shards": 3,
            "one_worker_per_source_shard": True,
            "same_candidate_bytes_and_runtime_in_every_worker": True,
            "aggregate_recomputes_deduplication_and_all_exact_bounds": True,
        },''',
        '''        "runtime": {
            "source_shards": 3,
            "one_worker_per_source_shard": True,
            "same_candidate_bytes_and_runtime_in_every_worker": True,
            "self_contained_source_bundle": True,
            "neutral_workdir_import_required": True,
            "aggregate_recomputes_deduplication_and_all_exact_bounds": True,
        },''',
        "protocol runtime closure",
    )
    replace_once(
        TEST,
        '''        self.assertIn(
            "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py",
            SOURCE_FILES,
        )''',
        '''        self.assertIn(
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
        self.assertTrue(protocol["runtime"]["neutral_workdir_import_required"])''',
        "runtime closure tests",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
