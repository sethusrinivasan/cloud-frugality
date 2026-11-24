"""
Pulumi Infrastructure definition for Cloud Frugality.

Provisions:
- Encrypted Amazon S3 bucket for cost, inventory, and configuration storage
- Granular IAM roles for Collector and Web Lambda functions (Least Privilege)
- AWS Lambda functions (Graviton ARM64 / Python 3.12)
- Public AWS Lambda Function URL
- EventBridge Scheduler for daily automated collection
- CloudWatch Log Groups with retention
- Mandatory 'Frugality: true' resource tags
"""
from __future__ import annotations

import json
import os
import pulumi
import pulumi_aws as aws

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
CURRENT_REGION = aws.get_region().region
CURRENT_CALLER = aws.get_caller_identity()

# Common tags enforced on all resources
COMMON_TAGS = {
    "Project": "CloudFrugality",
    "Frugality": "true",
    "ManagedBy": "Pulumi",
}

# 1. Dedicated S3 Bucket for DuckDB Storage & Settings
frugality_bucket = aws.s3.Bucket(
    "frugality-data-bucket",
    bucket_prefix="cloud-frugality-",
    force_destroy=True,
    tags=COMMON_TAGS,
)

# Enable SSE-S3 encryption
bucket_encryption = aws.s3.BucketServerSideEncryptionConfiguration(
    "frugality-bucket-encryption",
    bucket=frugality_bucket.id,
    rules=[
        aws.s3.BucketServerSideEncryptionConfigurationRuleArgs(
            apply_server_side_encryption_by_default=aws.s3.BucketServerSideEncryptionConfigurationRuleApplyServerSideEncryptionByDefaultArgs(
                sse_algorithm="AES256",
            ),
        ),
    ],
)

# Block all public S3 access
bucket_pab = aws.s3.BucketPublicAccessBlock(
    "frugality-bucket-pab",
    bucket=frugality_bucket.id,
    block_public_acls=True,
    block_public_policy=True,
    ignore_public_acls=True,
    restrict_public_buckets=True,
)

# Enforce TLS-only transport in Bucket Policy
bucket_policy = aws.s3.BucketPolicy(
    "frugality-bucket-tls-policy",
    bucket=frugality_bucket.id,
    policy=frugality_bucket.arn.apply(
        lambda arn: json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "EnforceTLSRequestsOnly",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "s3:*",
                    "Resource": [arn, f"{arn}/*"],
                    "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                }
            ],
        })
    ),
)

# 2. Package Source Code Asset
lambda_pkg_dir = os.path.join(REPO_ROOT, "build", "lambda_python")
if os.path.isdir(lambda_pkg_dir):
    lambda_code = pulumi.FileArchive(lambda_pkg_dir)
else:
    lambda_code = pulumi.FileArchive(os.path.join(SRC_DIR, "python"))

# 3. Collector Lambda & Granular IAM Role
collector_role = aws.iam.Role(
    "collector-execution-role",
    name_prefix="cloud-frugality-collector-",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "sts:AssumeRole",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Effect": "Allow",
            }
        ],
    }),
    tags=COMMON_TAGS,
)

# Collector S3 Permissions (Read & Write to Frugality Bucket)
collector_s3_policy = aws.iam.RolePolicy(
    "collector-s3-policy",
    role=collector_role.id,
    policy=frugality_bucket.arn.apply(
        lambda arn: json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "CollectorS3ScopedAccess",
                    "Effect": "Allow",
                    "Action": [
                        "s3:PutObject",
                        "s3:GetObject",
                        "s3:ListBucket",
                    ],
                    "Resource": [arn, f"{arn}/*"],
                }
            ],
        })
    ),
)

# Collector Cost Explorer, FreeTier, and Inventory Permissions
collector_ce_policy = aws.iam.RolePolicy(
    "collector-ce-inventory-policy",
    role=collector_role.id,
    policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadBillingAndFreeTier",
                "Effect": "Allow",
                "Action": [
                    "ce:GetCostAndUsage",
                    "ce:GetCostForecast",
                    "ce:GetDimensionValues",
                    "freetier:GetAccountPlanState",
                    "freetier:GetFreeTierUsage",
                ],
                "Resource": "*",
            },
            {
                "Sid": "ReadResourceTaggingAndInventory",
                "Effect": "Allow",
                "Action": [
                    "tag:GetResources",
                    "lambda:ListFunctions",
                    "rds:DescribeDBInstances",
                ],
                "Resource": "*",
            },
        ],
    }),
)

# CloudWatch Logging Policy for Collector
collector_log_group = aws.cloudwatch.LogGroup(
    "collector-log-group",
    name="/aws/lambda/cloud-frugality-collector",
    retention_in_days=3,
    tags=COMMON_TAGS,
)

collector_log_policy = aws.iam.RolePolicy(
    "collector-log-policy",
    role=collector_role.id,
    policy=collector_log_group.arn.apply(
        lambda arn: json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "CreateLogEvents",
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                    "Resource": f"{arn}:*",
                }
            ],
        })
    ),
)

