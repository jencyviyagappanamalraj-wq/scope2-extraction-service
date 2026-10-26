#!/usr/bin/env bash
# Run this in AWS CloudShell (or any Linux shell with AWS CLI + SAM CLI).
set -euo pipefail
STACK=scope2-hello
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-south-1}}"
sam build
sam deploy --stack-name "$STACK" --region "$REGION" \
  --resolve-s3 --capabilities CAPABILITY_IAM --no-confirm-changeset
aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs" --output table
