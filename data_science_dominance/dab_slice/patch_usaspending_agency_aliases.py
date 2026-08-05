from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANDIDATE = ROOT / "dab_slice_agent.py"
BASE_SHA256 = "77ad131788a384cf030c2dad0ad7628fac4ad5a30c221f5e7206004a9403d1b2"


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if sha256(CANDIDATE) != BASE_SHA256:
        raise SystemExit("refusing to patch an unexpected DAB candidate")

    source = CANDIDATE.read_text(encoding="utf-8")
    old = '''    qualifying: set[str] = set()\n    for award_id, agency in contract_rows:\n        agency_key = normalize_key(agency)\n        if not ("departmentofdefense" in agency_key or agency_key in {"dod", "defense", "usdepartmentofdefense"}):\n            continue\n'''
    new = '''    # Resolve agency surface forms through DAB's authoritative lookup.\n    # Exact normalized fallback aliases cover minimal/synthetic fixtures; substring\n    # matching is intentionally forbidden because values such as\n    # "Not the Department of Defense" are not DoD awards.\n    agency_path = paths.dab_root / "query_usaspending" / "query_dataset" / "agencies.duckdb"\n    try:\n        agency_rows = duck_rows(\n            agency_path,\n            "SELECT surface_form, canonical_name FROM agency_aliases",\n        )\n    except Exception:\n        agency_rows = []\n    dod_agency_keys = {\n        "dod",\n        "departmentofdefense",\n        "deptofdefense",\n        "departmentofdefensedod",\n        "defensedepartment",\n        "usdepartmentofdefense",\n    }\n    for surface_form, canonical_name in agency_rows:\n        if normalize_key(canonical_name) == "departmentofdefense":\n            dod_agency_keys.add(normalize_key(surface_form))\n\n    qualifying: set[str] = set()\n    for award_id, agency in contract_rows:\n        agency_key = normalize_key(agency)\n        if agency_key not in dod_agency_keys:\n            continue\n'''
    if source.count(old) != 1:
        raise SystemExit("expected USAspending agency block not found exactly once")
    CANDIDATE.write_text(source.replace(old, new), encoding="utf-8")


if __name__ == "__main__":
    main()
