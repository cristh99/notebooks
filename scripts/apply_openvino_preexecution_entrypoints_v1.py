from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_runner() -> None:
    path = "ocr_real_risk_v1/openvino_full_gate_runner_v7.py"
    replace_once(
        path,
        "from .openvino_full_gate_registry_v7 import (\n"
        "    _image_id_from_path,\n"
        "    verify_registry_bundle,\n"
        ")\n\n\ndef _load_model",
        "from .openvino_full_gate_registry_v7 import (\n"
        "    _image_id_from_path,\n"
        "    verify_registry_bundle,\n"
        ")\n"
        "from .openvino_preexecution_gate_v7 import verify_preexecution_gate\n\n\ndef _load_model",
    )
    replace_once(
        path,
        "def _verify_registry_for_execution(\n"
        "    registry_root: Path,\n"
        "    authorization: Mapping[str, Any],\n"
        "    expected_binding: Mapping[str, Any],\n"
        ") -> dict[str, Any]:",
        "def _verify_registry_for_execution(\n"
        "    registry_root: Path,\n"
        "    authorization: Mapping[str, Any],\n"
        "    expected_binding: Mapping[str, Any],\n"
        "    expected_preexecution: Mapping[str, Any],\n"
        ") -> dict[str, Any]:",
    )
    replace_once(
        path,
        "        summary.get(\"evaluation_authorized\") is not True\n"
        "        or receipt.get(\"authorization_binding\") != expected_binding\n",
        "        summary.get(\"evaluation_authorized\") is not True\n"
        "        or receipt.get(\"authorization_binding\") != expected_binding\n"
        "        or receipt.get(\"preexecution_binding\") != expected_preexecution\n",
    )
    replace_once(
        path,
        "    authorization = verify_bound_execution_authorization(\n"
        "        authorization_path, authorization_sha256, \"EVALUATE_PARTITIONS\"\n"
        "    )\n"
        "    claim = verify_execution_claim(\n",
        "    authorization = verify_bound_execution_authorization(\n"
        "        authorization_path, authorization_sha256, \"EVALUATE_PARTITIONS\"\n"
        "    )\n"
        "    preexecution = verify_preexecution_gate(authorization)\n"
        "    claim = verify_execution_claim(\n",
    )
    replace_once(
        path,
        "    registry_summary = _verify_registry_for_execution(\n"
        "        registry_root, authorization, expected_binding\n"
        "    )\n",
        "    registry_summary = _verify_registry_for_execution(\n"
        "        registry_root, authorization, expected_binding, preexecution\n"
        "    )\n",
    )
    replace_once(
        path,
        "            \"authorization_binding\": expected_binding,\n"
        "            \"code_bundle\": code_bundle,\n",
        "            \"authorization_binding\": expected_binding,\n"
        "            \"preexecution_binding\": preexecution,\n"
        "            \"code_bundle\": code_bundle,\n",
    )


def patch_aggregate() -> None:
    path = "ocr_real_risk_v1/openvino_full_gate_aggregate_v7.py"
    replace_once(
        path,
        "from .openvino_full_gate_registry_v7 import verify_registry_bundle\n",
        "from .openvino_full_gate_registry_v7 import verify_registry_bundle\n"
        "from .openvino_preexecution_gate_v7 import verify_preexecution_gate\n",
    )
    replace_once(
        path,
        "def _validate_report_identity(\n"
        "    report: Mapping[str, Any],\n"
        "    *,\n"
        "    expected_code_bundle: Mapping[str, str],\n"
        "    authorization_binding: Mapping[str, Any],\n"
        ") -> None:",
        "def _validate_report_identity(\n"
        "    report: Mapping[str, Any],\n"
        "    *,\n"
        "    expected_code_bundle: Mapping[str, str],\n"
        "    authorization_binding: Mapping[str, Any],\n"
        "    expected_preexecution: Mapping[str, Any] | None = None,\n"
        ") -> None:",
    )
    replace_once(
        path,
        "        report.get(\"authorization_binding\") != authorization_binding\n"
        "        or report.get(\"code_bundle\") != expected_code_bundle\n",
        "        report.get(\"authorization_binding\") != authorization_binding\n"
        "        or (\n"
        "            expected_preexecution is not None\n"
        "            and report.get(\"preexecution_binding\") != expected_preexecution\n"
        "        )\n"
        "        or report.get(\"code_bundle\") != expected_code_bundle\n",
    )
    replace_once(
        path,
        "    expected_code_bundle: Mapping[str, str],\n"
        "    authorization_binding: Mapping[str, Any],\n"
        "    minimum_active: int = MINIMUM_ACTIVE_AFTER_DEDUP,\n",
        "    expected_code_bundle: Mapping[str, str],\n"
        "    authorization_binding: Mapping[str, Any],\n"
        "    expected_preexecution: Mapping[str, Any] | None = None,\n"
        "    minimum_active: int = MINIMUM_ACTIVE_AFTER_DEDUP,\n",
    )
    replace_once(
        path,
        "            expected_code_bundle=expected_code_bundle,\n"
        "            authorization_binding=authorization_binding,\n"
        "        )\n",
        "            expected_code_bundle=expected_code_bundle,\n"
        "            authorization_binding=authorization_binding,\n"
        "            expected_preexecution=expected_preexecution,\n"
        "        )\n",
    )
    replace_once(
        path,
        "        \"authorization_binding\": authorization_binding,\n"
        "        \"code_bundle\": dict(expected_code_bundle),\n",
        "        \"authorization_binding\": authorization_binding,\n"
        "        \"preexecution_binding\": expected_preexecution,\n"
        "        \"code_bundle\": dict(expected_code_bundle),\n",
    )
    replace_once(
        path,
        "    authorization = verify_bound_execution_authorization(\n"
        "        authorization_path, authorization_sha256, \"AGGREGATE\"\n"
        "    )\n"
        "    claim = verify_execution_claim(\n",
        "    authorization = verify_bound_execution_authorization(\n"
        "        authorization_path, authorization_sha256, \"AGGREGATE\"\n"
        "    )\n"
        "    preexecution = verify_preexecution_gate(authorization)\n"
        "    claim = verify_execution_claim(\n",
    )
    replace_once(
        path,
        "        registry.get(\"evaluation_authorized\") is not True\n"
        "        or registry.get(\"authorization_binding\") != expected_binding\n"
        "        or registry_receipt.get(\"code_bundle\") != authorization[\"code_bundle\"]\n",
        "        registry.get(\"evaluation_authorized\") is not True\n"
        "        or registry.get(\"authorization_binding\") != expected_binding\n"
        "        or registry_receipt.get(\"preexecution_binding\") != preexecution\n"
        "        or registry_receipt.get(\"code_bundle\") != authorization[\"code_bundle\"]\n",
    )
    replace_once(
        path,
        "        expected_code_bundle=authorization[\"code_bundle\"],\n"
        "        authorization_binding=expected_binding,\n"
        "    )\n",
        "        expected_code_bundle=authorization[\"code_bundle\"],\n"
        "        authorization_binding=expected_binding,\n"
        "        expected_preexecution=preexecution,\n"
        "    )\n",
    )


def main() -> None:
    patch_runner()
    patch_aggregate()


if __name__ == "__main__":
    main()
