# Roz company AWS cutover

Run this **after** the personal plumbing lab
([roz-aws-plumbing-lab.md](roz-aws-plumbing-lab.md)) and **after** firm AWS
access exists. Reuse the same **EC2 + Docker Compose** shape; swap in company
secrets, real data mounts, and babysitting reductions.

Do not start from ECS/Fargate or the CDK shadow stack until this cutover is
boringly reliable. The scaffold under [infra/aws/](../infra/aws/) remains a later
evolution (Phase C).

Related:

- [earnings-monitor-setup.md](earnings-monitor-setup.md) — local Compose patterns
- [earnings-monitor-access-validation.md](earnings-monitor-access-validation.md) — deploy gates
- [earnings-monitor-runbook.md](earnings-monitor-runbook.md) — day-2 operations
- Lab notes file from Phase A (instance size, memory, mount fixes)

```text
Lab lessons (sizing, mounts, compose commands)
        |
        v
Company EC2 + same Compose + Secrets Manager / approved secret store
        |
        v
Live smoke (one ticker) -> watchlist automation -> laptop-off proof
        |
        v
Phase C later: ECS/Fargate + EFS/S3 (optional)
```

---

## B0. Access gates (stop if any fail)

Complete before launching a company instance:

| Gate | Check |
|---|---|
| Account | `aws sts get-caller-identity` returns the **intended company** account/role |
| Spend | Named owner + monthly cap approved |
| Data | Written approval to store Anthropic / Snowflake / Quartr credentials and earnings artifacts in that account |
| Network | Outbound HTTPS allowed to required vendors (Anthropic, Snowflake, Quartr, SMTP as applicable) |
| Dashboard access | Start with **VPN and/or SSH tunnel only** (same as lab). Defer public ALB + Cognito until explicitly approved |
| Email | Mailpit in sandbox first; M365/SES only after IT approves ([earnings-monitor-setup.md](earnings-monitor-setup.md)) |
| Validation doc | Walk [earnings-monitor-access-validation.md](earnings-monitor-access-validation.md) for any items that apply to EC2+Compose (caller identity, secrets, email). Skip CDK/ECR/Cognito items until Phase C |

If personal-lab MFA/billing habits were useful, repeat them on the company login
path your firm requires (IAM Identity Center, etc.).

---

## B1. First company always-on (EC2 + Compose)

### B1.1 Size from lab notes

Use the instance type and disk size that worked in the plumbing lab (starting
point was `t3.large` / 40–60 GB). Do not downsize to free-tier micro for the
full stack.

Security group (company account):

- Inbound **22** from corporate VPN CIDR and/or your approved admin IP — not `0.0.0.0/0`
- No public inbound 8501/8025 unless security explicitly signs off (prefer tunnel/VPN)

### B1.2 Bootstrap (same as lab, firm clone + secrets)

1. Install Docker Engine + Compose on Ubuntu LTS.
2. Clone the firm-approved Git remote/branch; pin a known commit SHA.
3. Create real mount trees for:
   - `config/` (sectors, fiscal calendars, automation watchlist)
   - `Structured Narrative/config` (overlays)
   - `transcripts_raw`, `output`, inbox/events
4. Place secrets using a **firm-approved** method:
   - Prefer AWS Secrets Manager (or SSM) with task/host pull, **or**
   - Tightly permissioned on-box files (`chmod 600`), never OneDrive as runtime
5. Copy [services/earnings_monitor/.env.example](../services/earnings_monitor/.env.example)
   to on-box `.env.local` and set real monitor knobs. Do **not** use the
   plumbing-lab example as the production secret file — it is smoke-only.
6. Point Compose at real env files per setup docs:

```bash
export EARNINGS_MONITOR_ENV_FILE="services/earnings_monitor/.env.local"
export STRUCTURED_NARRATIVE_ENV_FILE="$PWD/Structured Narrative/.env"
export REPO_ENV_FILE="$PWD/.env"
export STRUCTURED_NARRATIVE_OUTPUT_DIR="$PWD/Structured Narrative/output"
export STRUCTURED_NARRATIVE_TRANSCRIPTS_DIR="$PWD/Structured Narrative/transcripts_raw"
```

