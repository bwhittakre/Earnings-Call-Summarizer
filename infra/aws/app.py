#!/usr/bin/env python3
import aws_cdk as cdk

from earnings_monitor_stack import EarningsMonitorStack

app = cdk.App()
if not app.node.try_get_context("container_image"):
    app.node.set_context(
        "container_image", "public.ecr.aws/docker/library/python:3.12-slim"
    )
EarningsMonitorStack(
    app,
    "EarningsMonitor",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
)
app.synth()
