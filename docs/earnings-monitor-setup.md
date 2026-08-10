# Earnings monitor setup

## Local Windows-first Roz runtime

Prerequisites: Docker Desktop with Compose v2 and at least 4 GB available to
Docker. The default Compose platform is `linux/amd64`, which works with Windows
Docker Desktop. On Apple Silicon, set `DOCKER_PLATFORM=linux/arm64`.

Copy `services/earnings_monitor/.env.example` to an untracked `.env.local`.
Point Compose at that monitor configuration, the existing Snowflake and
Anthropic credential files, and the canonical Structured Narrative output
directory. Set these variables again after opening a new PowerShell session:

```powershell
$env:EARNINGS_MONITOR_ENV_FILE="services/earnings_monitor/.env.local"
$env:STRUCTURED_NARRATIVE_ENV_FILE="$PWD\Structured Narrative\.env"
$env:REPO_ENV_FILE="$PWD\.env"
$env:STRUCTURED_NARRATIVE_OUTPUT_DIR="$PWD\Structured Narrative\output"
docker compose build
docker compose up -d
docker compose ps
```

Open the dashboard at <http://localhost:8501> and Mailpit at
<http://localhost:8025>. State is retained in the `monitor-data` and
`mailpit-data` named volumes. `docker compose down` preserves them;
`docker compose down --volumes` deletes local state.

Mailpit is the default notification transport (`mailpit:1025`, no STARTTLS).
Messages include both plain-text and HTML alternatives and can be validated
without external delivery. To use Microsoft 365, copy the example environment
to an untracked file and set:

```text
EARNINGS_MONITOR_SMTP_MODE=microsoft365
EARNINGS_MONITOR_SMTP_HOST=smtp.office365.com
EARNINGS_MONITOR_SMTP_PORT=587
EARNINGS_MONITOR_SMTP_STARTTLS=true
EARNINGS_MONITOR_SMTP_USERNAME=<tenant-approved-mailbox>
EARNINGS_MONITOR_SMTP_PASSWORD=<secret-or-app-password>
EARNINGS_MONITOR_SMTP_FROM=<tenant-approved-from-address>
EARNINGS_MONITOR_SMTP_TO=<comma-separated-recipients>
```

The Microsoft 365 tenant administrator must enable Authenticated SMTP for the
mailbox/tenant or provide an allowed equivalent credential flow. MFA,
Conditional Access, SMTP AUTH policy, sender permissions, mailbox licensing,
and recipient allow-listing are external setup gates. Keep credentials out of
Git. The `MailSender` boundary remains transport-neutral so a future Microsoft
Graph sender can replace SMTP without changing notification assembly.
Start Compose with `EARNINGS_MONITOR_ENV_FILE` pointing to that untracked file;
the Compose service does not override its SMTP values.

The one-shot `history-import` service first builds the pilot-four consolidated
Parquet dataset in the shared data volume. The monitor then runs the repository's
manual-event scheduler and the dashboard reads both that history and live SQLite
event state. The worker atomically claims and executes workflow jobs from the
shared SQLite queue.

Arm an event using confirmed Quartr watchlist times. Re-run the same command to
correct either time without resetting its processing state:

```powershell
docker compose run --rm monitor arm `
  --ticker MU `
  --period FY2026-Q4 `
  --report-at 2026-09-24T16:05:00-04:00 `
  --call-at 2026-09-24T17:00:00-04:00
```

## Onboard a new company (Quartr MCP default)

History transcripts are **not** pulled via Quartr REST or ROIC by default.
Seed lookback files with Cursor Quartr MCP into
`Structured Narrative/transcripts_raw/{TICKER}_FY….txt`, then run Onboard:

```powershell
# After MCP wrote STRW_FY….txt into transcripts_raw:
docker compose run --rm monitor onboard `
  --ticker STRW `
  --period FY2026-Q2 `
  --report-at 2026-08-06T16:00:00-04:00 `
  --isin US8631821019 `
  --skip-pull `
  --force-onboard
```

