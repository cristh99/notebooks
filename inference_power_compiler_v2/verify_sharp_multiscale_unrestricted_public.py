from __future__ import annotations

import base64
from hashlib import sha256
import lzma
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "sharp_multiscale_unrestricted_public_source.py.xz.b64"
SOURCE_SHA256 = "8f7d037f62cd930aaafe8e7da8dc1b97ac7913170ccd02bc8937d349f9f237e3"


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