collector_fn = aws.lambda_.Function(
    "collector-function",
    name="cloud-frugality-collector",
    runtime="python3.12",
    architectures=["x86_64"],
    handler="handler.lambda_handler",
    role=collector_role.arn,
    code=lambda_code,
    timeout=120,
    memory_size=512,
    environment=aws.lambda_.FunctionEnvironmentArgs(
        variables={
            "FRUGALITY_S3_BUCKET": frugality_bucket.id,
            "FRUGALITY_S3_PREFIX": "frugality/python",
            "AWS_REGION_NAME": CURRENT_REGION,
            "LOG_LEVEL": "INFO",
            "BURN_WINDOW_DAYS": "7",
            "HARVEST_WINDOW_DAYS": "30",
            "ASSUMED_CREDIT_GRANT_USD": "200",
        }
    ),
    tags=COMMON_TAGS,
)

# 4. Web Portal Lambda & Granular IAM Role (Least Privilege)
web_role = aws.iam.Role(
    "web-execution-role",
    name_prefix="cloud-frugality-web-",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "sts:AssumeRole",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Effect": "Allow",
            }
        ],
    }),
    tags=COMMON_TAGS,
)

# Web S3 Permissions: Read all DuckDB data, write only to settings prefix
web_s3_policy = aws.iam.RolePolicy(
    "web-s3-scoped-policy",
    role=web_role.id,
    policy=frugality_bucket.arn.apply(
        lambda arn: json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "WebReadDuckDBData",
                    "Effect": "Allow",
                    "Action": ["s3:GetObject", "s3:ListBucket"],
                    "Resource": [arn, f"{arn}/*"],
                },
                {
                    "Sid": "WebWriteSettingsOnly",
                    "Effect": "Allow",
                    "Action": ["s3:PutObject"],
                    "Resource": [
                        f"{arn}/frugality/python/settings/*",
                        f"{arn}/frugality/rust/settings/*",
                        f"{arn}/frugality/settings/*",
                    ],
                },
            ],
        })
    ),
)

# Web Lambda Permission to invoke Collector on-demand if real data refresh is needed
web_invoke_collector_policy = aws.iam.RolePolicy(
    "web-invoke-collector-policy",
    role=web_role.id,
    policy=collector_fn.arn.apply(
        lambda arn: json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "InvokeCollectorOnDemand",
                    "Effect": "Allow",
                    "Action": ["lambda:InvokeFunction"],
                    "Resource": arn,
                }
            ],
        })
    ),
)

web_log_group = aws.cloudwatch.LogGroup(
    "web-log-group",
    name="/aws/lambda/cloud-frugality-web",
    retention_in_days=3,
    tags=COMMON_TAGS,
)

web_log_policy = aws.iam.RolePolicy(
    "web-log-policy",
    role=web_role.id,
    policy=web_log_group.arn.apply(
        lambda arn: json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "CreateWebLogEvents",
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                    "Resource": f"{arn}:*",
                }
            ],
        })
    ),
)

PYTHON_ENDPOINT_URL = "https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/"
RUST_ENDPOINT_URL = "https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/"

web_fn = aws.lambda_.Function(
    "web-function",
    name="cloud-frugality-web",
    runtime="python3.12",
    architectures=["x86_64"],
    handler="web.lambda_handler",
    role=web_role.arn,
    code=lambda_code,
    timeout=60,
    memory_size=1024,
    environment=aws.lambda_.FunctionEnvironmentArgs(
        variables={
            "FRUGALITY_S3_BUCKET": frugality_bucket.id,
            "FRUGALITY_S3_PREFIX": "frugality/python",
            "FRUGALITY_PARQUET_KEY": "frugality/datasets/aws_1m_usage.parquet",
            "AWS_REGION_NAME": CURRENT_REGION,
            "COST_WINDOW_DAYS": "30",
            "LOG_LEVEL": "INFO",
            "COLLECTOR_FUNCTION_NAME": collector_fn.name,
            "PYTHON_WEB_URL": PYTHON_ENDPOINT_URL,
            "RUST_WEB_URL": RUST_ENDPOINT_URL,
        }
    ),
    tags=COMMON_TAGS,
)

# Function URL for Web Dashboard
web_fn_url = aws.lambda_.FunctionUrl(
    "web-function-url",
    function_name=web_fn.name,
    authorization_type="NONE",
    cors=aws.lambda_.FunctionUrlCorsArgs(
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    ),
)

# 5. Recurring Schedule via EventBridge Rule & Targets (Twice Daily)
harvest_schedule_rule = aws.cloudwatch.EventRule(
    "twice-daily-collector-schedule",
    schedule_expression="cron(0 0,12 * * ? *)",
    description="Triggers Cloud Frugality cost & inventory collector twice daily (00:00 and 12:00 UTC) to harvest real AWS Cost Explorer & Resource data",
    tags=COMMON_TAGS,
)

