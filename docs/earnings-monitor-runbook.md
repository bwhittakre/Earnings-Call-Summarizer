# Earnings monitor runbook

## Operating model

EventBridge invokes the dispatcher, which asynchronously invokes the poller.
The poller records a DynamoDB audit row and eventually publishes work to
SQS. Fargate workers consume SQS; failed jobs move to the DLQ after three
receives. The Streamlit service is behind an ALB. S3 stores durable artifacts,
while CloudWatch retains service logs and alarms on poller errors, stopped
workers, and DLQ depth.

The initial infrastructure sets `SHADOW_MODE=true`. The poller discovers zero
jobs by design and the worker does not delete messages until application
processing is wired.

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

**Credential exposure:** disable affected tasks/Lambdas, rotate the secret at
the provider and Secrets Manager, review CloudTrail, then redeploy. Never paste
secret values into tickets or logs.

**Rollback:** deploy the prior immutable image tag with CDK. Retained S3 and
DynamoDB resources survive stack updates/deletion; verify schema compatibility
before rollback.

## Known deployment gates

AWS deployment, DNS, ACM, Cognito, Secrets Manager values, SES production
approval, alarm notification routing, and third-party data access all require
account-owner action. The infrastructure cannot validate these without
credentials. The monitor discovery and job processor are still explicit
scaffolds and must be implemented before live processing.
