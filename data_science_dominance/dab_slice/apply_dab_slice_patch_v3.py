from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "dab_slice_agent.py"
PARENT_SHA256 = "77ad131788a384cf030c2dad0ad7628fac4ad5a30c221f5e7206004a9403d1b2"
FINAL_SHA256 = "0796f1d66d944e832181034f6e8e8800461b60d71e66716d5b19fe3fd1957dec"

OLD = '''    amount_index: dict[str, float] = {}
    collisions: set[str] = set()
    for award_id, amount_text in amount_rows:
        if is_superseded_identifier(award_id):
            continue
        amount = parse_money(amount_text)
        if amount is None or not math.isfinite(amount):
            continue
        for signature in identifier_signatures(award_id):
            if signature in amount_index and not math.isclose(amount_index[signature], float(amount), rel_tol=0.0, abs_tol=0.005):
                collisions.add(signature)
            else:
                amount_index[signature] = float(amount)
    for signature in collisions:
        amount_index.pop(signature, None)

    qualifying: set[str] = set()
    for award_id, agency in contract_rows:
        if normalize_key(agency) not in defense_aliases:
            continue
        signatures = identifier_signatures(award_id)
        matches = [(signature, amount_index[signature]) for signature in signatures if signature in amount_index]
        if not matches:
            amount = fuzzy_signature_match(signatures, amount_index, threshold=0.94)
            selected = min(signatures, key=len) if signatures else normalize_key(award_id)
        else:
            selected, amount = max(matches, key=lambda item: len(item[0]))
        if amount is not None and float(amount) > 1_000_000:
            qualifying.add(selected)
    return len(qualifying)
'''

NEW = '''    # Every surviving primary amount row is one award entity.  Signatures map to
    # that entity, not merely to a numeric value, so multiple contract-side
    # surface forms of the same award cannot be double-counted.
    amount_index: dict[str, tuple[int, float]] = {}
    collisions: set[str] = set()
    for entity_id, (award_id, amount_text) in enumerate(amount_rows):
        if is_superseded_identifier(award_id):
            continue
        amount = parse_money(amount_text)
        if amount is None or not math.isfinite(amount):
            continue
        payload = (entity_id, float(amount))
        for signature in identifier_signatures(award_id):
            existing = amount_index.get(signature)
            if existing is not None and existing[0] != entity_id:
                collisions.add(signature)
            else:
                amount_index[signature] = payload
    for signature in collisions:
        amount_index.pop(signature, None)

    qualifying: set[int] = set()
    for award_id, agency in contract_rows:
        if normalize_key(agency) not in defense_aliases:
            continue
        signatures = identifier_signatures(award_id)
        exact_payloads = {
            amount_index[signature]
            for signature in signatures
            if signature in amount_index
        }
        payload: tuple[int, float] | None
        if len(exact_payloads) == 1:
            payload = next(iter(exact_payloads))
        elif len(exact_payloads) > 1:
            # Ambiguous exact resolution is safer to skip than to invent a join.
            payload = None
        else:
            fuzzy = fuzzy_signature_match(signatures, amount_index, threshold=0.94)
            payload = fuzzy if isinstance(fuzzy, tuple) and len(fuzzy) == 2 else None
        if payload is not None:
            entity_id, amount = payload
            if amount > 1_000_000:
                qualifying.add(entity_id)
    return len(qualifying)
'''


def digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if digest(TARGET) != PARENT_SHA256:
        raise SystemExit("DAB slice parent candidate hash mismatch")
    source = TARGET.read_text(encoding="utf-8")
    if source.count(OLD) != 1:
        raise SystemExit("DAB slice patch target is not unique")
    TARGET.write_text(source.replace(OLD, NEW), encoding="utf-8")
    if digest(TARGET) != FINAL_SHA256:
        raise SystemExit("DAB slice patched candidate hash mismatch")
    print(f"Patched {TARGET} -> {FINAL_SHA256}")


if __name__ == "__main__":
    main()
