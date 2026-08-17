# Earnings monitor access validation

Complete these checks before requesting a live deployment. They are external
gates; CDK synthesis cannot prove them.

## AWS and network

- `aws sts get-caller-identity` returns the intended account and deployment role.
- The role can deploy CloudFormation/CDK assets and pass the generated ECS and
  Lambda roles; organization SCPs permit all declared services.
- ECR contains both `linux/amd64` and `linux/arm64` manifests for the selected tag.
- The ACM certificate is `ISSUED`, in the stack region, and covers the dashboard
  DNS name. DNS changes can be made by the deployment owner.
- Cognito callback and sign-out URLs match the final HTTPS dashboard URL. The
  app client generates a secret, as required by ALB Cognito authentication.

## Data and credentials

- The referenced Secrets Manager secret exists in-region. Its resource policy
  permits the generated task/Lambda roles; its value is never copied to CDK
  context.
- SEC EDGAR has a compliant organization/contact user agent and request-rate
  policy.
- Third-party transcript/data licenses allow scheduled cloud processing and
  storage.
- S3 retention, DynamoDB point-in-time recovery, and data classification have
  owner approval.

## Email

- SES identity/domain is verified with SPF/DKIM.
- If SES remains in sandbox, every recipient is verified. Otherwise production
  access and sending limits are approved.
- `MAIL FROM`, bounce/complaint handling, suppression-list ownership, and an
  alarm notification destination are defined.

## Validation commands

```powershell
aws sts get-caller-identity
aws ecr describe-images --repository-name earnings-monitor
aws acm describe-certificate --certificate-arn CERTIFICATE_ARN
aws sesv2 get-account
aws secretsmanager describe-secret --secret-id APP_SECRET_ARN
npx aws-cdk diff -c container_image=IMAGE_URI # plus production contexts
```

Stop if any command resolves to a different account/region, if HTTPS or Cognito
is absent, or if SES/data licensing is not approved.
