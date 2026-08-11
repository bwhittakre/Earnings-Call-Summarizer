# Roz AWS plumbing lab (personal account)

**New to AWS?** Start with the beginner path only:
[roz-aws-start-here.md](roz-aws-start-here.md) (session-by-session clicks).
Come back to this page for the fuller reference after Session 6+.

Personal AWS **EC2 + Docker Compose** lab to learn always-on ops **without**
company data. When the lab is done, capture lessons and follow
[roz-aws-company-cutover.md](roz-aws-company-cutover.md) on firm AWS.

This is not a live earnings environment. Do not onboard real tickers, run Quartr
sweeps against firm watchlists, regenerate the production Rank IC book, query
Snowflake, or send real email from this box.

Related: [earnings-monitor-setup.md](earnings-monitor-setup.md) (local Windows),
[earnings-monitor-access-validation.md](earnings-monitor-access-validation.md)
(company deploy gates).

## Hard rules — forbidden on the personal box

Do **not** copy or create any of the following on the personal EC2 instance:

- `Structured Narrative/.env`, repo-root `.env`, or any Anthropic / Snowflake /
  Quartr API keys or tokens
- Real `Structured Narrative/transcripts_raw/` contents
- Production `Structured Narrative/output/` (Rank IC HTML, panels, spines)
- Company overlays used for live scoring with firm ISINs / credentials
- Firm SMTP / Microsoft 365 mailbox credentials
- Cloudflare tunnel tokens or R2 keys intended for internal sharing

## What you may use

- This GitHub repo clone (no secret files in the clone)
- [docker-compose.yml](../docker-compose.yml) and
  [services/earnings_monitor/Dockerfile](../services/earnings_monitor/Dockerfile)
- [services/earnings_monitor/.env.plumbing-lab.example](../services/earnings_monitor/.env.plumbing-lab.example)
  copied on-box to an untracked `.env.local`
- Empty or tiny synthetic directories for Compose bind mounts
- Mailpit only for SMTP
- `SHADOW_MODE=true`

## Locked lab shape

| Item | Value |
|---|---|
| Region | `us-east-1` |
| Compute | One EC2 + Docker Compose (not ECS/Fargate) |
| Instance start size | `t3.large` (2 vCPU / 8 GB); free-tier micro will likely OOM |
| Root volume | 40–60 GB gp3 |
| AMI | Ubuntu 22.04 or 24.04 LTS |
| SSH | Port 22 from **your public IP only** |
| Dashboard | SSH tunnel to `127.0.0.1:8501` — **never** open 8501/8025 to `0.0.0.0/0` |
| Time box | 2–4 weeks, then stop/terminate |

```text
Your laptop --SSH tunnel--> EC2 (Docker Compose)
                              monitor, worker, research-regen,
                              dashboard, mailpit
                              local disk only (no company data)
```

---

## A0. Account hygiene (day 0)

1. Enable MFA on the AWS root user and any IAM user you create.
2. Prefer an IAM user with EC2 / EBS / VPC / CloudWatch only — do not daily-drive root.
3. Create billing alarms (for example actual charges above $10 and above $50).
4. Note credit / free-tier balance; keep the lab time-boxed.
5. Confirm you will not place company secrets on this account.

---

## A1. Network + EC2

1. Default VPC is fine for the lab.
2. Create a security group:
   - Inbound **TCP 22** from your current public IP only (update when your IP changes).
   - No inbound rules for 8501, 8025, or other app ports.
3. Create a key pair; download the `.pem` once and store it privately on your laptop
   (not in the repo, not in OneDrive-synced project folders if avoidable).
4. Launch Ubuntu LTS:
   - Instance type: `t3.large` (resize later from lab notes if needed)
   - Storage: 40–60 GB gp3
   - Security group: the one above
   - Key pair: the one you created
5. Associate an Elastic IP only if you need a stable SSH target while iterating;
   release it at tear-down to avoid idle charges.

---

## A2. Host bootstrap

SSH in (replace key path and host):

```bash
ssh -i /path/to/roz-lab.pem ubuntu@YOUR_EC2_PUBLIC_DNS
```

### Install Docker Engine + Compose plugin

Follow Docker’s current Ubuntu install docs for Docker Engine and the Compose
plugin. Confirm:

```bash
docker version
docker compose version
```

Add your user to the `docker` group if needed, then log out/in so you can run
Docker without `sudo`.

