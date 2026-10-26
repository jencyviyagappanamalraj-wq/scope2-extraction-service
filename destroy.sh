#!/usr/bin/env bash
# Removes the whole stack. Never delete AWS resources by hand.
# Do NOT delete the bucket/stack named aws-sam-cli-managed-default: SAM needs it.
set -euo pipefail
STACK=scope2-hello
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-south-1}}"
BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)
aws s3 rm "s3://$BUCKET" --recursive || true
sam delete --stack-name "$STACK" --region "$REGION" --no-prompts
