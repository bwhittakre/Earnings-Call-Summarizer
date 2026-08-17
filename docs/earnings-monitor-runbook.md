# Earnings monitor runbook

## Operating model

Roz V1 is Windows-first. Onboarded tickers can auto-arm via host
`calendar_publish` + `EARNINGS_MONITOR_PROVIDER=watched` (see
[`earnings-monitor-auto-loop.md`](earnings-monitor-auto-loop.md)); manual `arm`
remains available and wins on override. The monitor advances event gates
and enqueues idempotent jobs in SQLite; the worker claims those jobs and runs
the existing Structured Narrative profiles. The Cursor Quartr watcher writes
transcripts into the mounted inbox. Snowflake freshness uses the same
Structured Narrative credentials and source tables as the existing model.
Partial state appears in the dashboard immediately; the final notification is
sent only after post-call processing succeeds or the transcript reaches its
three-hour timeout.

Each monitor pass is recorded in SQLite `poll_cycles`; each claimed job attempt
is recorded in `job_runs` with stage, duration, result summary, and error.
Use the dashboard Operations view for the event timeline, stuck-event
classification, stale poller signal, repeated failures, and R2 publication
status. The default thresholds are controlled by
`EARNINGS_MONITOR_STUCK_EVENT_SECONDS` and
`EARNINGS_MONITOR_REPEATED_FAILURE_THRESHOLD`.

Notifications are multipart plain text + HTML. The quant-ready message reports
available measures, point-in-time z-scores, freshness/as-of detail, and the
dashboard link. The final message reads the consolidated company-quarter
dataset and Structured Narrative registry/artifacts to report dimension
narrative level/change, quant gaps and divergences, evidence, completeness, and
dashboard/artifact links. Missing fields are rendered as `n/a` and explicit
completion issues rather than preventing delivery.

SQLite notification keys suppress repeated cycle alerts and duplicate milestone
messages. A terminal/stall failure is sent once per event; a later successful
completion uses a distinct `recovery-success` key and is also sent exactly once.
Stuck-event, repeated-failure, stale-poller, and failed-publication signals use
stable operational keys so monitor and worker loops do not send per-cycle noise.
After correcting an incident, preserve the notification and job history.

Local Compose uses Mailpit. For Microsoft 365 SMTP use
`smtp.office365.com:587` with STARTTLS and an untracked environment file
containing the tenant-approved username/password/from/to settings. Run
`python -m services.earnings_monitor diagnose` before arming a live event.
Mailbox licensing, SMTP AUTH enablement, MFA/Conditional Access compatibility,
send-as permissions, and tenant recipient policies remain owner setup gates;
the monitor does not create or alter Microsoft 365 resources.

Optional Cloudflare Tunnel and R2 operation is documented in
[`earnings-monitor-cloudflare.md`](earnings-monitor-cloudflare.md). A Tunnel or
Access incident should be isolated by stopping `cloudflared`; do not stop the
monitor or worker unless local processing itself is unsafe. An R2 failure does
not roll back a successful workflow: inspect the artifact publication row,
correct endpoint/credentials, and restart the worker so persisted retries can
continue.

The AWS section below describes the retained deployment scaffold, not the active
Roz V1 runtime.

EventBridge invokes the dispatcher, which asynchronously invokes the poller.
The poller records a DynamoDB audit row and eventually publishes work to
SQS. Fargate workers consume SQS; failed jobs move to the DLQ after three
receives. The Streamlit service is behind an ALB. S3 stores durable artifacts,
while CloudWatch retains service logs and alarms on poller errors, stopped
workers, and DLQ depth.

The initial infrastructure sets `SHADOW_MODE=true`. The poller discovers zero
jobs by design and the worker does not delete messages until application
processing is wired.

## First-Print vs Onboard

Use the mode router mentally (or `services.earnings_monitor.mode_router`) before
arming a new ticker/period:

| Mode | When | Command |
|------|------|---------|
| **First-Print** | Zero prior Quartr/ROIC earnings events and no on-disk transcripts | `arm --first-print` |
| **Onboard** | Prior history exists (or local transcripts) but the ticker is not fully wired | `onboard` or `arm --onboard` |
| **Standard** | Already in `CompanyProfile` with scored history | `arm` (default) |

### First-Print (SPCX postmortem)

SpaceX (`SPCX`) FY2026-Q2 was a first public print: empty `prior_quarters`, no
delta baseline. Arming without `--first-print` queued a prior-quarter baseline
that could not succeed. Fix:

```bash
python -m services.earnings_monitor arm \
  --ticker SPCX --period FY2026-Q2 \
  --report-at 2026-08-04T20:00:00+00:00 \
  --call-at 2026-08-04T21:00:00+00:00 \
  --first-print
```

