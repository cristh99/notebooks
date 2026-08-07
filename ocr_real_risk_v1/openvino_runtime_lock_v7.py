"""Fail-closed verification of the exact OpenVINO v7 quality runtime.

The lock is quality-only: it freezes every executable/package/native file that
can affect OCR or candidate inference, while explicitly refusing a speed claim.
Hosted-runner image labels and the full unrelated dpkg inventory are retained as
provenance, not treated as scientific identity. Verification must complete before
any OpenVINO source byte is read.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from .core import canonical_json, sha256_file

RUNTIME_SCHEMA = "eaat.openvino_v7_quality_runtime_lock/1"
RUNTIME_STATUS = "FROZEN_QUALITY_RUNTIME_NO_SPEED_CLAIM"
RUNTIME_ARTIFACT_ID = 8_992_594_936
RUNTIME_ARTIFACT_SHA256 = (
    "b75a52b7b7d4105e623a90a98243dd0db815d057c42bb700282df12c6ceaf190"
)
RUNTIME_LOCK_FILE_SHA256 = (
    "9d4896a53e88566fafb31df6b8b8286bf55e0d92509f7e9e75f7c5eb77be2e1e"
)
RUNTIME_STABLE_PAYLOAD_SHA256 = (
    "491f07bfc67e3e8c806f71f8cebd301670731642ed589c859e4cc62ec65ac821"
)
RUNTIME_IMAGE_OS = "ubuntu24"
RUNTIME_IMAGE_VERSION = "20260804.265.1"
RUNTIME_PYTHON_VERSION = "3.11.15"
RUNTIME_TESSERACT_VERSION = "5.3.4"
RUNTIME_TESSERACT_SOURCE_COMMIT = "8ee020e14cf5be4e3f0e9beb09b6b050a1871854"
RUNTIME_TESSERACT_BINARY_SHA256 = (
    "a3beae5dc9a3156b4de8d291eb4ea8a7f481bfc42985c5e831db9603a92824db"
)
RUNTIME_ENG_TRAINEDDATA_SHA256 = (
    "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
)
RUNTIME_PYTHON_EXECUTABLE_SHA256 = (
    "3d47c83556de5a94fb39905399cf8d7040be140c25c667bd34cb6d7eefd42075"
)
EXPECTED_PACKAGE_VERSIONS = {
    "Pillow": "12.2.0",
    "duckdb": "1.5.5",
    "joblib": "1.5.3",
    "numpy": "2.2.6",
    "opencv-python-headless": "4.10.0.84",
    "packaging": "26.3",
    "pyarrow": "18.1.0",
    "pytesseract": "0.3.13",
    "scikit-learn": "1.8.0",
    "scipy": "1.17.1",
    "threadpoolctl": "3.6.0",
}
EXPECTED_FILES = {
    "dpkg-packages.txt",
    "locale.txt",
    "lscpu.txt",
    "native-files.sha256",
    "os-release.txt",
    "pip-debug.txt",
    "python-files.sha256",
    "python-freeze.txt",
    "runner-metadata.json",
    "runtime-lock.json",
    "tesseract-version.txt",
    "uname.txt",
}
THREAD_ENV = {
    "PYTHONHASHSEED": "0",
    "OMP_THREAD_LIMIT": "1",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


def _sha(path: Path) -> str:
    return sha256_file(path)


def verifier_source_sha256() -> str:
    return _sha(Path(__file__).resolve())


def _verify_stable(payload: Mapping[str, Any]) -> bool:
    unsigned = dict(payload)
    observed = str(unsigned.pop("stable_payload_sha256", ""))
    return observed == hashlib.sha256(
        canonical_json(unsigned).encode("utf-8")
    ).hexdigest()


def _verify_hash_manifest(root: Path) -> None:
    manifest = root / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise RuntimeError("runtime lock lacks SHA256SUMS.txt")
    declared: set[str] = set()
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = raw.split("  ", 1)
        if relative in declared or relative not in EXPECTED_FILES:
            raise RuntimeError("runtime lock file-set drift")
        target = root / relative
        if not target.is_file() or _sha(target) != expected:
            raise RuntimeError(f"runtime lock hash mismatch: {relative}")
        declared.add(relative)
    if declared != EXPECTED_FILES:
        raise RuntimeError("runtime lock manifest is incomplete")
    observed = {
        path.name for path in root.iterdir() if path.is_file() and path.name != manifest.name
    }
    if observed != EXPECTED_FILES:
        raise RuntimeError("runtime lock contains undeclared files")


def _authorization_fields(authorization: Mapping[str, Any]) -> None:
    expected = {
        "runtime_lock_artifact_id": RUNTIME_ARTIFACT_ID,
        "runtime_lock_artifact_sha256": RUNTIME_ARTIFACT_SHA256,
        "runtime_lock_file_sha256": RUNTIME_LOCK_FILE_SHA256,
        "runtime_lock_stable_payload_sha256": RUNTIME_STABLE_PAYLOAD_SHA256,
        "runtime_image_os": RUNTIME_IMAGE_OS,
        "runtime_image_version": RUNTIME_IMAGE_VERSION,
        "runtime_python_version": RUNTIME_PYTHON_VERSION,
        "runtime_tesseract_version": RUNTIME_TESSERACT_VERSION,
        "runtime_required": True,
        "speed_claim_authorized": False,
        "runtime_verifier_source_sha256": verifier_source_sha256(),
    }
    for key, value in expected.items():
        if authorization.get(key) != value:
            raise RuntimeError(f"authorization runtime binding drift: {key}")


def _package_manifest() -> str:
    rows: list[str] = []
    for name in EXPECTED_PACKAGE_VERSIONS:
        dist = importlib.metadata.distribution(name)
        for item in dist.files or ():
            path = Path(dist.locate_file(item))
            if not path.is_file():
                continue
            resolved = path.resolve()
            rows.append(
                f"{name}\t{item.as_posix()}\t{_sha(resolved)}\t{resolved.stat().st_size}"
            )
    return "\n".join(sorted(rows)) + "\n"


def _native_manifest() -> str:
    candidates: set[Path] = {
        Path(sys.executable).resolve(),
        Path("/usr/local/bin/tesseract").resolve(),
    }
    for name in EXPECTED_PACKAGE_VERSIONS:
        dist = importlib.metadata.distribution(name)
        for item in dist.files or ():
            path = Path(dist.locate_file(item))
            if path.is_file() and (path.suffix == ".so" or ".so." in path.name):
                candidates.add(path.resolve())
    native: set[Path] = set()
    pattern = re.compile(r"(?:=>\s+)?(/[^\s]+)")
    for candidate in sorted(candidates):
        if not candidate.is_file():
            raise RuntimeError(f"missing native runtime file: {candidate}")
        native.add(candidate)
        result = subprocess.run(
            ["ldd", str(candidate)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise RuntimeError(f"ldd failed: {candidate}")
        for match in pattern.finditer(result.stdout):
            path = Path(match.group(1))
            if path.is_file():
                native.add(path.resolve())
    rows = [f"{path}\t{_sha(path)}\t{path.stat().st_size}" for path in sorted(native)]
    return "\n".join(rows) + "\n"


def _command_text(command: list[str]) -> str:
    return subprocess.check_output(command, text=True)


def _verify_current_runtime(root: Path, lock: Mapping[str, Any]) -> None:
    if platform.python_version() != RUNTIME_PYTHON_VERSION:
        raise RuntimeError("Python runtime version drift")
    if os.environ.get("ImageOS") != RUNTIME_IMAGE_OS:
        raise RuntimeError("GitHub runner image OS drift")
    if os.environ.get("RUNNER_OS") != "Linux" or os.environ.get("RUNNER_ARCH") != "X64":
        raise RuntimeError("GitHub runner platform drift")
    for key, expected in THREAD_ENV.items():
        if os.environ.get(key) != expected:
            raise RuntimeError(f"runtime environment drift: {key}")
    executable = Path(sys.executable).resolve()
    if (
        str(executable) != lock["python"]["executable"]
        or _sha(executable) != RUNTIME_PYTHON_EXECUTABLE_SHA256
    ):
        raise RuntimeError("Python executable identity drift")
    observed_versions = {
        name: importlib.metadata.version(name) for name in EXPECTED_PACKAGE_VERSIONS
    }
    if observed_versions != EXPECTED_PACKAGE_VERSIONS:
        raise RuntimeError("Python dependency version drift")
    if _package_manifest() != (root / "python-files.sha256").read_text(encoding="utf-8"):
        raise RuntimeError("Python package file identity drift")
    if _native_manifest() != (root / "native-files.sha256").read_text(encoding="utf-8"):
        raise RuntimeError("native library identity drift")
    freeze = (
        "\n".join(
            sorted(
                _command_text(
                    [sys.executable, "-m", "pip", "freeze", "--all"]
                ).splitlines()
            )
        )
        + "\n"
    )
    if freeze != (root / "python-freeze.txt").read_text(encoding="utf-8"):
        raise RuntimeError("pip freeze drift")
    tesseract = Path(lock["tesseract"]["binary"])
    traineddata = Path(lock["tesseract"]["eng_traineddata"])
    if _sha(tesseract) != RUNTIME_TESSERACT_BINARY_SHA256:
        raise RuntimeError("Tesseract binary drift")
    if _sha(traineddata) != RUNTIME_ENG_TRAINEDDATA_SHA256:
        raise RuntimeError("eng.traineddata drift")
    first = _command_text([str(tesseract), "--version"]).splitlines()[0]
    if first != f"tesseract {RUNTIME_TESSERACT_VERSION}":
        raise RuntimeError("Tesseract version drift")
    if _sha(Path("/etc/os-release")) != lock["system"]["os_release_sha256"]:
        raise RuntimeError("operating system identity drift")


def verify_runtime_lock(
    root: Path,
    authorization: Mapping[str, Any],
    *,
    verify_current: bool = True,
) -> dict[str, Any]:
    """Verify artifact, authorization, and executable dependency closure."""
    root = Path(root)
    _authorization_fields(authorization)
    _verify_hash_manifest(root)
    lock_path = root / "runtime-lock.json"
    if _sha(lock_path) != RUNTIME_LOCK_FILE_SHA256:
        raise RuntimeError("runtime lock file SHA-256 mismatch")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if (
        lock.get("schema") != RUNTIME_SCHEMA
        or lock.get("status") != RUNTIME_STATUS
        or lock.get("stable_payload_sha256") != RUNTIME_STABLE_PAYLOAD_SHA256
        or not _verify_stable(lock)
        or lock.get("runner", {}).get("image_os") != RUNTIME_IMAGE_OS
        or lock.get("runner", {}).get("image_version") != RUNTIME_IMAGE_VERSION
        or lock.get("platform", {}).get("python") != RUNTIME_PYTHON_VERSION
        or lock.get("tesseract", {}).get("version") != RUNTIME_TESSERACT_VERSION
        or lock.get("tesseract", {}).get("source_commit")
        != RUNTIME_TESSERACT_SOURCE_COMMIT
        or lock.get("execution", {}).get("quality_claim_authorized") is not True
        or lock.get("execution", {}).get("speed_claim_authorized") is not False
        or lock.get("execution", {}).get("scientific_execution_authorized") is not False
        or lock.get("execution", {}).get("openvino_scientific_images_opened") != 0
        or lock.get("execution", {}).get("ocr_runs") != 0
        or lock.get("execution", {}).get("candidate_inference_runs") != 0
    ):
        raise RuntimeError("runtime lock semantic contract failed")
    if verify_current:
        _verify_current_runtime(root, lock)
    return {
        "artifact_id": RUNTIME_ARTIFACT_ID,
        "artifact_zip_sha256": RUNTIME_ARTIFACT_SHA256,
        "runtime_lock_file_sha256": RUNTIME_LOCK_FILE_SHA256,
        "runtime_lock_stable_payload_sha256": RUNTIME_STABLE_PAYLOAD_SHA256,
        "runtime_verifier_source_sha256": verifier_source_sha256(),
        "image_os": RUNTIME_IMAGE_OS,
        "lock_creation_image_version": RUNTIME_IMAGE_VERSION,
        "host_image_version_enforced": False,
        "system_package_inventory_enforced": False,
        "executable_dependency_closure_enforced": True,
        "python": RUNTIME_PYTHON_VERSION,
        "tesseract": RUNTIME_TESSERACT_VERSION,
        "quality_claim_authorized": True,
        "speed_claim_authorized": False,
    }
