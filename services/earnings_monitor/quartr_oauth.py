"""OAuth for the Quartr MCP server, so the calendar sweep can run unattended.

Quartr's MCP endpoint is OAuth-protected and its authorization server offers
only ``authorization_code`` and ``refresh_token`` -- there is no
``client_credentials`` grant, so a token cannot be minted from a secret alone.
What it does support is a long-lived refresh token, which is enough: a human
signs in through the browser exactly once, and every run after that mints its
own access token with no browser, no API key and no Cursor session.

The client is public (``token_endpoint_auth_methods_supported: ["none"]``), so
there is no client secret to protect -- but the refresh token IS a credential
and lives in a gitignored file with no other copy.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Mapping

LOG = logging.getLogger(__name__)

MCP_RESOURCE = "https://mcp.quartr.com/mcp"
PROTECTED_RESOURCE_METADATA = (
    "https://mcp.quartr.com/.well-known/oauth-protected-resource/mcp"
)
SCOPE = "mcp:tools"
CLIENT_NAME = "roz-earnings-monitor"

# Refresh a little early: a token that expires mid-sweep fails the whole run.
EXPIRY_SKEW_SECONDS = 120

DEFAULT_TOKEN_REL = Path("host_quartr") / ".quartr_oauth.json"


class QuartrAuthError(RuntimeError):
    """Auth is unusable and a human must sign in again."""


@dataclass
class TokenSet:
    access_token: str = ""
    refresh_token: str = ""
    client_id: str = ""
    expires_at: float = 0.0

    @property
    def expired(self) -> bool:
        return time.time() >= (self.expires_at - EXPIRY_SKEW_SECONDS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "expires_at": self.expires_at,
        }


def default_token_path(repo_root: Path | str | None = None) -> Path:
    override = os.environ.get("QUARTR_OAUTH_TOKEN_PATH")
    if override:
        return Path(override)
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return root / DEFAULT_TOKEN_REL


def load_tokens(path: Path | str) -> TokenSet:
    target = Path(path)
    if not target.is_file():
        return TokenSet()
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QuartrAuthError(f"unreadable token file {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise QuartrAuthError(f"token file must be an object: {target}")
    return TokenSet(
        access_token=str(payload.get("access_token") or ""),
        refresh_token=str(payload.get("refresh_token") or ""),
        client_id=str(payload.get("client_id") or ""),
        expires_at=float(payload.get("expires_at") or 0.0),
    )


def save_tokens(path: Path | str, tokens: TokenSet) -> Path:
    """Write tokens 0600-ish, atomically, creating parents as needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(tokens.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:  # pragma: no cover - best effort on Windows
        pass
    os.replace(temporary, target)
    return target


def _post_form(url: str, fields: Mapping[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise QuartrAuthError(f"{url} returned {exc.code}: {detail}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise QuartrAuthError(f"{url} failed: {exc}") from exc


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        raise QuartrAuthError(f"{url} failed: {exc}") from exc


def discover_endpoints() -> dict[str, str]:
    """Resolve authorize/token/register from RFC 8414 metadata.

    Discovered rather than hardcoded: the authorization server is free to move
    these, and a stale constant would fail as an opaque 404 during a sweep.
    """
    meta = _get_json(PROTECTED_RESOURCE_METADATA)
    servers = meta.get("authorization_servers") or []
    if not servers:
        raise QuartrAuthError("no authorization_servers in resource metadata")
    issuer = str(servers[0]).rstrip("/")
    for suffix in (
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
    ):
        try:
            doc = _get_json(issuer + suffix)
        except QuartrAuthError:
            continue
        if doc.get("token_endpoint"):
            return {
                "issuer": str(doc.get("issuer") or issuer),
                "authorization_endpoint": str(doc["authorization_endpoint"]),
                "token_endpoint": str(doc["token_endpoint"]),
                "registration_endpoint": str(doc.get("registration_endpoint") or ""),
            }
    raise QuartrAuthError(f"no usable authorization-server metadata at {issuer}")


def register_client(registration_endpoint: str, redirect_uri: str) -> str:
    """RFC 7591 dynamic registration -> client_id (public client, no secret)."""
    body = json.dumps(
        {
            "client_name": CLIENT_NAME,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPE,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        registration_endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise QuartrAuthError(
            f"client registration returned {exc.code}: {detail}"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise QuartrAuthError(f"client registration failed: {exc}") from exc
    client_id = str(payload.get("client_id") or "")
    if not client_id:
        raise QuartrAuthError("registration response had no client_id")
    return client_id


class _CallbackHandler(BaseHTTPRequestHandler):
    """Single-shot loopback receiver for the authorization code."""

    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        type(self).result = {k: v[0] for k, v in params.items()}
        ok = "code" in type(self).result
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        message = (
            "<h2>Quartr connected.</h2><p>You can close this tab and return "
            "to the terminal.</p>"
            if ok
            else f"<h2>Authorization failed.</h2><pre>{type(self).result}</pre>"
        )
        self.write_body(message)

    def write_body(self, message: str) -> None:
        self.wfile.write(f"<html><body>{message}</body></html>".encode("utf-8"))

    def log_message(self, *args: Any) -> None:  # noqa: A003 - silence stdlib logging
        return


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def interactive_login(
    token_path: Path | str,
    *,
    port: int = 0,
    open_browser: bool = True,
    timeout_seconds: float = 300.0,
) -> TokenSet:
    """One-time browser sign-in. Persists a refresh token for unattended runs."""
    endpoints = discover_endpoints()
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    bound_port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{bound_port}/callback"
    _CallbackHandler.result = {}

    client_id = register_client(endpoints["registration_endpoint"], redirect_uri)
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # RFC 8707: bind the token to this MCP resource.
            "resource": MCP_RESOURCE,
        }
    )
    auth_url = f"{endpoints['authorization_endpoint']}?{query}"

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    print("\nOpen this URL to connect Quartr (one time only):\n")
    print(auth_url + "\n")
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:  # pragma: no cover - headless box
            pass
    thread.join(timeout=timeout_seconds)
    server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise QuartrAuthError(
            f"no callback received within {timeout_seconds:.0f}s on {redirect_uri}"
        )
    if result.get("state") != state:
        raise QuartrAuthError("state mismatch on OAuth callback")
    if "code" not in result:
        raise QuartrAuthError(f"authorization failed: {result}")

    payload = _post_form(
        endpoints["token_endpoint"],
        {
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": MCP_RESOURCE,
        },
    )
    tokens = _tokens_from_payload(payload, client_id=client_id)
    if not tokens.refresh_token:
        raise QuartrAuthError(
            "Quartr issued no refresh_token; unattended runs are not possible"
        )
    save_tokens(token_path, tokens)
    return tokens


def _tokens_from_payload(
    payload: Mapping[str, Any], *, client_id: str, previous: TokenSet | None = None
) -> TokenSet:
    access = str(payload.get("access_token") or "")
    if not access:
        raise QuartrAuthError(f"token response had no access_token: {payload}")
    # Rotation is optional; keep the old refresh token when none comes back.
    refresh = str(
        payload.get("refresh_token") or (previous.refresh_token if previous else "")
    )
    expires_in = float(payload.get("expires_in") or 3600)
    return TokenSet(
        access_token=access,
        refresh_token=refresh,
        client_id=client_id,
        expires_at=time.time() + expires_in,
    )


def refresh_tokens(token_path: Path | str, tokens: TokenSet) -> TokenSet:
    if not tokens.refresh_token or not tokens.client_id:
        raise QuartrAuthError("no refresh token on file; run `quartr login` first")
    endpoints = discover_endpoints()
    payload = _post_form(
        endpoints["token_endpoint"],
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": tokens.client_id,
            "resource": MCP_RESOURCE,
        },
    )
    refreshed = _tokens_from_payload(
        payload, client_id=tokens.client_id, previous=tokens
    )
    save_tokens(token_path, refreshed)
    return refreshed


def get_access_token(token_path: Path | str) -> str:
    """Token for an unattended run. Raises when a human must sign in again."""
    tokens = load_tokens(token_path)
    if not tokens.refresh_token:
        raise QuartrAuthError(
            f"Quartr is not connected (no token at {token_path}). Run:\n"
            "  python -m services.earnings_monitor.host_automation quartr login"
        )
    if tokens.access_token and not tokens.expired:
        return tokens.access_token
    return refresh_tokens(token_path, tokens).access_token