First-Print skips pre_release baseline and post-call delta/surprise/novelty
comparisons that require a prior transcript.

### Onboard

Lookback is **10y** when `report_at - now >= 48h`, else **3y**. The 3y path
reuses ROIC `fetch_transcripts` + `export_inbox_to_transcripts_raw`; the 10y
path uses `Structured Narrative/quartr_history_import.py` (needs
`QUARTR_API_KEY`). Onboard then scaffolds `prior_quarters` /
`output_quarters`, resolves `estpermid` (hard-fail if missing), bootstraps
fiscal calendar into `config/fiscal_calendars.yaml` when needed, runs quant +
batch LLM + `build_feature_panel --from-registry`, and prints the
`history_import` handoff. If batch work is incomplete at `report_at`, the
event stays `onboarding_blocked` with a clear error — never a silent baseline
fail.

```bash
# Plan only
python -m services.earnings_monitor onboard \
  --ticker NEWCO --period FY2026-Q2 \
  --report-at 2026-09-01T20:00:00+00:00 --dry-run

# Full onboard + arm (ticker must be on EARNINGS_MONITOR_TICKERS)
python -m services.earnings_monitor arm \
  --ticker NEWCO --period FY2026-Q2 \
  --report-at 2026-09-01T20:00:00+00:00 \
  --call-at 2026-09-01T21:00:00+00:00 \
  --onboard
```

### Fiscal calendar

EDGAR fiscal-profile bootstrap (`src/ingest/edgar/fiscal_profile.py`) feeds
`config/fiscal_calendars.yaml`. Most XLK names need no entry (calendar or
existing offset logic). Onboard writes an entry only when the ticker is absent.

## Shadow-live procedure

1. Complete every item in `earnings-monitor-access-validation.md`.
2. Deploy to a non-production account with HTTPS and Cognito configured.
3. Keep `SHADOW_MODE=true`; use a verified internal SES recipient only.
4. Run for at least two expected schedule windows. Confirm one poll audit row
   per cycle, no Lambda errors, stable ECS tasks, empty DLQ, and no outbound
   customer email.
5. Wire the real discovery/processing entry points and test with a fixed,
   allow-listed ticker set. Compare discovered events and generated output
   against the existing manual process; record false positives and misses.
6. Publish test jobs to SQS. Verify idempotency, retries, visibility timeout,
   artifact writes, and that an intentionally failing job reaches the DLQ.
7. Validate SES content through the internal allow-list and confirm
   bounce/complaint handling.
8. Obtain owner sign-off. Change shadow mode through an reviewed deployment,
   never by editing a running task. Expand the ticker and recipient allow-lists
   gradually.

## Routine checks

- ECS worker/dashboard desired and running counts match.
- EventBridge schedule and both Lambda functions are enabled.
- SQS age/depth trends are bounded; DLQ is empty.
- Poller errors and application log error rates are zero.
- DynamoDB and S3 have current records; SES sends/bounces remain expected.

## Incidents

**Backlog:** keep the schedule enabled if discovery is safe, scale workers, and
inspect the oldest job. Do not reduce visibility timeout below worst-case
processing time.

**DLQ messages:** disable or retain shadow mode, inspect without deleting,
correct the root cause, then redrive a small sample. Confirm idempotency first.

**Bad alerts/output:** stop outbound sending, preserve artifacts/logs, set
shadow mode, and compare the affected event with source evidence.

**Stuck local event:** use the Operations timeline to identify the last
successful stage and its duration. Check the event's `last_error`, worker logs,
and whether the current job is pending/running before changing state.

**Repeated workflow failure:** preserve the `job_runs` history and source
transcript, correct the root cause, then allow the existing bounded SQLite retry
to proceed. Do not delete the idempotency key or manually rerun scoring merely
to clear the alert.

**R2 publication failure:** confirm the event workflow is still complete, then
check endpoint, bucket-scoped credentials, and network access. Content uploads
are immutable and the completion manifest is written last, so retrying a
partial publication is safe. Never upload `monitor.sqlite3`, its WAL/SHM files,
or any other live state as an artifact.

**Credential exposure:** disable affected tasks/Lambdas, rotate the secret at
the provider and Secrets Manager, review CloudTrail, then redeploy. Never paste
secret values into tickets or logs.

**Rollback:** deploy the prior immutable image tag with CDK. Retained S3 and
DynamoDB resources survive stack updates/deletion; verify schema compatibility
before rollback.

## Known deployment gates

AWS deployment, DNS, ACM, Cognito, Secrets Manager values, SES production
approval, alarm notification routing, and third-party data access all require
account-owner action. The AWS Lambda/SQS path remains a scaffold. The local Roz
scheduler and SQLite worker are implemented independently and must not be
described as validating that cloud path.
