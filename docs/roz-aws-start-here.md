# START HERE — Roz always-on lab (beginner path)

You only need this file for now. Ignore company AWS, ECS, Snowflake Streamlit,
and the longer lab doc until the checklist at the bottom says you are ready.

**Goal of this path:** rent one small computer in AWS, install Docker, start Roz
containers with **no company data**, prove they stay up when your laptop is off.

**Not the goal yet:** live earnings, real API keys, firm data, or “production.”

Work **one day / one session at a time**. Stop when the session checklist is done.

---

## Before anything else (2 minutes)

Write this on a sticky note:

> Personal AWS = practice plumbing only.  
> No Cassius `.env`, transcripts, Snowflake, Anthropic, Quartr, or work email passwords.

If you are tempted to copy work secrets “just to test,” stop. That is a later
phase on **company** AWS.

---

## Big picture (so the steps make sense)

| Piece | Plain English |
|---|---|
| AWS account | Your personal login + billing/credits |
| EC2 | One rented Linux computer that stays on |
| Security group | Firewall: only you can SSH in |
| Key pair (`.pem`) | Password file for SSH — keep it private |
| Docker Compose | Same “start Roz services” tool you use locally |
| SSH tunnel | Safe way to open the dashboard on *your* laptop without exposing it to the internet |

You will: create the computer → log in → install Docker → clone the repo →
`docker compose up` → open the UI through a tunnel → reboot / leave overnight →
write short notes → turn the computer off when done learning.

---

## Session 1 — Account safety (do this first)

Do these in the AWS website (console). Region: top-right, set to **US East (N. Virginia) / us-east-1**.

### 1. Turn on MFA

1. Sign in at <https://console.aws.amazon.com/>
2. Click your account name (top right) → **Security credentials**
3. Under **Multi-factor authentication**, assign MFA to the root user
4. Follow the prompts (phone authenticator app is fine)

### 2. Billing alarm (so credits don’t vanish unnoticed)

1. Search for **Billing** → open Billing and Cost Management  
   (or Billing → Preferences → enable “Receive Billing Alerts” if asked)
2. Search for **CloudWatch** → **Alarms** → **All alarms** → **Create alarm**
3. Select metric: **Billing** → **Total Estimated Charge** (USD)  
   If Billing metrics are missing, enable them under Billing preferences first, wait ~15 minutes, retry.
4. Threshold: greater than **10** (create a second alarm at **50** the same way)
5. Create an SNS topic / email subscription when prompted; confirm the email

### 3. Optional but smart: stop using root daily

1. Search **IAM** → **Users** → **Create user**
2. Name it e.g. `roz-lab-admin`
3. Attach policies: `AmazonEC2FullAccess`, `CloudWatchFullAccess`  
   (good enough for the lab; tighten later if you want)
4. Enable console password + access keys only if you need CLI later
5. Sign out of root; sign in as this user for the rest of the lab

**Session 1 done when:** MFA on, at least one billing alarm email confirmed.

---

## Session 2 — Create the computer (EC2)

Still in **us-east-1**.

### 1. Find your public IP

On your laptop, open <https://checkip.amazonaws.com/> and copy the number  
(e.g. `203.0.113.10`). You will allow SSH only from that address.

### 2. Create a key pair

1. Search **EC2** → left menu **Key Pairs** → **Create key pair**
2. Name: `roz-plumbing-lab`
3. Type: **RSA**, format: **`.pem`** (for OpenSSH; on Windows use this with
   Windows OpenSSH or convert later — see Session 3)
4. Create; save the downloaded `.pem` somewhere private  
   Example: `C:\Users\BobbyWhittaker\.ssh\roz-plumbing-lab.pem`  
   **Not** inside the git repo.

### 3. Create a security group (firewall)

1. EC2 → **Security Groups** → **Create security group**
2. Name: `roz-plumbing-lab-sg`
3. Description: `SSH only for Roz lab`
4. Inbound rules → **Add rule**:
   - Type: **SSH**
   - Port: **22**
   - Source: **My IP** (or paste `YOUR_IP/32`)
5. Do **not** add rules for 8501 or 8025
6. Create

### 4. Launch the instance

1. EC2 → **Instances** → **Launch instances**
2. Name: `roz-plumbing-lab`
3. AMI: **Ubuntu Server 24.04 LTS** (or 22.04 LTS)
4. Instance type: **t3.large**  
   (Yes, larger than free-tier micro. Micro will likely fail for this stack.
   Your credits are for this kind of learning.)
5. Key pair: `roz-plumbing-lab`
6. Network → edit:
   - Security group: select `roz-plumbing-lab-sg` (not “allow SSH from anywhere”)
7. Storage: **40 GiB** gp3 (or 60 if offered easily)
8. Launch

Wait until **Instance state = Running** and **Status checks** pass (2/2).

Copy the **Public IPv4 address** (or Public DNS). You need it for SSH.

**Session 2 done when:** one Running Ubuntu instance, SSH-only security group, `.pem` saved.

---

## Session 3 — Log into the computer

On **Windows PowerShell** (adjust paths):

```powershell
# Lock down key permissions (required by SSH)
icacls $env:USERPROFILE\.ssh\roz-plumbing-lab.pem /inheritance:r
icacls $env:USERPROFILE\.ssh\roz-plumbing-lab.pem /grant:r "$env:USERNAME:(R)"

ssh -i $env:USERPROFILE\.ssh\roz-plumbing-lab.pem ubuntu@PASTE_PUBLIC_IP_HERE
```

