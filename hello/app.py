import json
import os
import time

import boto3

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
table = dynamodb.Table(os.environ["TABLE_NAME"])


def handler(event, context):
    job_id = f"hello-{int(time.time())}"
    table.put_item(Item={"job_id": job_id, "status": "ok"})
    s3.put_object(
        Bucket=os.environ["BUCKET_NAME"],
        Key=f"tests/{job_id}.txt",
        Body=b"hello from scope 2",
    )
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"ok": True, "job_id": job_id}),
    }
