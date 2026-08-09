from __future__ import annotations

import base64
import gzip
import hashlib
import io
import re
import shutil
import subprocess
import tarfile
import zipfile
from collections import defaultdict
from pathlib import Path


ROOT = Path.cwd()
CAPSULE = ROOT / "logic_power_v10_capsule"
DECODE_ROOT = ROOT / "_logic_v10_decoded"
RUNTIME_ROOT = ROOT / "_finance_runtime"
EXPECTED_PRIVATE_HEAD = "ba10d0edc7eb20d499d0481fda2537e782b6efb2"


def _find_package(root: Path) -> Path | None:
    candidates: list[Path] = []
    for active in root.rglob("active_discovery.py"):
        package = active.parent
        if package.name != "logic_power_v10":
            continue
        if (package / "certificate.py").is_file() and (
            package / "__init__.py"
        ).is_file():
            candidates.append(package)
    if not candidates:
        return None
    return min(candidates, key=lambda item: (len(item.parts), str(item)))


def _base64_like(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        text = path.read_text(encoding="ascii")
    except (UnicodeDecodeError, OSError):
        return False
    compact = "".join(text.split())
    if len(compact) < 32:
        return False
    return re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact) is not None


def _group_key(path: Path) -> tuple[str, str]:
    name = re.sub(
        r"(?:[._-](?:part|chunk)?[._-]?\d+)+$",
        "",
        path.name,
        flags=re.IGNORECASE,
    )
    return str(path.parent), name


def _decode_payload(parts: list[Path]) -> bytes | None:
    compact = b"".join(
        b"".join(path.read_bytes().split())
        for path in sorted(parts, key=lambda item: str(item))
    )
    compact += b"=" * (-len(compact) % 4)
    for altchars in (None, b"-_"):
        try:
            return base64.b64decode(
                compact,
                altchars=altchars,
                validate=False,
            )
        except Exception:
            continue
    return None


def _safe_tar_extract(payload: bytes, destination: Path) -> bool:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            base = destination.resolve()
            for member in archive.getmembers():
                target = (destination / member.name).resolve()
                if target != base and base not in target.parents:
                    raise RuntimeError(f"unsafe tar member: {member.name}")
            archive.extractall(destination)
        return True
    except (tarfile.TarError, OSError):
        return False


def _safe_zip_extract(payload: bytes, destination: Path) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            base = destination.resolve()
            for name in archive.namelist():
                target = (destination / name).resolve()
                if target != base and base not in target.parents:
                    raise RuntimeError(f"unsafe zip member: {name}")
            archive.extractall(destination)
        return True
    except (zipfile.BadZipFile, OSError):
        return False


def _extract_payload(payload: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if _safe_tar_extract(payload, destination):
        return
    if _safe_zip_extract(payload, destination):
        return

    if payload.startswith(b"\x1f\x8b"):
        try:
            unpacked = gzip.decompress(payload)
        except OSError:
            unpacked = b""
        if unpacked:
            if _safe_tar_extract(unpacked, destination):
                return
            if _safe_zip_extract(unpacked, destination):
                return
            (destination / "decoded-gzip.bin").write_bytes(unpacked)
            return

    if payload.startswith(b"# v2 git bundle"):
        bundle = destination / "source.bundle"
        bundle.write_bytes(payload)
        clone = destination / "bundle-clone"
        subprocess.run(
            ["git", "clone", str(bundle), str(clone)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return

    (destination / "decoded.bin").write_bytes(payload)


def _overlay_plain_sources(target: Path) -> None:
    for source in CAPSULE.rglob("*.py"):
        parts = source.parts
        try:
            index = parts.index("logic_power_v10")
        except ValueError:
            continue
        relative = Path(*parts[index + 1 :])
        if not relative.parts:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _verify_head_binding() -> None:
    found = False
    for path in CAPSULE.rglob("*"):
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if EXPECTED_PRIVATE_HEAD in text:
            found = True
            break
    if not found:
        raise RuntimeError(
            "Logic Power v10 capsule is not bound to the expected private head"
        )


def reconstruct() -> Path:
    if not CAPSULE.is_dir():
        raise RuntimeError("logic_power_v10_capsule is missing")
    _verify_head_binding()

    direct = _find_package(CAPSULE)
    if direct is None:
        shutil.rmtree(DECODE_ROOT, ignore_errors=True)
        DECODE_ROOT.mkdir(parents=True)

        base64_files = [
            path for path in CAPSULE.rglob("*") if _base64_like(path)
        ]
        groups: dict[tuple[str, str], list[Path]] = defaultdict(list)
        for path in base64_files:
            groups[_group_key(path)].append(path)
            groups[(str(path.parent), "__all__")].append(path)

        seen_payloads: set[str] = set()
        for index, parts in enumerate(
            sorted(groups.values(), key=lambda items: [str(item) for item in items])
        ):
            payload = _decode_payload(parts)
            if not payload:
                continue
            digest = hashlib.sha256(payload).hexdigest()
            if digest in seen_payloads:
                continue
            seen_payloads.add(digest)
            _extract_payload(payload, DECODE_ROOT / f"candidate-{index:03d}")

        direct = _find_package(DECODE_ROOT)

    if direct is None:
        listing = "\n".join(
            str(path.relative_to(ROOT))
            for path in sorted(CAPSULE.rglob("*"))
            if path.is_file()
        )
        raise RuntimeError(
            "unable to reconstruct Logic Power v10; capsule files:\n" + listing
        )

    shutil.rmtree(RUNTIME_ROOT, ignore_errors=True)
    RUNTIME_ROOT.mkdir(parents=True)
    target = RUNTIME_ROOT / "logic_power_v10"
    shutil.copytree(direct, target)
    _overlay_plain_sources(target)

    required = {
        "__init__.py",
        "active_discovery.py",
        "certificate.py",
    }
    missing = sorted(
        name for name in required if not (target / name).is_file()
    )
    if missing:
        raise RuntimeError(f"reconstructed package is incomplete: {missing}")
    return RUNTIME_ROOT


if __name__ == "__main__":
    print(reconstruct())
