"""EventBridge target that starts one poll cycle asynchronously."""

import json
import os

import boto3

lambda_client = boto3.client("lambda")


def handler(event, _context):
    function_name = os.environ["POLLER_FUNCTION_NAME"]
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps({"source": "scheduled-dispatch", "event": event}).encode(),
    )
    return {"statusCode": 202, "requestId": response.get("ResponseMetadata", {}).get("RequestId")}
