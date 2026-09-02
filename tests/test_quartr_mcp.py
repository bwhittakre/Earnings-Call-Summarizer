from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from services.earnings_monitor.quartr_mcp import (
    QuartrMcpError,
    QuartrMcpGateway,
    _parse_body,
    _rows_from_payload,
    _unwrap_tool_result,
    resolve_events_tool,
)
from services.earnings_monitor.quartr_oauth import (
    QuartrAuthError,
    TokenSet,
    _tokens_from_payload,
    load_tokens,
    save_tokens,
)


class TestEventsToolResolution:
    def test_prefers_exact_known_name(self):
        tools = [{"name": "get_transcript"}, {"name": "list_events"}]
        assert resolve_events_tool(tools) == "list_events"

    def test_rejects_event_detail_and_transcript_lookalikes(self):
        """Substring matching would pick these; they take an id, not a ticker."""
        tools = [
            {"name": "get_event_transcript"},
            {"name": "get_event_by_id"},
            {"name": "list_upcoming_events"},
        ]
        assert resolve_events_tool(tools) == "list_upcoming_events"

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("QUARTR_MCP_EVENTS_TOOL", "custom_tool")
        assert resolve_events_tool([{"name": "list_events"}]) == "custom_tool"

    def test_no_candidate_raises_with_the_available_names(self):
        with pytest.raises(QuartrMcpError) as excinfo:
            resolve_events_tool([{"name": "get_financials"}])
        assert "get_financials" in str(excinfo.value)

    def test_empty_tool_list_raises(self):
        with pytest.raises(QuartrMcpError):
            resolve_events_tool([])


class TestPayloadNormalization:
    @pytest.mark.parametrize(
        "payload",
        [
            [{"id": 1}],
            {"events": [{"id": 1}]},
            {"data": [{"id": 1}]},
            {"results": [{"id": 1}]},
            {"items": [{"id": 1}]},
        ],
    )
    def test_list_shapes(self, payload):
        assert _rows_from_payload(payload) == [{"id": 1}]

    def test_single_event_object(self):
        assert _rows_from_payload({"id": 7, "eventType": "q_2"})[0]["id"] == 7

    def test_unrecognized_shape_is_empty_not_an_error(self):
        assert _rows_from_payload({"message": "no data"}) == []


class TestResponseParsing:
    def test_plain_json(self):
        assert _parse_body("application/json", '{"result": {"ok": 1}}')["result"] == {
            "ok": 1
        }

    def test_sse_stream(self):
        raw = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":2}}\n\n'
        assert _parse_body("text/event-stream", raw)["result"] == {"ok": 2}

    def test_sse_without_payload_raises(self):
        with pytest.raises(QuartrMcpError):
            _parse_body("text/event-stream", "event: ping\n\n")

    def test_structured_content_preferred_over_text(self):
        result = {
            "structuredContent": {"events": [{"id": 3}]},
            "content": [{"type": "text", "text": "ignored"}],
        }
        assert _unwrap_tool_result(result) == {"events": [{"id": 3}]}

    def test_text_content_json_is_decoded(self):
        result = {"content": [{"type": "text", "text": '[{"id": 4}]'}]}
        assert _unwrap_tool_result(result) == [{"id": 4}]

    def test_tool_error_raises(self):
        with pytest.raises(QuartrMcpError):
            _unwrap_tool_result({"isError": True, "content": []})


class _StubClient:
    """Mimics the real tool contract: search_companies then list_events."""

    def __init__(self, events=None, matches=None, raises_on=None):
        self.events = events if events is not None else []
        self.matches = (
            matches
            if matches is not None
            else {"matches": [{"id": 4541, "ticker": "ADSK", "name": "Autodesk"}]}
        )
        self.raises_on = raises_on
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self):
        return [{"name": "list_events"}, {"name": "search_companies"}]

    def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if self.raises_on == name:
            raise QuartrMcpError("boom")
        return self.matches if name == "search_companies" else self.events

    def args_for(self, name):
        return next(a for n, a in self.calls if n == name)


class TestCompanyIdResolution:
    def test_requires_an_exact_ticker_match(self):
        """Quartr search is fuzzy; arming the wrong company is worse than none."""
        from services.earnings_monitor.quartr_mcp import resolve_company_id

        payload = {
            "matches": [
                {"id": 1, "ticker": "ADS", "name": "Adient"},
                {"id": 4541, "ticker": "ADSK", "name": "Autodesk"},
            ]
        }
        assert resolve_company_id(payload, "ADSK") == 4541

    def test_no_exact_match_is_none_not_a_guess(self):
        from services.earnings_monitor.quartr_mcp import resolve_company_id

        payload = {"matches": [{"id": 1, "ticker": "ADS", "name": "Adient"}]}
        assert resolve_company_id(payload, "ADSK") is None

    def test_lookup_is_cached_across_calls(self):
        client = _StubClient(events=[{"id": 1}])
        gateway = QuartrMcpGateway(client)
        gateway.list_events(ticker="ADSK")
        gateway.list_events(ticker="ADSK")
        searches = [n for n, _ in client.calls if n == "search_companies"]
        assert len(searches) == 1


