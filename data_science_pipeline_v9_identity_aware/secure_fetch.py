from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from facts_contract import canonical_json_bytes


class FetchValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchContract:
    url: str
    allowed_hosts: tuple[str, ...]
    expected_media_types: tuple[str, ...]
    min_bytes: int
    max_bytes: int
    timeout_seconds: float = 60.0
    max_redirects: int = 3
    required_magic: bytes | None = None


def _host_key(host: str) -> str:
    return host.rstrip(".").casefold()


def validate_url(url: str, allowed_hosts: Sequence[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme.casefold() != "https":
        raise FetchValidationError("only HTTPS URLs are allowed")
    if parsed.username or parsed.password:
        raise FetchValidationError("userinfo in URL is forbidden")
    if parsed.port not in {None, 443}:
        raise FetchValidationError("only TCP port 443 is allowed")
    if not parsed.hostname:
        raise FetchValidationError("URL hostname is missing")
    allowed = {_host_key(host) for host in allowed_hosts}
    if _host_key(parsed.hostname) not in allowed:
        raise FetchValidationError(f"host is not allowlisted: {parsed.hostname}")


def resolve_public_addresses(host: str, port: int = 443) -> tuple[str, ...]:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchValidationError(f"DNS resolution failed for {host}: {exc}") from exc
    addresses = {ipaddress.ip_address(answer[4][0]) for answer in answers}
    if not addresses:
        raise FetchValidationError(f"DNS returned no addresses for {host}")
    unsafe = sorted(
        str(address)
        for address in addresses
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
    )
    if unsafe:
        raise FetchValidationError(f"host {host} resolved to non-public addresses: {unsafe}")
    return tuple(sorted(str(address) for address in addresses))


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, *, pinned_addresses: Sequence[str], **kwargs: Any) -> None:
        self._pinned_addresses = tuple(pinned_addresses)
        if not self._pinned_addresses:
            raise FetchValidationError("no pinned public addresses")
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        last_error: OSError | None = None
        for address in self._pinned_addresses:
            sock = None
            try:
                sock = socket.create_connection((address, self.port), self.timeout, self.source_address)
                if self._tunnel_host:
                    self.sock = sock
                    self._tunnel()
                    sock = self.sock
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as exc:
                last_error = exc
                if sock is not None:
                    sock.close()
        raise OSError(f"all pinned public addresses failed: {last_error}")


class PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, contract: FetchContract) -> None:
        super().__init__(context=ssl.create_default_context())
        self.contract = contract

    def https_open(self, request):
        parsed = urlparse(request.full_url)
        validate_url(request.full_url, self.contract.allowed_hosts)
        assert parsed.hostname is not None
        addresses = resolve_public_addresses(parsed.hostname, parsed.port or 443)

        def factory(host: str, **kwargs: Any) -> PinnedHTTPSConnection:
            return PinnedHTTPSConnection(host, pinned_addresses=addresses, **kwargs)

        return self.do_open(factory, request)


class LimitedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, contract: FetchContract) -> None:
        super().__init__()
        self.contract = contract
        self.redirect_count = 0

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        if self.redirect_count > self.contract.max_redirects:
            raise HTTPError(newurl, code, "redirect limit exceeded", headers, fp)
        validate_url(newurl, self.contract.allowed_hosts)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _content_type(headers: Any) -> str:
    value = str(headers.get("Content-Type", "")).split(";", 1)[0].strip().casefold()
    return value


def fetch(contract: FetchContract, output: Path, receipt_path: Path) -> dict[str, Any]:
    validate_url(contract.url, contract.allowed_hosts)
    if contract.min_bytes < 0 or contract.max_bytes < contract.min_bytes:
        raise FetchValidationError("invalid byte bounds")
    redirect_handler = LimitedRedirectHandler(contract)
    opener = build_opener(ProxyHandler({}), redirect_handler, PinnedHTTPSHandler(contract))
    request = Request(
        contract.url,
        headers={
            "User-Agent": "EVIDENCIA_PUBLICA-DataSciencePipeline/9",
            "Accept": ", ".join(contract.expected_media_types),
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    digest = hashlib.sha256()
    total = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    temporary.unlink(missing_ok=True)
    try:
        with opener.open(request, timeout=contract.timeout_seconds) as response, temporary.open("wb") as handle:
            status = int(response.getcode())
            if status != 200:
                raise FetchValidationError(f"unexpected HTTP status: {status}")
            final_url = str(response.geturl())
            validate_url(final_url, contract.allowed_hosts)
            media_type = _content_type(response.headers)
            expected = {item.casefold() for item in contract.expected_media_types}
            if media_type not in expected:
                raise FetchValidationError(f"unexpected media type: {media_type!r}")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_int = int(declared)
                except ValueError as exc:
                    raise FetchValidationError("invalid Content-Length") from exc
                if declared_int > contract.max_bytes:
                    raise FetchValidationError("declared body exceeds maximum size")
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > contract.max_bytes:
                    raise FetchValidationError("body exceeds maximum size")
                digest.update(chunk)
                handle.write(chunk)
    except (HTTPError, URLError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, FetchValidationError):
            raise
        raise FetchValidationError(f"fetch failed: {exc}") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    if total < contract.min_bytes:
        temporary.unlink(missing_ok=True)
        raise FetchValidationError(f"body is smaller than minimum: {total}")
    if contract.required_magic is not None:
        with temporary.open("rb") as handle:
            actual_magic = handle.read(len(contract.required_magic))
        if actual_magic != contract.required_magic:
            temporary.unlink(missing_ok=True)
            raise FetchValidationError("required file magic is missing")
    temporary.replace(output)
    parsed_final = urlparse(final_url)
    receipt = {
        "schema": "data-science-pipeline/secure-fetch-receipt/1",
        "verdict": "PASS",
        "requested_url": contract.url,
        "final_url": final_url,
        "final_host": _host_key(parsed_final.hostname or ""),
        "allowed_hosts": sorted({_host_key(host) for host in contract.allowed_hosts}),
        "status": status,
        "content_type": media_type,
        "bytes": total,
        "sha256": digest.hexdigest(),
        "redirects": redirect_handler.redirect_count,
        "dns_pinned": True,
        "ambient_proxies_disabled": True,
        "magic": None if contract.required_magic is None else contract.required_magic.decode("ascii", errors="strict"),
        "output_name": output.name,
    }
    payload = canonical_json_bytes(receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(payload)
    receipt_digest = hashlib.sha256(payload).hexdigest()
    receipt_path.with_suffix(receipt_path.suffix + ".sha256").write_text(
        f"{receipt_digest}  {receipt_path.name}\n", encoding="utf-8"
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--allowed-host", action="append", required=True)
    parser.add_argument("--media-type", action="append", required=True)
    parser.add_argument("--min-bytes", type=int, required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-redirects", type=int, default=3)
    parser.add_argument("--magic")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    contract = FetchContract(
        url=args.url,
        allowed_hosts=tuple(args.allowed_host),
        expected_media_types=tuple(args.media_type),
        min_bytes=args.min_bytes,
        max_bytes=args.max_bytes,
        timeout_seconds=args.timeout,
        max_redirects=args.max_redirects,
        required_magic=None if args.magic is None else args.magic.encode("ascii"),
    )
    result = fetch(contract, args.output, args.receipt)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