daily_target = aws.cloudwatch.EventTarget(
    "daily-collector-target",
    rule=harvest_schedule_rule.name,
    arn=collector_fn.arn,
    input=json.dumps({"source": "scheduled", "window_days": 30}),
)

schedule_permission = aws.lambda_.Permission(
    "allow-eventbridge-invoke-collector",
    action="lambda:InvokeFunction",
    function=collector_fn.name,
    principal="events.amazonaws.com",
    source_arn=harvest_schedule_rule.arn,
)

# 5. Rust Implementation Lambda Functions & Corresponding Resources
rust_pkg_dir = os.path.join(REPO_ROOT, "build", "lambda_rust")
if os.path.isdir(rust_pkg_dir):
    rust_code = pulumi.FileArchive(rust_pkg_dir)
else:
    rust_bootstrap = os.path.join(SRC_DIR, "rust", "bootstrap")
    if os.path.exists(rust_bootstrap):
        rust_code = pulumi.AssetArchive({"bootstrap": pulumi.FileAsset(rust_bootstrap)})
    else:
        rust_code = pulumi.FileArchive(os.path.join(SRC_DIR, "rust"))

rust_common_tags = {
    **COMMON_TAGS,
    "Engine": "Rust",
    "ApplicationName": "CloudFrugality-Rust",
}

# Rust Web Function URL
web_rust_log_group = aws.cloudwatch.LogGroup(
    "web-rust-log-group",
    name="/aws/lambda/cloud-frugality-web-rust",
    retention_in_days=3,
    tags=rust_common_tags,
)

web_rust_fn = aws.lambda_.Function(
    "web-rust-function",
    name="cloud-frugality-web-rust",
    runtime="provided.al2023",
    architectures=["x86_64"],
    handler="bootstrap",
    role=web_role.arn,
    code=rust_code,
    timeout=30,
    memory_size=256,
    environment=aws.lambda_.FunctionEnvironmentArgs(
        variables={
            "FRUGALITY_S3_BUCKET": frugality_bucket.id,
            "FRUGALITY_S3_PREFIX": "frugality/rust",
            "AWS_REGION_NAME": CURRENT_REGION,
            "COST_WINDOW_DAYS": "30",
            "LOG_LEVEL": "INFO",
            "PYTHON_WEB_URL": PYTHON_ENDPOINT_URL,
            "RUST_WEB_URL": RUST_ENDPOINT_URL,
        }
    ),
    tags=rust_common_tags,
)

web_rust_fn_url = aws.lambda_.FunctionUrl(
    "web-rust-function-url",
    function_name=web_rust_fn.name,
    authorization_type="NONE",
    cors=aws.lambda_.FunctionUrlCorsArgs(
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    ),
)

# Rust Collector Lambda
collector_rust_log_group = aws.cloudwatch.LogGroup(
    "collector-rust-log-group",
    name="/aws/lambda/cloud-frugality-collector-rust",
    retention_in_days=3,
    tags=rust_common_tags,
)

collector_rust_fn = aws.lambda_.Function(
    "collector-rust-function",
    name="cloud-frugality-collector-rust",
    runtime="provided.al2023",
    architectures=["x86_64"],
    handler="bootstrap",
    role=collector_role.arn,
    code=rust_code,
    timeout=120,
    memory_size=256,
    environment=aws.lambda_.FunctionEnvironmentArgs(
        variables={
            "FRUGALITY_S3_BUCKET": frugality_bucket.id,
            "FRUGALITY_S3_PREFIX": "frugality/rust",
            "AWS_REGION_NAME": CURRENT_REGION,
            "LOG_LEVEL": "INFO",
            "BURN_WINDOW_DAYS": "7",
            "ASSUMED_CREDIT_GRANT_USD": "200",
        }
    ),
    tags=rust_common_tags,
)

# Recurring Schedule target for Rust Collector
daily_target_rust = aws.cloudwatch.EventTarget(
    "daily-collector-rust-target",
    rule=harvest_schedule_rule.name,
    arn=collector_rust_fn.arn,
    input=json.dumps({"source": "scheduled", "engine": "rust", "window_days": 30}),
)

schedule_permission_rust = aws.lambda_.Permission(
    "allow-eventbridge-invoke-collector-rust",
    action="lambda:InvokeFunction",
    function=collector_rust_fn.name,
    principal="events.amazonaws.com",
    source_arn=harvest_schedule_rule.arn,
)

# Exports
pulumi.export("bucket_name", frugality_bucket.id)
pulumi.export("bucket_arn", frugality_bucket.arn)
pulumi.export("collector_function_name", collector_fn.name)
pulumi.export("collector_python_function_name", collector_fn.name)
pulumi.export("collector_rust_function_name", collector_rust_fn.name)
pulumi.export("web_function_name", web_fn.name)
pulumi.export("web_python_function_name", web_fn.name)
pulumi.export("web_rust_function_name", web_rust_fn.name)
pulumi.export("web_url", web_fn_url.function_url)
pulumi.export("web_python_url", web_fn_url.function_url)
pulumi.export("web_rust_url", web_rust_fn_url.function_url)
