from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
    aws_applicationautoscaling as appscaling,
    aws_certificatemanager as acm,
    aws_cloudwatch as cloudwatch,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_actions as elbv2_actions,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    aws_sqs as sqs,
)
from constructs import Construct


class EarningsMonitorStack(Stack):
    """Credential-free-to-synth deployment scaffold for the earnings monitor."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)
        Tags.of(self).add("Application", "earnings-monitor")
        Tags.of(self).add("ManagedBy", "aws-cdk")

        schedule = self.node.try_get_context("schedule") or "cron(0/15 * * * ? *)"
        image_uri = self.node.try_get_context("container_image")
        if not image_uri:
            raise ValueError("CDK context container_image must be a deployable multi-arch image URI")

        artifacts = s3.Bucket(
            self,
            "Artifacts",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(30))],
            removal_policy=RemovalPolicy.RETAIN,
        )
        state = dynamodb.Table(
            self,
            "State",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        dlq = sqs.Queue(
            self,
            "JobsDlq",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            retention_period=Duration.days(14),
        )
        jobs = sqs.Queue(
            self,
            "Jobs",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            visibility_timeout=Duration.minutes(20),
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=3),
        )

        lambda_dir = str(Path(__file__).parent / "lambda")
        poller = lambda_.Function(
            self,
            "Poller",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="poller.handler",
            code=lambda_.Code.from_asset(lambda_dir),
            timeout=Duration.minutes(2),
            memory_size=256,
            environment={
                "QUEUE_URL": jobs.queue_url,
                "STATE_TABLE_NAME": state.table_name,
                "ARTIFACT_BUCKET_NAME": artifacts.bucket_name,
                "SHADOW_MODE": "true",
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        jobs.grant_send_messages(poller)
        state.grant_read_write_data(poller)
        artifacts.grant_read_write(poller)

        dispatcher = lambda_.Function(
            self,
            "Dispatcher",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="dispatcher.handler",
            code=lambda_.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={"POLLER_FUNCTION_NAME": poller.function_name},
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        poller.grant_invoke(dispatcher)
        events.Rule(
            self,
            "MonitorSchedule",
            schedule=events.Schedule.expression(schedule),
            targets=[targets.LambdaFunction(dispatcher, retry_attempts=2)],
        )

        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
        )
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights=True)
        image = ecs.ContainerImage.from_registry(image_uri)

        worker_task = ecs.FargateTaskDefinition(
            self, "WorkerTask", cpu=512, memory_limit_mib=1024
        )
        worker = worker_task.add_container(
            "Worker",
            image=image,
            command=["worker"],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="worker", log_retention=logs.RetentionDays.ONE_MONTH
            ),
            environment={
                "APP_ENV": "aws",
                "QUEUE_URL": jobs.queue_url,
                "STATE_TABLE_NAME": state.table_name,
                "ARTIFACT_BUCKET_NAME": artifacts.bucket_name,
                "SHADOW_MODE": "true",
            },
        )
        worker.add_port_mappings(ecs.PortMapping(container_port=8501))
        jobs.grant_consume_messages(worker_task.task_role)
        state.grant_read_write_data(worker_task.task_role)
        artifacts.grant_read_write(worker_task.task_role)
        worker_service = ecs.FargateService(
            self,
            "WorkerService",
            cluster=cluster,
            task_definition=worker_task,
            desired_count=1,
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            enable_execute_command=True,
        )
        worker_service.auto_scale_task_count(min_capacity=1, max_capacity=10).scale_on_metric(
            "QueueDepth",
            metric=jobs.metric_approximate_number_of_messages_visible(),
            scaling_steps=[
                appscaling.ScalingInterval(upper=0, change=-1),
                appscaling.ScalingInterval(lower=1, change=1),
                appscaling.ScalingInterval(lower=25, change=4),
            ],
            cooldown=Duration.minutes(2),
        )

        dashboard_task = ecs.FargateTaskDefinition(
            self, "DashboardTask", cpu=512, memory_limit_mib=1024
        )
        dashboard = dashboard_task.add_container(
            "Dashboard",
            image=image,
            command=["dashboard"],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="dashboard", log_retention=logs.RetentionDays.ONE_MONTH
            ),
            environment={
                "APP_ENV": "aws",
                "DATA_DIR": "/tmp/data",
                "STATE_TABLE_NAME": state.table_name,
                "ARTIFACT_BUCKET_NAME": artifacts.bucket_name,
                "SHADOW_MODE": "true",
            },
        )
        dashboard.add_port_mappings(ecs.PortMapping(container_port=8501))
        state.grant_read_data(dashboard_task.task_role)
        artifacts.grant_read(dashboard_task.task_role)

        certificate_arn = self.node.try_get_context("certificate_arn")
        certificate = (
            acm.Certificate.from_certificate_arn(self, "Certificate", certificate_arn)
            if certificate_arn
            else None
        )
        dashboard_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "DashboardService",
            cluster=cluster,
            task_definition=dashboard_task,
            desired_count=1,
            public_load_balancer=True,
            assign_public_ip=True,
            listener_port=443 if certificate else 80,
            protocol=elbv2.ApplicationProtocol.HTTPS if certificate else elbv2.ApplicationProtocol.HTTP,
            certificate=certificate,
            redirect_http=bool(certificate),
            health_check_grace_period=Duration.minutes(2),
        )
        dashboard_service.target_group.configure_health_check(path="/_stcore/health")

        auth_values = {
            "pool": self.node.try_get_context("cognito_user_pool_arn"),
            "client": self.node.try_get_context("cognito_user_pool_client_id"),
            "domain": self.node.try_get_context("cognito_user_pool_domain"),
        }
        if any(auth_values.values()) and not all(auth_values.values()):
            raise ValueError("all three Cognito contexts must be set together")
        if all(auth_values.values()):
            if not certificate:
                raise ValueError("Cognito authentication requires certificate_arn (HTTPS)")
            user_pool = cognito.UserPool.from_user_pool_arn(
                self, "DashboardUserPool", auth_values["pool"]
            )
            user_pool_client = cognito.UserPoolClient.from_user_pool_client_id(
                self, "DashboardUserPoolClient", auth_values["client"]
            )
            user_pool_domain = cognito.UserPoolDomain.from_domain_name(
                self, "DashboardUserPoolDomain", auth_values["domain"]
            )
            dashboard_service.listener.add_action(
                "CognitoAuth",
                priority=1,
                conditions=[elbv2.ListenerCondition.path_patterns(["/*"])],
                action=elbv2_actions.AuthenticateCognitoAction(
                    user_pool=user_pool,
                    user_pool_client=user_pool_client,
                    user_pool_domain=user_pool_domain,
                    next=elbv2.ListenerAction.forward([dashboard_service.target_group]),
                ),
            )

        secret_arn = self.node.try_get_context("app_secret_arn")
        if secret_arn:
            secret = secretsmanager.Secret.from_secret_complete_arn(
                self, "ApplicationSecret", secret_arn
            )
            secret.grant_read(worker_task.task_role)
            secret.grant_read(dashboard_task.task_role)
            poller.add_environment("APP_SECRET_ARN", secret_arn)
            worker.add_environment("APP_SECRET_ARN", secret_arn)

        ses_identity_arn = self.node.try_get_context("ses_identity_arn")
        if ses_identity_arn:
            send_policy = iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"], resources=[ses_identity_arn]
            )
            poller.add_to_role_policy(send_policy)
            worker_task.add_to_task_role_policy(send_policy)
            poller.add_environment("SES_IDENTITY_ARN", ses_identity_arn)
            worker.add_environment("SES_IDENTITY_ARN", ses_identity_arn)

        cloudwatch.Alarm(
            self,
            "DlqNotEmpty",
            metric=dlq.metric_approximate_number_of_messages_visible(),
            threshold=1,
            evaluation_periods=1,
        )
        cloudwatch.Alarm(
            self,
            "WorkerStopped",
            metric=worker_service.metric("RunningTaskCount"),
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            evaluation_periods=2,
        )
        cloudwatch.Alarm(
            self,
            "PollerErrors",
            metric=poller.metric_errors(),
            threshold=1,
            evaluation_periods=1,
        )

        CfnOutput(self, "DashboardUrl", value=dashboard_service.load_balancer.load_balancer_dns_name)
        CfnOutput(self, "JobsQueueUrl", value=jobs.queue_url)
        CfnOutput(self, "ArtifactsBucket", value=artifacts.bucket_name)
        CfnOutput(self, "StateTable", value=state.table_name)
        CfnOutput(
            self,
            "ProductionGate",
            value="Set certificate/auth/image/secret/SES contexts before production.",
        )