Defaults:

- Mode classification uses the on-disk MCP transcript count (no Quartr REST).
- Empty `transcripts_raw` fails with instructions to seed MCP (ROIC is not tried).
- Pass `--isin` for Snowflake/LSEG resolve so recycled `IBESTICKER` values cannot
  win (e.g. STRW). Overlay IDs are reused unless `--refresh-ids`.
- Fiscal calendar skips EDGAR when the ticker is already in
  `config/fiscal_calendars.yaml`.
- Onboard writes `Structured Narrative/config/company_overlays/{TICKER}.json`.
  `get_company` lazy-loads that file (overlay wins over hardcoded
  `COMPANIES` entries), so subprocess quant/LLM scoring does not need an
  in-process `register_overlay_profile` call. Hardcoding a ticker in
  `company_config.py` is optional convenience, not required for scoring.

Opt-in only when needed: `--use-quartr-rest`, `--allow-roic-fallback`,
`--estpermid` / `--barra-id`. `arm --onboard` accepts the same flags plus
`--skip-pull`.

Manual `arm` always wins over subsequent watched discovery for that event ID.
For the full automatic loop (watchlist → host calendar publish → watched
discover → concurrent live dispatch), see
[`earnings-monitor-auto-loop.md`](earnings-monitor-auto-loop.md) and
[`earnings-monitor-host-automation.md`](earnings-monitor-host-automation.md).

To enable automatic assisted arming, set `EARNINGS_MONITOR_PROVIDER=watched`
and point `EARNINGS_MONITOR_EVENT_MANIFESTS` at a mounted intake directory.
Compose uses
`earnings-scraper-main/earnings-scraper-main/inbox/events` on the host. The
monitor creates that subdirectory on startup. The Quartr-assisted watcher
publishes one `*.event.json` file per event by writing a temporary file in that
directory and renaming it only after the JSON is complete:

```json
{
  "schema_version": 1,
  "provider_event_id": "quartr-event-123",
  "ticker": "MU",
  "fiscal_period": "FY2026-Q4",
  "report_at": "2026-09-24T20:05:00Z",
  "call_at": "2026-09-24T21:00:00Z",
  "title": "Micron Technology FY2026 Q4 earnings call",
  "source_url": "https://quartr.com/example"
}
```

Republishing the same event is idempotent. A corrected manifest updates event
metadata and times without resetting lifecycle state or transcript progress.
Malformed files are logged and ignored; the last valid file by modification
time wins when duplicate manifests carry the same provider event ID.

The watcher may continue to publish legacy `.txt` transcripts with company and
period headers (or a name such as `MU-FY2026-Q4.txt`). The preferred handoff is
an atomically renamed `*.transcript.json` bundle:

```json
{
  "schema_version": 1,
  "provider_event_id": "quartr-event-123",
  "provider_document_id": "quartr-document-456",
  "ticker": "MU",
  "fiscal_period": "FY2026-Q4",
  "source_url": "https://quartr.com/example/transcript",
  "status": "final",
  "observed_at": "2026-09-24T22:15:00Z",
  "speaker_text": [
    {"speaker": "Operator", "text": "Good afternoon and welcome."},
    {"speaker": "Management", "text": "Thank you for joining us."}
  ]
}
```

`status` is `live` or `final`. Scoring policy for live vs final:

- After stagnation (and, by default, at least one live content growth —
  `EARNINGS_MONITOR_REQUIRE_LIVE_GROWTH`), the monitor may enqueue **one**
  LIVE `post_call`. Further live growth updates the fingerprint for the
  dashboard but does **not** enqueue another score.
- When the inbox bundle becomes `final`, a new fingerprint may enqueue
  another `post_call` (final re-score). Operators can also force a re-score
  via the Structured Narrative `--force` path.
