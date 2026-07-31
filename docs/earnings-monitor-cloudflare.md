# Earnings monitor Cloudflare edge and artifact storage

Roz continues to run locally in Docker. Cloudflare Tunnel exposes the local
Streamlit service, Cloudflare Access protects the hostname, and R2 receives
immutable completed-event artifacts through its S3-compatible endpoint.
Cloudflare does not run scoring, SQLite, Snowflake, Anthropic, subprocesses, or
the workflow worker.

## What the repository implements

- The `cloudflared` Compose service is isolated behind the `cloudflare` profile.
  Normal `docker compose up -d` remains localhost-only and does not require a
  Tunnel token.
- The dashboard port remains bound to `127.0.0.1`, preserving local recovery
  access at <http://localhost:8501>. The Tunnel reaches `http://dashboard:8501`
  over the Compose network; it does not use the host port.
- The worker uses the existing `S3ArtifactStore` boundary with the R2 endpoint.
  A completed post-call workflow queues publication in SQLite. Content objects
  are uploaded under an event/fingerprint prefix, then `complete.json` is
  uploaded last as the completion marker.
- Publication failures use persisted exponential retries. They never change a
  successful workflow back to failed or rerun scoring. Identical retries are
  idempotent; conflicting bytes are rejected.
- Only the final transcript, completed ticker scoring outputs, deterministic
  workflow result, and completion manifest are published. These are snapshotted
  beneath the event fingerprint after post-call success. Live SQLite files,
  WAL/SHM files, live transcripts, credentials, and arbitrary working
  directories are not uploaded.
- SQLite records poll cycles, every job attempt, stage duration/result/error,
  and artifact publication status. The dashboard Operations view displays run
  timelines, stuck events, stale polling, repeated failures, and exhausted R2
  publications.

## External setup gates

These actions require the Cloudflare account owner and are intentionally not
performed by repository code:

1. Add or select a Cloudflare-managed domain.
2. In Zero Trust, create a remotely managed Tunnel and copy its token.
3. Add a public hostname whose service is `http://dashboard:8501`.
4. Create an Access application for that hostname and an allow policy for the
   intended users. Verify Access protection before sharing the hostname.
5. Create a private R2 bucket.
6. Create bucket-scoped R2 S3 API credentials with Object Read & Write access.
   Record the Access Key ID and Secret Access Key; do not use a general
   Cloudflare API token in the S3 credential fields.

The R2 endpoint is
`https://ACCOUNT_ID.r2.cloudflarestorage.com`. A custom endpoint can be supplied
for jurisdictional endpoints or tests.

## Local configuration

Copy `services/earnings_monitor/.env.example` to the untracked
`services/earnings_monitor/.env.local`, then set:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=...
EARNINGS_MONITOR_R2_ACCOUNT_ID=...
EARNINGS_MONITOR_R2_BUCKET=roz-artifacts
EARNINGS_MONITOR_R2_PREFIX=production/roz
EARNINGS_MONITOR_R2_ACCESS_KEY_ID=...
EARNINGS_MONITOR_R2_SECRET_ACCESS_KEY=...
```

`EARNINGS_MONITOR_R2_ENDPOINT_URL` is optional when the account ID is set.
Leaving every R2 field blank disables publishing. Supplying only some required
fields is a startup configuration error so an operator cannot assume artifacts
are protected when they are not.

Compose variable interpolation happens before service `env_file` loading. Set
the Tunnel token in the PowerShell environment when starting the profile:

```powershell
$env:EARNINGS_MONITOR_ENV_FILE="services/earnings_monitor/.env.local"
$env:CLOUDFLARE_TUNNEL_TOKEN="<tunnel-token>"
docker compose --profile cloudflare up -d
docker compose ps
docker compose logs cloudflared
```

Without the profile, `cloudflared` is not created and a missing token cannot
break the local stack:

```powershell
docker compose up -d
```

Do not start the `cloudflare` profile until a real token is configured. The
placeholder is deliberately invalid and cannot create a Tunnel or other
Cloudflare resource.

## Verification

1. Confirm <http://localhost:8501> still works.
2. Open the public hostname in a private browser and confirm Access challenges
   an unauthorized session.
3. Run a controlled completed event.
4. In the Operations view, confirm the artifact publication is `succeeded` and
   has a `manifest_uri`.
5. In R2, confirm the event prefix contains `workflow-result.json`, the final
   transcript, completed ticker output snapshots, and `complete.json`.
6. Temporarily use an invalid R2 endpoint in a non-production test and confirm
   the workflow remains complete while publication retries are visible.

## Recovery and rotation

- Tunnel incident: stop only the sidecar with
  `docker compose stop cloudflared`; use localhost for recovery.
- R2 incident: correct credentials/endpoint and restart the worker. Pending
  publications retain their retry state. Exhausted publications remain visible
  for operator investigation and are not silently discarded.
- Credential exposure: rotate the Tunnel token and R2 credentials in
  Cloudflare, update the untracked environment, and recreate the affected
  containers. Never paste credential values into logs, commits, or tickets.
- Access policy error: stop `cloudflared` immediately. Local processing and
  localhost dashboard access continue.
