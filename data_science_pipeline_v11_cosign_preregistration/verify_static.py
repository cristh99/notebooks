from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

SCHEMA = "data-science-pipeline/fresh-document-preregistration/2"
EXPECTED_REPOSITORY = "cristh99/notebooks"
EXPECTED_BASE_SHA = "5707a9e777ca7ee2d216ce6580bab6575dd8b148"
EXPECTED_V10_RECEIPT = "780ee7d26299b91820fff686fc8332d047bb446e79f7edc8f8c88e2174b2cce3"
EXPECTED_PAGE_URL = (
    "https://oncae.gob.hn/biblioteca/manuales/catalogo-electronico/"
    "manual-de-usuario-para-compras-por-catalogo-electronico/"
)
EXPECTED_PAGE_TITLE = "Manual de usuario para compras por catálogo electrónico"
EXPECTED_DOWNLOAD_LABEL = "Manual de usuario Catálogo Electrónico Abril 2016"
EXPECTED_REF = "refs/heads/agent/data-science-v11-cosign-direct-oidc"
EXPECTED_WORKFLOW_REF = (
    "cristh99/notebooks/.github/workflows/data-science-v11-cosign-direct-oidc.yml"
    "@refs/heads/agent/data-science-v11-cosign-direct-oidc"
)
EXPECTED_CERT_IDENTITY = (
    "https://github.com/cristh99/notebooks/.github/workflows/"
    "data-science-v11-cosign-direct-oidc.yml"
    "@refs/heads/agent/data-science-v11-cosign-direct-oidc"
)
EXPECTED_SUBJECTS = {
    "repo:cristh99/notebooks:ref:refs/heads/agent/data-science-v11-cosign-direct-oidc",
    "repo:cristh99@87334928/notebooks@616013328:ref:refs/heads/agent/data-science-v11-cosign-direct-oidc",
}
EXPECTED_RETIRED_HASHES = {
    "5f278ec51106212a95a6f8c135cdfb8376724daab1e49b9ca0d3879543d11e85",
    "bf8860cd7e895b1cb2c86735638ddbdf7839538df844727a0938274b498785a7",
    "98a57e2306bb8f4632dfdadba6be813306f9c322b00ff8275a57460447a891c8",
    "c540e5e96140f3d0cb5d9f2115facac7bb39699e0a2f8f014045867a957f1b06",
}
EXPECTED_COSIGN_SHA = "c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74"
EXPECTED_TERMINALS = {
    "MATCH_OFFICIAL",
    "MATCH_VALIDATED",
    "CANDIDATE_REVIEW",
    "NOT_EVALUABLE",
    "NO_MATCH_OBSERVED",
    "QUARANTINED",
    "BLOCKED_RESOURCE",
}
EXPECTED_PROMOTION_GATES = {
    "sigstore_oidc_bundle_verified",
    "source_page_and_pdf_hosts_allowlisted",
    "source_sha256_not_retired",
    "full_document_processed",
    "all_hard_claims_confirmed",
    "zero_quarantined_claims",
    "zero_false_amounts",
    "byte_identical_replay",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_KEY_RE = re.compile(
    r"(^|[_-])(secret|password|private[_-]?key|credential|api[_-]?key|access[_-]?token|auth[_-]?token)($|[_-])",
    re.I,
)


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def walk_keys(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require(
                not SECRET_KEY_RE.search(str(key)),
                f"credential-like key forbidden at {path}.{key}",
            )
            walk_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_keys(child, f"{path}[{index}]")


def validate_payload(payload: dict[str, object]) -> dict[str, bool]:
    require(payload.get("schema") == SCHEMA, "schema mismatch")
    walk_keys(payload)

    timestamp = payload.get("preregistered_at")
    require(isinstance(timestamp, str), "preregistered_at missing")
    parsed = datetime.fromisoformat(timestamp)
    require(parsed.tzinfo is not None, "preregistered_at timezone missing")

    base = payload.get("base")
    require(isinstance(base, dict), "base missing")
    require(base.get("repository") == EXPECTED_REPOSITORY, "repository mismatch")
    require(base.get("head_sha") == EXPECTED_BASE_SHA, "base sha mismatch")
    require(
        base.get("v10_receipt_sha256") == EXPECTED_V10_RECEIPT,
        "v10 receipt mismatch",
    )

    source = payload.get("source_selection")
    require(isinstance(source, dict), "source_selection missing")
    require(source.get("official_host") == "oncae.gob.hn", "host mismatch")
    require(source.get("official_page_url") == EXPECTED_PAGE_URL, "page URL mismatch")
    parsed_url = urlparse(str(source.get("official_page_url", "")))
    require(
        parsed_url.scheme == "https"
        and parsed_url.hostname == "oncae.gob.hn"
        and parsed_url.username is None
        and parsed_url.password is None
        and not parsed_url.query
        and not parsed_url.fragment,
        "page URL not canonical HTTPS",
    )
    require(source.get("visible_page_title") == EXPECTED_PAGE_TITLE, "title mismatch")
    require(
        source.get("visible_download_label") == EXPECTED_DOWNLOAD_LABEL,
        "download label mismatch",
    )
    require(
        source.get("selection_basis") == "official_page_metadata_only",
        "selection basis mismatch",
    )
    for field in ("pdf_url", "pdf_sha256", "pdf_bytes", "total_pages"):
        require(source.get(field) is None, f"{field} must remain unknown")
    for field in (
        "pdf_url_resolved_before_freeze",
        "pdf_bytes_downloaded_before_freeze",
        "document_content_accessed_before_freeze",
    ):
        require(source.get(field) is False, f"{field} must be false")

    freshness = payload.get("freshness")
    require(isinstance(freshness, dict), "freshness missing")
    retired = freshness.get("retired_source_sha256")
    require(isinstance(retired, list), "retired hashes missing")
    require(set(retired) == EXPECTED_RETIRED_HASHES, "retired hash set mismatch")
    require(len(retired) == len(set(retired)), "retired hashes duplicate")
    require(
        all(isinstance(item, str) and SHA256_RE.fullmatch(item) for item in retired),
        "retired hash invalid",
    )
    require(freshness.get("candidate_not_previously_opened") is True, "freshness false")
    require(
        freshness.get("reuse_for_promotion_forbidden") is True,
        "reuse guard missing",
    )

    trust = payload.get("trust_contract")
    require(isinstance(trust, dict), "trust contract missing")
    require(
        trust.get("mechanism") == "github_actions_oidc_sigstore_cosign_keyless",
        "trust mechanism mismatch",
    )
    require(
        trust.get("oidc_issuer") == "https://token.actions.githubusercontent.com",
        "issuer mismatch",
    )
    require(trust.get("oidc_audience") == "sigstore", "audience mismatch")
    require(trust.get("repository") == EXPECTED_REPOSITORY, "trust repo mismatch")
    require(trust.get("repository_id") == "616013328", "repository id mismatch")
    require(trust.get("repository_owner_id") == "87334928", "owner id mismatch")
    require(trust.get("repository_visibility") == "public", "visibility mismatch")
    require(trust.get("ref") == EXPECTED_REF, "ref mismatch")
    require(trust.get("workflow_ref") == EXPECTED_WORKFLOW_REF, "workflow ref mismatch")
    require(
        trust.get("certificate_identity") == EXPECTED_CERT_IDENTITY,
        "certificate identity mismatch",
    )
    require(set(trust.get("allowed_oidc_subjects", [])) == EXPECTED_SUBJECTS, "subject set mismatch")
    require(trust.get("github_hosted_runner_required") is True, "hosted runner guard missing")
    require(
        trust.get("subject_path")
        == "data_science_pipeline_v11_cosign_preregistration/PREREGISTRATION.json",
        "subject path mismatch",
    )
    require(trust.get("cosign_version") == "3.0.6", "cosign version mismatch")
    require(
        trust.get("cosign_linux_amd64_sha256") == EXPECTED_COSIGN_SHA,
        "cosign hash mismatch",
    )
    for field in (
        "sigstore_bundle_required",
        "transparency_log_inclusion_required",
        "explicit_identity_token_required",
    ):
        require(trust.get(field) is True, f"{field} must be true")

    channels = payload.get("channel_contract")
    require(isinstance(channels, dict), "channel contract missing")
    require(
        channels.get("source_provenance", {}).get("required_validation")
        == "github_oidc_cosign_bundle",
        "provenance validation mismatch",
    )
    require(
        channels.get("document_metadata", {}).get("role") == "candidate_context_only"
        and channels.get("document_metadata", {}).get("can_confirm_content") is False,
        "metadata authority invalid",
    )
    require(
        channels.get("native_control", {}).get("role") == "independent_diagnostic"
        and channels.get("native_control", {}).get("can_confirm_content") is False,
        "native authority invalid",
    )

    evaluation = payload.get("evaluation_contract")
    require(isinstance(evaluation, dict), "evaluation contract missing")
    scope = evaluation.get("document_scope")
    require(isinstance(scope, dict), "scope missing")
    require(scope.get("full_document_required") is True, "full document guard missing")
    require(scope.get("maximum_pages") == 120, "page cap mismatch")
    require(scope.get("maximum_bytes") == 40_000_000, "byte cap mismatch")
    require(scope.get("oversize_terminal") == "BLOCKED_RESOURCE", "oversize terminal mismatch")

    candidates = evaluation.get("ocr_candidates")
    require(isinstance(candidates, list) and len(candidates) == 3, "candidate set mismatch")
    require({item.get("psm") for item in candidates} == {3, 6, 11}, "PSM set mismatch")
    require(all(item.get("dpi") == 300 for item in candidates), "DPI mismatch")
    require(
        evaluation.get("candidate_score")
        == "mean_confidence + 20*native_token_recall + word_count/(1+word_count)",
        "score mismatch",
    )
    require(set(evaluation.get("terminal_states", [])) == EXPECTED_TERMINALS, "terminal set mismatch")
    require(
        set(evaluation.get("promotion_requires", [])) == EXPECTED_PROMOTION_GATES,
        "promotion gate set mismatch",
    )
    require(
        evaluation.get("amount_guard", {}).get("unqualified_year_is_not_money") is True,
        "year money guard missing",
    )

    controls = payload.get("execution_controls")
    require(isinstance(controls, dict), "execution controls missing")
    require(controls.get("actual_external_evaluations") == 0, "external evaluation already occurred")
    require(controls.get("maximum_external_evaluations") == 1, "evaluation cap mismatch")
    require(controls.get("post_result_retuning_permitted") is False, "retuning must be false")
    require(controls.get("merge_authorized") is False, "merge must be false")
    require(controls.get("production_modified") is False, "production must be false")
    require(controls.get("mass_processing_authorized") is False, "mass processing must be false")
    require(controls.get("gcloud_used") is False, "GCloud must be false")
    require(controls.get("paid_compute_used") is False, "paid compute must be false")
    require(controls.get("external_cost_usd") == 0.0, "cost must be zero")
    require(controls.get("stage08_unblocked") is False, "Stage 08 must remain blocked")

    boundary = payload.get("claim_boundary")
    require(isinstance(boundary, dict), "claim boundary missing")
    require(
        boundary.get("scientific_promotion_credit_before_external_document_pass") == 0,
        "promotion credit must be zero",
    )
    require("corruption" in boundary.get("signature_does_not_establish", []), "corruption boundary missing")
    require("truth_of_preregistration_declarations" in boundary.get("signature_does_not_establish", []), "truth boundary missing")

    return {
        "schema_exact": True,
        "canonical_metadata_only_selection": True,
        "freshness_guarded": True,
        "trust_identity_pinned": True,
        "cosign_binary_hash_pinned": True,
        "channel_authority_scoped": True,
        "full_document_required": True,
        "single_external_execution_frozen": True,
        "zero_cost_exact": True,
        "stage08_blocked": True,
        "credential_fields_absent": True,
    }


def validate_file(path: Path) -> dict[str, bool]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    require(raw == canonical_bytes(payload), "preregistration file is not canonical JSON")
    return validate_payload(payload)
