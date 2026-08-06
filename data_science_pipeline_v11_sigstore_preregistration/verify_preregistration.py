from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

SCHEMA = "data-science-pipeline/fresh-document-preregistration/1"
EXPECTED_REPOSITORY = "cristh99/notebooks"
EXPECTED_BASE_HEAD = "5707a9e777ca7ee2d216ce6580bab6575dd8b148"
EXPECTED_HOST = "oncae.gob.hn"
EXPECTED_PAGE_URL = (
    "https://oncae.gob.hn/biblioteca/manuales/catalogo-electronico/"
    "manual-de-usuario-para-compras-por-catalogo-electronico/"
)
EXPECTED_PAGE_TITLE = "Manual de usuario para compras por catálogo electrónico"
EXPECTED_DOWNLOAD_LABEL = "Manual de usuario Catálogo Electrónico Abril 2016"
EXPECTED_CONTENT_ALL = ("CATALOGO", "ELECTRONICO")
EXPECTED_CONTENT_ANY = ("MANUAL", "USUARIO")
REQUIRED_TERMINALS = {
    "MATCH_OFFICIAL",
    "MATCH_VALIDATED",
    "CANDIDATE_REVIEW",
    "NOT_EVALUABLE",
    "NO_MATCH_OBSERVED",
    "QUARANTINED",
    "BLOCKED_RESOURCE",
}
REQUIRED_PROMOTION_GATES = {
    "sigstore_attestation_verified",
    "source_page_and_pdf_hosts_allowlisted",
    "source_sha256_not_retired",
    "full_document_processed",
    "all_hard_claims_confirmed",
    "zero_quarantined_claims",
    "zero_false_amounts",
    "byte_identical_replay",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY = re.compile(r"(^|[_-])(secret|password|private[_-]?key|credential|api[_-]?key|access[_-]?token|auth[_-]?token)($|[_-])", re.I)


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _walk_keys(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _require(not _SECRET_KEY.search(str(key)), f"credential-like key forbidden at {path}.{key}")
            _walk_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_keys(child, f"{path}[{index}]")


def validate_payload(payload: dict[str, object]) -> dict[str, bool]:
    _require(payload.get("schema") == SCHEMA, "schema mismatch")
    _walk_keys(payload)

    preregistered_at = payload.get("preregistered_at")
    _require(isinstance(preregistered_at, str), "preregistered_at missing")
    parsed_time = datetime.fromisoformat(preregistered_at)
    _require(parsed_time.tzinfo is not None, "preregistered_at must include timezone")

    base = payload.get("base")
    _require(isinstance(base, dict), "base missing")
    _require(base.get("repository") == EXPECTED_REPOSITORY, "repository mismatch")
    _require(base.get("head_sha") == EXPECTED_BASE_HEAD, "base head mismatch")
    _require(bool(_SHA256.fullmatch(str(base.get("v10_receipt_sha256", "")))), "v10 receipt invalid")

    source = payload.get("source_selection")
    _require(isinstance(source, dict), "source_selection missing")
    _require(source.get("official_host") == EXPECTED_HOST, "official host mismatch")
    _require(source.get("official_page_url") == EXPECTED_PAGE_URL, "official page URL mismatch")
    parsed_url = urlparse(str(source.get("official_page_url", "")))
    _require(
        parsed_url.scheme == "https"
        and parsed_url.hostname == EXPECTED_HOST
        and parsed_url.username is None
        and parsed_url.password is None
        and not parsed_url.query
        and not parsed_url.fragment,
        "official page URL is not canonical HTTPS",
    )
    _require(source.get("visible_page_title") == EXPECTED_PAGE_TITLE, "page title mismatch")
    _require(source.get("visible_download_label") == EXPECTED_DOWNLOAD_LABEL, "download label mismatch")
    _require(source.get("selection_basis") == "official_page_metadata_only", "selection basis invalid")
    for field in ("pdf_url", "pdf_sha256", "pdf_bytes", "total_pages"):
        _require(source.get(field) is None, f"{field} must remain unknown before freeze")
    for field in (
        "pdf_url_resolved_before_freeze",
        "pdf_bytes_downloaded_before_freeze",
        "document_content_accessed_before_freeze",
    ):
        _require(source.get(field) is False, f"{field} must be false")

    freshness = payload.get("freshness")
    _require(isinstance(freshness, dict), "freshness missing")
    retired_hashes = freshness.get("retired_source_sha256")
    _require(isinstance(retired_hashes, list) and len(retired_hashes) >= 4, "retired hashes incomplete")
    _require(all(_SHA256.fullmatch(str(item)) for item in retired_hashes), "retired hash invalid")
    _require(len(retired_hashes) == len(set(retired_hashes)), "retired hashes duplicate")
    _require(freshness.get("candidate_not_previously_opened") is True, "freshness not asserted")
    _require(freshness.get("reuse_for_promotion_forbidden") is True, "reuse guard missing")

    channels = payload.get("channel_contract")
    _require(isinstance(channels, dict), "channel contract missing")
    _require(
        channels.get("source_provenance", {}).get("role") == "publisher_identity_only",
        "source provenance role invalid",
    )
    _require(
        channels.get("source_provenance", {}).get("required_validation")
        == "github_oidc_sigstore_attestation",
        "source provenance validation invalid",
    )
    _require(
        channels.get("document_metadata", {}).get("role") == "candidate_context_only"
        and channels.get("document_metadata", {}).get("can_confirm_content") is False,
        "metadata authority invalid",
    )
    _require(
        channels.get("ocr_content", {}).get("role") == "document_content_confirmation",
        "OCR role invalid",
    )
    _require(
        channels.get("native_control", {}).get("role") == "independent_diagnostic"
        and channels.get("native_control", {}).get("can_confirm_content") is False
        and channels.get("native_control", {}).get("ocr_miss_action") == "QUARANTINED",
        "native control role invalid",
    )

    evaluation = payload.get("evaluation_contract")
    _require(isinstance(evaluation, dict), "evaluation contract missing")
    scope = evaluation.get("document_scope")
    _require(isinstance(scope, dict), "document scope missing")
    _require(scope.get("full_document_required") is True, "full document required")
    _require(scope.get("maximum_pages") == 120, "page cap mismatch")
    _require(scope.get("maximum_bytes") == 40_000_000, "byte cap mismatch")
    _require(scope.get("oversize_terminal") == "BLOCKED_RESOURCE", "oversize terminal invalid")

    candidates = evaluation.get("ocr_candidates")
    _require(isinstance(candidates, list) and len(candidates) == 3, "OCR candidate set mismatch")
    candidate_names = [item.get("name") for item in candidates]
    _require(len(candidate_names) == len(set(candidate_names)), "OCR candidate names duplicate")
    _require(all(item.get("dpi") == 300 for item in candidates), "all OCR candidates must use 300 DPI")
    _require({item.get("psm") for item in candidates} == {3, 6, 11}, "PSM set mismatch")
    _require(evaluation.get("ocr_languages") == "spa+eng", "OCR languages mismatch")
    _require(
        evaluation.get("candidate_score")
        == "mean_confidence + 20*native_token_recall + word_count/(1+word_count)",
        "candidate score mismatch",
    )

    publisher = evaluation.get("publisher_claim")
    _require(isinstance(publisher, dict), "publisher claim missing")
    _require(
        publisher.get("expected_entity_id") == "hn:institution:oncae"
        and publisher.get("confirmation_channel") == "source_provenance",
        "publisher claim invalid",
    )

    content = evaluation.get("content_claim")
    _require(isinstance(content, dict), "content claim missing")
    _require(tuple(content.get("required_all_tokens", [])) == EXPECTED_CONTENT_ALL, "all-token set mismatch")
    _require(tuple(content.get("required_any_tokens", [])) == EXPECTED_CONTENT_ANY, "any-token set mismatch")
    _require(content.get("confirmation_channel") == "ocr_content", "content channel invalid")
    _require(content.get("native_control_role") == "diagnostic_only", "native control promoted")

    amount = evaluation.get("amount_guard")
    _require(isinstance(amount, dict), "amount guard missing")
    _require(amount.get("unqualified_year_is_not_money") is True, "year money guard missing")
    _require(
        amount.get("abstention_required_when_no_currency_qualified_amount") is True,
        "amount abstention missing",
    )
    _require("L 2016" in amount.get("forbidden_false_amount_surfaces", []), "2016 false amount guard missing")

    _require(set(evaluation.get("terminal_states", [])) == REQUIRED_TERMINALS, "terminal states mismatch")
    _require(set(evaluation.get("promotion_requires", [])) == REQUIRED_PROMOTION_GATES, "promotion gates mismatch")

    controls = payload.get("execution_controls")
    _require(isinstance(controls, dict), "execution controls missing")
    _require(controls.get("actual_external_evaluations") == 0, "external evaluation already occurred")
    _require(controls.get("maximum_external_evaluations") == 1, "evaluation count cap mismatch")
    _require(controls.get("post_result_retuning_permitted") is False, "retuning must be forbidden")
    _require(controls.get("merge_authorized") is False, "merge must remain unauthorized")
    _require(controls.get("production_modified") is False, "production must remain unmodified")
    _require(controls.get("mass_processing_authorized") is False, "mass processing must be unauthorized")
    _require(controls.get("external_cost_usd") == 0.0, "external cost must be zero")
    _require(controls.get("stage08_unblocked") is False, "Stage 08 must remain blocked")

    boundary = payload.get("claim_boundary")
    _require(isinstance(boundary, dict), "claim boundary missing")
    _require(boundary.get("scientific_promotion_credit_before_external_pass") == 0, "credit must be zero")
    _require("corruption" in boundary.get("does_not_establish", []), "corruption boundary missing")

    return {
        "schema_exact": True,
        "metadata_only_selection": True,
        "content_unopened": True,
        "freshness_guarded": True,
        "channel_authority_scoped": True,
        "full_document_required": True,
        "single_execution_frozen": True,
        "zero_cost_exact": True,
        "stage08_blocked": True,
        "credential_fields_absent": True,
    }


def validate_file(path: Path) -> dict[str, bool]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    _require(raw == canonical_bytes(payload), "preregistration file is not canonical JSON")
    return validate_payload(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    checks = validate_file(args.path)
    print(json.dumps({"verdict": "PASS", "checks": checks}, sort_keys=True))


if __name__ == "__main__":
    main()
