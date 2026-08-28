---
id: annotation-desk-queue-host-refresh
type: annotation
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: Desk hook is live via bind-mount; image bake still hash-blocked
tags: annotation,desk,claims,roz,worker,august-2026
created_at: 2026-08-28T14:10:00+00:00
updated_at: 2026-08-28T14:40:00+00:00
---
`docker compose build monitor worker` failed on a pip hash mismatch
(expected `97b3e89…`, got `c1fffd…`) that is not in repo requirements.
Until a clean bake lands, `docker-compose.yml` bind-mounts `./services`
and `./scripts` onto monitor-common and worker.

Force-recreated `roz-monitor-1` / `roz-worker-1` on 28 Aug 2026.
In-container smoke test (`walk_after_novelty_view` for NVDA FY2027-Q2
only, no gold rescore):

- `status=walked`, `changed=False`, `n_trees=33`
- cue queue written, `n_missed=0`, gold recall `1.0`
- proposals written, `n_proposals=0`, gate allowed

Host fallback if mounts disappear: `python scripts/_desk_cue_queue.py`.
Does not auto-seed. Does not call an LLM.
