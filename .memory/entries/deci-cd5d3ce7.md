---
id: deci-cd5d3ce7
type: decision
project: earnings-call-summarizer
parent_id: plan-c35843a9
title: Quartr MCP OAuth refresh token closes the acquisition loop
node_label: Quartr MCP OAuth refresh token closes the acquisit
tags: quartr,oauth,monitor,phase2,automation
status: active
open_threads: 1
success: 'null'
files: services/earnings_monitor/quartr_oauth.py,services/earnings_monitor/quartr_mcp.py,services/earnings_monitor/host_automation.py,services/earnings_monitor/calendar_publish.py,services/earnings_monitor/automation_watchlist.py
session_id: sess-c2464faf
created_at: '2026-09-02T16:05:26.307290+00:00'
updated_at: '2026-09-02T19:52:34.688110+00:00'
related_to: ''
invalidated_by: ''
invalidates: ''
---
Phase 2 needs something to publish event manifests into inbox/events. Two routes are dead ends.

Quartr REST (QuartrApiClient, already used by onboard.py) needs QUARTR_API_KEY, which we do not have. Ruled out.

A Cursor Automation is blocked structurally: Automations only bind MCP servers registered via the cursor.com dashboard (serverIdentifier prefixed dashboard-, dashboard-team-, plugin-). Quartr is a project .cursor/mcp.json entry and this machine has no ~/.cursor/mcps catalog. Prefilling an ineligible server blocks save, and it would only run while Cursor is open.

Chosen: JSON-RPC straight to https://mcp.quartr.com/mcp. Its RFC 8414 metadata gives grant_types_supported=[authorization_code, refresh_token], token_endpoint_auth_methods_supported=[none], plus dynamic registration. No client_credentials grant, so no secret-only minting -- but refresh_token means one browser sign-in, then every later run mints its own access token. Headless, no API key, no editor.

quartr_oauth.py: RFC 7591 registration + PKCE over a loopback redirect, persisted to host_quartr/.quartr_oauth.json (gitignored; the refresh token is a live credential with no other copy), refreshed with a 120s skew so it cannot die mid-sweep.

quartr_mcp.py: streamable-HTTP client whose QuartrMcpGateway satisfies the same list_events(*, ticker) contract as the JSON-dump gateways, so publish_calendar cannot tell the difference and stays covered by existing tests. The events tool is discovered from a live tools/list, scored to avoid event-detail and transcript tools (they take an event id, not a ticker), overridable via QUARTR_MCP_EVENTS_TOOL.

'calendar --source mcp' writes dumps to disk then publishes from disk, keeping the audited file path as the only publish path.

Outstanding: the one-time sign-in has not happened, so the resolved tool name is unverified against the live server.
