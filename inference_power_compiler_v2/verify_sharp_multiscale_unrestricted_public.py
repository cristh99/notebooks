from __future__ import annotations

import base64
from hashlib import sha256
import lzma
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "sharp_multiscale_unrestricted_public_source.py.xz.b64"
SOURCE_SHA256 = "bbcab12adcf702cb6324c0448c266b50d54bf0e58cceca86940da4c0d99297fd"


def decoded_source() -> bytes:
    encoded = "".join(PAYLOAD.read_text(encoding="ascii").split())
    source = lzma.decompress(base64.b64decode(encoded, validate=True))
    actual = sha256(source).hexdigest()
    if actual != SOURCE_SHA256:
        raise RuntimeError(f"decoded verifier digest mismatch: {actual}")
    return source


def main() -> None:
    source = decoded_source()
    if len(sys.argv) == 3 and sys.argv[1] == "--emit-source":
        Path(sys.argv[2]).write_bytes(source)
        return
    code = compile(source, str(Path(__file__).resolve()), "exec")
    namespace = {
        "__name__": "__main__",
        "__file__": str(Path(__file__).resolve()),
        "__package__": None,
    }
    exec(code, namespace)


if __name__ == "__main__":
    main()