class TestGateway:
    def test_sends_company_id_and_the_required_expand(self):
        """list_events takes companyId, not ticker, and expand is mandatory."""
        client = _StubClient(events=[{"id": 1}])
        rows = QuartrMcpGateway(client).list_events(ticker="adsk")
        args = client.args_for("list_events")
        assert args["companyId"] == 4541
        # contentDates carries the call/report times the manifest needs.
        assert "contentDates" in args["expand"]
        assert "ticker" not in args
        assert rows[0]["ticker"] == "ADSK"

    def test_window_reaches_past_one_quarter(self):
        """Next-quarter scheduling needs to see ~90 days out, not 30."""
        client = _StubClient(events=[{"id": 1}])
        QuartrMcpGateway(client).list_events(ticker="ADSK")
        args = client.args_for("list_events")
        assert args["startDate"] < args["endDate"]
        assert QuartrMcpGateway.DEFAULT_LOOKAHEAD_DAYS >= 120

    def test_one_bad_ticker_does_not_abort_the_sweep(self):
        client = _StubClient(raises_on="list_events")
        assert QuartrMcpGateway(client).list_events(ticker="ADSK") == ()

    def test_unresolvable_company_is_skipped_without_calling_list_events(self):
        client = _StubClient(matches={"matches": []})
        assert QuartrMcpGateway(client).list_events(ticker="ADSK") == ()
        assert not any(n == "list_events" for n, _ in client.calls)

    def test_existing_ticker_field_is_not_overwritten(self):
        client = _StubClient(events=[{"id": 1, "ticker": "MSFT"}])
        rows = QuartrMcpGateway(client).list_events(ticker="ADSK")
        assert rows[0]["ticker"] == "MSFT"


class TestTokenStore:
    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "tok.json"
        save_tokens(path, TokenSet("a", "r", "cid", time.time() + 900))
        loaded = load_tokens(path)
        assert (loaded.access_token, loaded.refresh_token, loaded.client_id) == (
            "a",
            "r",
            "cid",
        )
        assert not loaded.expired

    def test_missing_file_is_empty_not_an_error(self, tmp_path: Path):
        assert load_tokens(tmp_path / "nope.json").refresh_token == ""

    def test_corrupt_file_raises(self, tmp_path: Path):
        path = tmp_path / "tok.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(QuartrAuthError):
            load_tokens(path)

    def test_expiry_uses_a_skew_so_a_token_cannot_die_mid_sweep(self):
        assert TokenSet("a", "r", "c", time.time() + 30).expired
        assert not TokenSet("a", "r", "c", time.time() + 3600).expired

    def test_refresh_token_is_kept_when_the_server_does_not_rotate_it(self):
        previous = TokenSet("old", "keep-me", "cid", 0.0)
        refreshed = _tokens_from_payload(
            {"access_token": "new", "expires_in": 3600},
            client_id="cid",
            previous=previous,
        )
        assert refreshed.refresh_token == "keep-me"
        assert refreshed.access_token == "new"

    def test_rotated_refresh_token_replaces_the_old_one(self):
        refreshed = _tokens_from_payload(
            {"access_token": "new", "refresh_token": "rotated", "expires_in": 60},
            client_id="cid",
            previous=TokenSet("old", "stale", "cid", 0.0),
        )
        assert refreshed.refresh_token == "rotated"

    def test_missing_access_token_raises(self):
        with pytest.raises(QuartrAuthError):
            _tokens_from_payload({"expires_in": 60}, client_id="cid")

    def test_token_path_honors_the_env_override(self, tmp_path: Path, monkeypatch):
        from services.earnings_monitor.quartr_oauth import default_token_path

        monkeypatch.setenv("QUARTR_OAUTH_TOKEN_PATH", str(tmp_path / "x.json"))
        assert default_token_path(Path("/anything")) == tmp_path / "x.json"


def test_token_file_is_not_committable(tmp_path: Path):
    """The refresh token is a live credential; gitignore must cover its dir."""
    repo = Path(__file__).resolve().parents[1]
    ignored = (repo / ".gitignore").read_text(encoding="utf-8", errors="replace")
    assert "/host_quartr/" in ignored


class TestRateLimitBackoff:
    def test_prefers_the_servers_retry_after_header(self):
        from services.earnings_monitor.quartr_mcp import _retry_after_seconds

        assert _retry_after_seconds({"Retry-After": "13"}, "", 0) == 14.0

    def test_falls_back_to_the_retry_after_in_the_json_body(self):
        """Quartr reports the wait in the body as well as the header."""
        from services.earnings_monitor.quartr_mcp import _retry_after_seconds

        body = '{"error":"Too many requests","retryAfter":"13"}'
        assert _retry_after_seconds({}, body, 0) == 14.0

    def test_backs_off_exponentially_with_no_hint(self):
        from services.earnings_monitor.quartr_mcp import _retry_after_seconds

        delays = [_retry_after_seconds({}, "", n) for n in range(4)]
        assert delays == sorted(delays) and delays[0] < delays[-1]

    def test_delay_is_capped(self):
        from services.earnings_monitor.quartr_mcp import (
            MAX_RETRY_DELAY,
            _retry_after_seconds,
        )

        assert _retry_after_seconds({"Retry-After": "99999"}, "", 0) == MAX_RETRY_DELAY
        assert _retry_after_seconds({}, "", 40) == MAX_RETRY_DELAY

    def test_garbage_retry_after_does_not_raise(self):
        from services.earnings_monitor.quartr_mcp import _retry_after_seconds

        assert _retry_after_seconds({"Retry-After": "soon"}, "", 1) > 0