### B1.3 Bring stack up

```bash
docker compose build
docker compose up -d monitor worker research-regen dashboard mailpit
docker compose ps
```

SMTP: keep `EARNINGS_MONITOR_SMTP_MODE=local` / Mailpit until M365 is approved,
then follow the Microsoft 365 block in
[earnings-monitor-setup.md](earnings-monitor-setup.md).

### B1.4 First smoke (narrow)

Before enabling the full automation watchlist:

1. Confirm dashboard via SSH tunnel or VPN path only.
2. Arm or onboard **one** non-critical ticker path and confirm monitor/worker
   progress in the Operations view.
3. Confirm research-regen can write under the mounted `output/` tree.
4. Fix mount/permission issues now — they get harder under live season load.

---

## B2. Reduce babysitting

Goal: you are not starting Compose every morning or watching logs all day.

| Habit | Action |
|---|---|
| Deploy script | One script or documented sequence: `git fetch` → checkout known SHA → `docker compose build` → `up -d` |
| Pin SHA | Record running `git rev-parse HEAD` on the host (file or tag) |
| Disk alarm | CloudWatch alarm when root (or data) filesystem > ~80% |
| Host recovery | EC2 auto-recovery / status-check alarm so a failed instance is visible |
| Restart policy | Rely on Compose `restart: unless-stopped` (already in compose file) |
| Runbook | Add company-specific restart/rollback notes to [earnings-monitor-runbook.md](earnings-monitor-runbook.md) when stable |
| Updates | Occasional deliberate deploys — not continuous ad-hoc edits on the box |

Example deploy skeleton (adapt paths; keep on the company host or in an internal ops doc):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/roz/Earnings-Call-Summarizer   # firm path
git fetch origin
git checkout "$1"   # pass commit SHA or tag
docker compose build
docker compose up -d monitor worker research-regen dashboard mailpit
git rev-parse HEAD | tee /opt/roz/RUNNING_SHA
docker compose ps
```

---

## B3. Live cutover checklist

Check off before calling company always-on “real”:

- [ ] `aws sts get-caller-identity` is the company sandbox/production account intended for Roz
- [ ] Secrets are not on a personal AWS account and not in Git
- [ ] Monitor + worker process a real armed event end-to-end
- [ ] research-regen writes Rank IC / consolidated (or book) artifacts to durable disk
- [ ] Dashboard reachable only via approved path (tunnel/VPN); not open to the world
- [ ] Ops health / failures visible (dashboard Operations and/or CloudWatch)
- [ ] Mail path validated (Mailpit in sandbox, or approved M365/SES)
- [ ] Laptop powered **off** during a test window; job still completes on EC2
- [ ] Deploy SHA recorded; rollback (`git checkout` previous SHA + compose up) rehearsed once
- [ ] Lab notes deltas applied (memory, disk, mount paths)

---

## Phase C — Later (structure only; not the first company deploy)

Only after Phase B is boring:

1. Translate Compose services to **ECS/Fargate**
2. Shared SQLite/state on **EFS**; large HTML/artifacts toward **S3**
3. Wire **Secrets Manager** into task definitions
4. Revisit [infra/aws/earnings_monitor_stack.py](../infra/aws/earnings_monitor_stack.py)
   (today: shadow poller / empty `discover_jobs` — not a drop-in for the live
   Quartr + SQLite loop)

Until then, company EC2 + Compose is the supported always-on path.

---

## Mapping lab → company

| Plumbing lab | Company cutover |
|---|---|
| Personal account | Company sandbox / prod account |
| Empty mounts + stub `.env` | Real config, transcripts, output, approved secrets |
| `.env.plumbing-lab.example` | `.env.example` → firm `.env.local` + secret store |
| Mailpit only | Mailpit then approved M365/SES |
| SSH from home IP | SSH/VPN from corporate controls |
| Learn reboot + sizing | Laptop-off proof + deploy script + alarms |
| Tear down when done | Persist with spend cap + runbook |