### Clone the repo (no secrets)

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/bwhittakre/Earnings-Call-Summarizer.git
cd Earnings-Call-Summarizer
git checkout cursor/automated-earnings-monitor   # or the branch you use for Roz
git rev-parse --short HEAD                       # record this in lab notes
```

Do not `scp` firm `.env` files or production data trees onto the instance.

### Create empty mount directories

Compose expects several bind mounts. Create empty trees so mounts succeed:

```bash
mkdir -p \
  "Structured Narrative/config/company_overlays" \
  "Structured Narrative/transcripts_raw" \
  "Structured Narrative/output/cross_company/reports" \
  "earnings-scraper-main/earnings-scraper-main/inbox/events" \
  config/sectors

# Minimal stub files so optional env binds do not fail if referenced
touch "Structured Narrative/.env" .env
```

Keep those stub `.env` files **empty** (or comment-only). Never paste company keys.

### Plumbing-lab env file

```bash
cp services/earnings_monitor/.env.plumbing-lab.example \
   services/earnings_monitor/.env.local
# Edit only if you need path tweaks; do not add third-party secrets.
```

### Shell exports for Compose (Linux host)

```bash
export EARNINGS_MONITOR_ENV_FILE="services/earnings_monitor/.env.local"
export STRUCTURED_NARRATIVE_ENV_FILE="$PWD/Structured Narrative/.env"
export REPO_ENV_FILE="$PWD/.env"
export STRUCTURED_NARRATIVE_OUTPUT_DIR="$PWD/Structured Narrative/output"
export STRUCTURED_NARRATIVE_TRANSCRIPTS_DIR="$PWD/Structured Narrative/transcripts_raw"
# Optional: export DOCKER_PLATFORM=linux/amd64 if you standardize on amd64 images
```

Persist these in `~/.bashrc` on the **lab box only** if helpful.

---

## A3. Bring the stack up (smoke only)

```bash
docker compose build
docker compose up -d monitor worker research-regen dashboard mailpit
docker compose ps
docker compose logs --tail=100
```

### Reach the dashboard from your laptop (tunnel only)

On your laptop (not on the EC2 box):

```bash
ssh -i /path/to/roz-lab.pem -L 8501:127.0.0.1:8501 -L 8025:127.0.0.1:8025 \
  ubuntu@YOUR_EC2_PUBLIC_DNS
```

Then open:

- Dashboard: <http://localhost:8501>
- Mailpit: <http://localhost:8025>

If the page does not load, check `docker compose ps` and that you did **not**
publish 8501 on the security group.

### Lab success criteria

- All five services running (or healthy) after ~10 minutes
- Dashboard and Mailpit work **only** via the SSH tunnel
- `sudo reboot` on the instance; after reconnect, `docker compose ps` shows
  services back (`restart: unless-stopped`)
- Laptop powered off overnight; instance still running next morning
- `docker stats` sampled once at idle — record peak memory in lab notes

### Explicit non-goals (Phase A)

- Onboarding real tickers / First-Print with firm history
- Quartr live sweep against production dumps
- Rank IC / consolidated regen for the live book
- Snowflake or Anthropic calls
- Microsoft 365 or other real SMTP
- Cloudflare tunnel / public URLs

---

## A4. Capture lab lessons (required handoff artifact)

Create a short notes file (laptop-local is fine), for example
`roz-aws-lab-notes.md`, covering:

| Topic | What to record |
|---|---|
| Instance | Final instance type, AMI, region, disk size |
| Memory | Idle vs during `compose build` (`docker stats`) |
| Platform | `linux/amd64` vs host arch issues |
| Mounts | Any path fixes required on Linux vs Windows docs |
| Commands | Exact exports + compose up line that worked |
| Commit | `git rev-parse HEAD` that was running |
| Pain points | What blocked you and how you fixed it |
| Company deltas | What must change when real data/secrets appear |

Phase B reads this file. Do not skip it.

---

## A5. Tear-down discipline

When learning is done or credits run low:

```bash
cd ~/Earnings-Call-Summarizer   # or your clone path
docker compose down
```

In the AWS console (or CLI):

1. Stop then **terminate** the EC2 instance.
2. Confirm the root EBS volume is deleted (or delete it if retained).
3. Release any Elastic IP.
4. Delete the lab key pair / security group if you will not reuse them.
5. Confirm billing / credit usage returns toward zero over the next day.

---

## Quick reference

| Step | Action |
|---|---|
| Secrets | None — empty stubs only |
| Env template | `.env.plumbing-lab.example` → on-box `.env.local` |
| Up | `docker compose up -d monitor worker research-regen dashboard mailpit` |
| UI | SSH `-L 8501:...` and `-L 8025:...` |
| Next | [roz-aws-company-cutover.md](roz-aws-company-cutover.md) |
