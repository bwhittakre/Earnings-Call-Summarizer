---
id: anno-ba5059aa
type: annotation
project: earnings-call-summarizer
parent_id: deci-9203674d
title: 'Deleting an instrumented module does NOT stop a running container: sys.modules
  caches it'
node_label: Deleting an instrumented module does NOT stop a ru
tags: docker,python,instrumentation,gotcha,bind-mount
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-3dc76492
created_at: '2026-09-02T18:41:54.999098+00:00'
updated_at: '2026-09-02T18:41:54.999098+00:00'
---
Found while auditing that no debug instrumentation remained. Source was clean; the RUNTIME was not.

services/earnings_monitor/_debug_probe.py was deleted from the host, and /app/services is a bind mount so the file vanished from roz-monitor-1 immediately. Expected an ImportError, since the probe import sits INSIDE discover() and therefore runs every cycle. Got none -- and the monitor kept logging healthy cycles.

The reason is that Python caches imported modules in sys.modules. The module was imported on the first discover cycle hours earlier; every later 'from ._debug_probe import probe' resolves from that cache and never touches the filesystem. So the process happily kept running the OLD instrumented code with no error and no way to tell from the source tree.

Proof it was still live: /app/scripts/debug-ccf4b6.log was RECREATED at 48,000 bytes minutes after I deleted it. After 'docker restart', the same check returned 'No such file or directory' across several cycles.

RULE: stripping instrumentation from source is not done until the processes that imported it are restarted. Verify by deleting the log file and confirming it does NOT reappear -- not by grepping the source, which will look clean either way.

Related finds in the same audit:
- A stale __pycache__/_debug_probe.cpython-312.pyc survived the source deletion. Harmless for imports (PEP 3147: a cached pyc is only used when the .py exists) but removed anyway.
- Containers drift badly. roz-worker-1 was 5 days old and roz-dashboard-1 27 hours, both bind-mounting /app/services, so neither had ANY of the Phase 1-3 work. Restarted all three that mount services. roz-research-regen-1 does not mount services and was left alone.
- Two COMPLETE sets of Angelo MCP servers are running (2x memory, coordinator, zettelkasten, artifacts, synapse), one per open Cursor workspace -- the worktree and the main repo. This is the mechanical cause of the memory read/write inconsistency seen earlier in this workstream: two memory servers bound to two different .memory/ directories.
- Verification gotcha: 'docker exec C sh -lc "grep -c \"a b c\" f"' loses the inner quotes through PowerShell and reports 0 matches, which read as a MISSING fix. Use 'docker exec C grep -n pattern file' directly.
