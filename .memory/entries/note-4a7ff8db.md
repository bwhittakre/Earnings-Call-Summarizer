---
id: note-4a7ff8db
type: note
project: earnings-call-summarizer
parent_id: plan-c35843a9
title: 'Laptop Task Scheduler sweep is TEMPORARY: the scanning module moves to AWS'
node_label: 'Laptop Task Scheduler sweep is TEMPORARY: the scan'
tags: monitor,automation,aws,temporary,scheduler
status: active
open_threads: 1
success: 'null'
files: ''
session_id: sess-3dc76492
created_at: '2026-09-02T18:10:35.600473+00:00'
updated_at: '2026-09-02T18:16:33.979114+00:00'
---
User decision, recorded so a future agent does not treat the Windows Task Scheduler job as the intended end state.

The daily Quartr calendar sweep runs on the laptop via Task Scheduler (6:00am daily, catch-up enabled). This is explicitly a STOPGAP. Once AWS is active and the stack runs 24/7, the scanning module moves there and the scheduled task should be REMOVED rather than left running in parallel -- two schedulers publishing manifests into the same inbox would race on the same (ticker, fiscal_period) filenames.

Why the laptop and not Docker, since the instinct was Docker: Docker Desktop on this machine runs as a DESKTOP APP, not a service (com.docker.service is Stopped/Manual while five Docker Desktop processes run in the user session). Container uptime is therefore capped by the user being logged in -- a sidecar gives no true 24/7 here. Containers do survive sleep (roz-research-regen-1 and roz-mailpit-1 showed 'Up 2 weeks' across three logged sleep/resume cycles); it is logout and shutdown that stop them.

Task Scheduler also beats a container loop on the two properties that actually matter for this job: it can run whether or not the user is logged on, and StartWhenAvailable reruns a MISSED window on next boot instead of idling until the next interval. And it keeps the Quartr OAuth token on the host instead of passing a credential into a container.

The cost of a missed day is low by design: published manifests persist on disk and the monitor keeps arming from them on a 30-day lookahead. Re-running the sweep is what catches a MOVED date, not what keeps Roz working. Real 24/7 only comes from an always-on machine, which is the AWS plan.