- Final bundles are written atomically to
  `Structured Narrative/transcripts_raw/{TICKER}_{FISCAL_PERIOD}.txt`.
  Duplicate delivery and restarts reuse the persisted fingerprint and SQLite
  idempotency keys.

### Quartr live sweep (MCP → inbox)

Keep Quartr access outside the Docker scoring path. Dump MCP
`read_transcript` JSON (or refresh the dump in a loop), then write an atomic
inbox bundle:

```bash
python -m services.earnings_monitor.quartr_sweep \
  --event-id 692045 --ticker STRW --period FY2026-Q2 \
  --inbox earnings-scraper-main/earnings-scraper-main/inbox \
  --from-json path/to/mcp_read_transcript.json

# Poll until isLive is false (re-read the same dump path each tick), then finalize:
python -m services.earnings_monitor.quartr_sweep \
  --event-id 692045 --ticker STRW --period FY2026-Q2 \
  --inbox earnings-scraper-main/earnings-scraper-main/inbox \
  --from-json path/to/mcp_read_transcript.json \
  --loop --interval-seconds 30
```

`JsonDumpGateway` / `CallableGateway` implement the sweep `QuartrGateway`;
`RestQuartrGateway` is a stub for a later REST client. The monitor continues
to use `LocalInboxProvider` only.

## Optional Cloudflare edge and R2

The default stack remains localhost-only. An opt-in `cloudflare` Compose profile
adds a Tunnel sidecar, while the worker can publish immutable completed-event
artifacts to R2 through the existing S3-compatible storage boundary. The
dashboard remains available on `127.0.0.1` for recovery.

Repository configuration, exact environment variables, verification, and the
external domain/Tunnel/Access/R2 credential gates are documented in
[`earnings-monitor-cloudflare.md`](earnings-monitor-cloudflare.md). Cloudflare
is not an execution target: Python scoring, SQLite, Snowflake, Anthropic, and
subprocess workflows remain in the local containers.

Roz begins
quant freshness checks no earlier than the release and 90 minutes before the
call, begins transcript checks 45 minutes after call start, and times out the
transcript stage three hours after call start.

## AWS deployment

Prerequisites:

- AWS CLI credentials for a dedicated deployment role.
- Node.js/npm (for the CDK CLI), Python 3.12, Docker Buildx.
- A bootstrapped CDK environment: `npx aws-cdk bootstrap aws://ACCOUNT/REGION`.
- An ECR repository and a multi-architecture image built with
  `deploy/aws/build-and-push.ps1`.
- ACM certificate in the deployment region and DNS control for HTTPS.
- Cognito user pool, app client with a client secret, and user-pool domain.
- Existing Secrets Manager secret containing application/API credentials.
- Verified SES identity; production access if recipients are not verified.

No AWS credentials are required for unit tests or synthesis:

```powershell
cd infra/aws
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/pytest
npx aws-cdk synth -c container_image=example.invalid/earnings-monitor:synth
```

Deploy only after supplying real, non-secret identifiers as CDK context:

```powershell
npx aws-cdk deploy `
  -c container_image=ACCOUNT.dkr.ecr.REGION.amazonaws.com/earnings-monitor:TAG `
  -c certificate_arn=arn:aws:acm:REGION:ACCOUNT:certificate/ID `
  -c cognito_user_pool_arn=arn:aws:cognito-idp:REGION:ACCOUNT:userpool/POOL `
  -c cognito_user_pool_client_id=CLIENT_ID `
  -c cognito_user_pool_domain=DOMAIN `
  -c app_secret_arn=arn:aws:secretsmanager:REGION:ACCOUNT:secret:NAME `
  -c ses_identity_arn=arn:aws:ses:REGION:ACCOUNT:identity/example.com
```

Do not put secret values in context, source files, task definitions, or Compose
files. The stack accepts only a Secrets Manager ARN and grants runtime read
access. Configure an alarm notification target separately (SNS/PagerDuty) after
deployment.
