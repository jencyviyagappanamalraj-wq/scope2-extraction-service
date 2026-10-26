"""One-time: create a PRIVATE, encrypted S3 bucket.
    python app/setup_bucket.py my-unique-bucket-name
Needs AWS credentials in your environment (aws configure, or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)."""
import os, sys
from pathlib import Path
import boto3
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")   # reads AWS_* and S3_BUCKET from .env

name = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("S3_BUCKET")
region = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("AWS_REGION", "ap-south-1")
if not name:
    sys.exit("Usage: python app/setup_bucket.py <globally-unique-bucket-name> [region]")

s3 = boto3.client("s3", region_name=region, endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None)
kwargs = {"Bucket": name}
if region != "us-east-1":
    kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
from botocore.exceptions import ClientError
try:
    s3.create_bucket(**kwargs)
except ClientError as e:
    print("\nAWS refused to create the bucket:\n")
    print(e.response["Error"].get("Message", str(e)))
    print("\nIf this says 'service control policy', your AWS account belongs to an organization that blocks it. "
          "Try another region (python app/setup_bucket.py <name> us-east-1) or use a personal AWS account.")
    sys.exit(1)

# 1) no public access, ever
s3.put_public_access_block(Bucket=name, PublicAccessBlockConfiguration={
    "BlockPublicAcls": True, "IgnorePublicAcls": True,
    "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
# 2) encrypt everything at rest by default
s3.put_bucket_encryption(Bucket=name, ServerSideEncryptionConfiguration={"Rules": [
    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
# 3) keep old versions if something is overwritten by mistake
s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
print(f"Created private, encrypted bucket '{name}' in {region}")
print(f"Make sure .env has: S3_BUCKET={name} and AWS_REGION={region}")
