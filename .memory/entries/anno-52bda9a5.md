---
id: anno-52bda9a5
type: annotation
project: earnings-call-summarizer
parent_id: deci-77219c82
title: Coordinator MCP tools return Unknown tool — spawning agents directly
node_label: Coordinator MCP tools return Unknown tool — spawni
tags: ''
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-36ccf53c
created_at: '2026-09-03T15:01:45.063275+00:00'
updated_at: '2026-09-03T15:01:45.063275+00:00'
---
All plugin-angelo-coordinator tools (agents, create_graph, get_ready_tasks, claim_task, submit_result, get_report) return 'Unknown tool' despite the namespace appearing ready in GetDynamicTools and angelo doctor reporting coordinator as OK. mcp_auth call succeeded but did not fix dispatch. Memory MCP is healthy.

Workaround: spawning Wave 1–5 subagents directly via the Task tool. Writing progress to memory tree instead of coordinator ledger. No fix cycles (no coordinator = no extend_graph), so moving straight to implementation.
