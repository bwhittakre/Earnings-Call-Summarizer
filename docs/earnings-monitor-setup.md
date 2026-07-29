# Earnings monitor setup

## Local Apple Silicon

Prerequisites: Docker Desktop with Compose v2 and at least 4 GB available to
Docker. The default Compose platform is `linux/arm64`; set
`DOCKER_PLATFORM=linux/amd64` only when testing the AWS runtime architecture.

```bash
docker compose build
docker compose up -d
docker compose ps
```

Open the dashboard at <http://localhost:8501> and Mailpit at
<http://localhost:8025>. State is retained in the `monitor-data` and
`mailpit-data` named volumes. `docker compose down` preserves them;
`docker compose down --volumes` deletes local state.

The one-shot `history-import` service first builds the pilot-four consolidated
Parquet dataset in the shared data volume. The monitor then runs the repository's
local-provider CLI and the dashboard reads both that history and live SQLite
event state. The separate worker remains a safe SQS scaffold: when configured,
it receives messages without acknowledging them. Wire the cloud job processor
before any live promotion.

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