- First time: type `yes` to trust the host
- Prompt should look like `ubuntu@ip-...:~$`

If SSH fails:

- Confirm instance is Running
- Confirm security group source still matches your current IP (home IP changes)
- Confirm username is `ubuntu` for Ubuntu AMIs

**Session 3 done when:** you have a Linux shell on the EC2 box.

---

## Session 4 — Install Docker on the box

You are **on the EC2 machine** (SSH session). Paste these blocks one at a time.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker ubuntu
```

Log out and back in so the `docker` group applies:

```bash
exit
```

Then SSH in again (same `ssh -i ...` command as Session 3).

Check:

```bash
docker version
docker compose version
```

**Session 4 done when:** both commands print version info without permission errors.

---

## Session 5 — Put Roz on the box (no secrets)

Still on EC2:

```bash
cd ~
git clone https://github.com/bwhittakre/Earnings-Call-Summarizer.git
cd Earnings-Call-Summarizer
git checkout cursor/automated-earnings-monitor
git rev-parse --short HEAD
```

Create empty folders and empty stub env files (no keys):

```bash
mkdir -p \
  "Structured Narrative/config/company_overlays" \
  "Structured Narrative/transcripts_raw" \
  "Structured Narrative/output/cross_company/reports" \
  "earnings-scraper-main/earnings-scraper-main/inbox/events" \
  config/sectors

touch "Structured Narrative/.env" .env

cp services/earnings_monitor/.env.plumbing-lab.example \
   services/earnings_monitor/.env.local
```

Set Compose environment variables (paste every time you open a new SSH session,
or append to `~/.bashrc`):

```bash
cd ~/Earnings-Call-Summarizer
export EARNINGS_MONITOR_ENV_FILE="services/earnings_monitor/.env.local"
export STRUCTURED_NARRATIVE_ENV_FILE="$PWD/Structured Narrative/.env"
export REPO_ENV_FILE="$PWD/.env"
export STRUCTURED_NARRATIVE_OUTPUT_DIR="$PWD/Structured Narrative/output"
export STRUCTURED_NARRATIVE_TRANSCRIPTS_DIR="$PWD/Structured Narrative/transcripts_raw"
```

**Session 5 done when:** repo exists, `.env.local` is the plumbing-lab copy, exports are set.

---

## Session 6 — Start Roz (smoke)

On EC2 (same exports as Session 5):

```bash
cd ~/Earnings-Call-Summarizer
docker compose build
docker compose up -d monitor worker research-regen dashboard mailpit
docker compose ps
docker compose logs --tail=50
```

First `build` can take a long time. That is normal.

You want `ps` to show those services running (or healthy). If something exits,
run `docker compose logs NAME` for that service and fix mounts/env — still
without adding company secrets.

### Open the dashboard safely (from your laptop)

New PowerShell window on your **laptop** (leave EC2 running):

```powershell
ssh -i $env:USERPROFILE\.ssh\roz-plumbing-lab.pem `
  -L 8501:127.0.0.1:8501 `
  -L 8025:127.0.0.1:8025 `
  ubuntu@PASTE_PUBLIC_IP_HERE
```

Keep that window open. On the laptop browser:

- Dashboard: <http://localhost:8501>
- Mailpit: <http://localhost:8025>

**Session 6 done when:** `docker compose ps` looks good and the dashboard loads via the tunnel.

---

## Session 7 — Prove “always on”

On EC2:

```bash
sudo reboot
```

Wait ~2 minutes, SSH back in, re-export the env vars if needed, then:

```bash
cd ~/Earnings-Call-Summarizer
docker compose ps
```

Containers should come back (`restart: unless-stopped`).

Then: shut your **laptop** overnight; leave EC2 running. Next morning SSH in —
instance still Running, compose still up.

**Session 7 done when:** reboot recovery works and overnight-with-laptop-off works.

---

## Session 8 — Write lab notes (required)

On your laptop, create a simple text/markdown file (Desktop is fine), e.g.
`roz-aws-lab-notes.md`, and fill in:

- Instance type and disk size used
- Approx memory from `docker stats` at idle
- Commit SHA that was running
- Exact exports + compose command
- Anything that broke and how you fixed it
- What you will change for company AWS later (real secrets, real data mounts)

You need this when company AWS exists. Do not skip it.

---

## Session 9 — When you are done learning: turn it off

Credits continue while EC2 runs. When the lab has taught you enough:

On EC2:

```bash
cd ~/Earnings-Call-Summarizer
docker compose down
exit
```

In AWS console → EC2 → Instances → select `roz-plumbing-lab` → **Instance state**
→ **Terminate instance**. Confirm the disk is deleted. Release any Elastic IP
if you created one.

---

## What to ignore until later

| Topic | When |
|---|---|
| Company data / real API keys | Company AWS only — [roz-aws-company-cutover.md](roz-aws-company-cutover.md) |
| Full detail / edge cases | [roz-aws-plumbing-lab.md](roz-aws-plumbing-lab.md) |
| ECS / Fargate / CDK | After company EC2 works |
| Live Quartr / Rank IC book | Not part of this lab |

---

## If you feel stuck

Reply with **which session number** you are on and the **exact error text**
(or a screenshot description). Do not jump ahead sessions to “make it real”
with company secrets — that recreates the overwhelm and the risk.
