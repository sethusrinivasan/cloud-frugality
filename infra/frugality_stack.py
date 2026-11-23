"""
CDK Stack definition for Cloud Frugality infrastructure.
"""
from __future__ import annotations

import os
import jsii
from aws_cdk import (
    Duration,
    Stack,
    CfnOutput,
    RemovalPolicy,
    BundlingOptions,
    DockerImage,
    ILocalBundling,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_logs as logs,
    aws_scheduler as scheduler,
)
from constructs import Construct

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB_ENDPOINT = "reality-check-cost-tracker.cluster-c52ymc6u0ruy.us-east-2.rds.amazonaws.com"
DEFAULT_DB_RESOURCE_ID = "cluster-DJLU4ZBVHZ6HGQCZTXR7YKDQ7Q"


@jsii.implements(ILocalBundling)
class LocalCollectorBundler:
    def try_bundle(self, output_dir: str, options) -> bool:
        import shutil
        import subprocess
        src = os.path.join(REPO_ROOT, "src")
        try:
            for name in os.listdir(src):
                s = os.path.join(src, name)
                d = os.path.join(output_dir, name)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
            subprocess.run(
                [
                    "pip", "install",
                    "-r", os.path.join(output_dir, "requirements.txt"),
                    "-t", output_dir,
                    "--platform", "manylinux2014_aarch64",
                    "--implementation", "cp",
                    "--python-version", "3.12",
                    "--only-binary=:all:",
                    "--upgrade",
                ],
                check=True,
            )
            subprocess.run(
                ["bash", "-c", f"find '{output_dir}' -name __pycache__ -type d -prune -exec rm -rf {{}} + || true"],
                check=False,
            )
            return True
        except Exception:
            return False


class CloudFrugalityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cluster_endpoint: str = DEFAULT_DB_ENDPOINT,
        cluster_resource_id: str = DEFAULT_DB_RESOURCE_ID,
        db_name: str = "postgres",
        db_iam_user: str = "cost_collector",
        db_reader_user: str = "cost_reader",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bundling = BundlingOptions(
            image=DockerImage.from_registry("public.ecr.aws/lambda/python:3.12-arm64"),
            command=[
                "bash", "-c",
                "cp -r /asset-input/. /asset-output/ && "
                "pip install -r /asset-output/requirements.txt -t /asset-output "
                "--platform manylinux2014_aarch64 --implementation cp "
                "--python-version 3.12 --only-binary=:all: --upgrade && "
                "find /asset-output -name __pycache__ -type d -prune -exec rm -rf {} + || true"
            ],
            local=LocalCollectorBundler(),
        )

        code_asset = lambda_.Code.from_asset(
            os.path.join(REPO_ROOT, "src"),
            bundling=bundling,
        )

        # 1. Collector Lambda
        collector_log = logs.LogGroup(
            self, "FrugalityCollectorLogGroup",
            log_group_name="/aws/lambda/cloud-frugality-collector",
            retention=logs.RetentionDays.THREE_DAYS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        collector = lambda_.Function(
            self, "FrugalityCollectorFunction",
            function_name="cloud-frugality-collector",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=code_asset,
            timeout=Duration.seconds(120),
            memory_size=256,
            log_group=collector_log,
            environment={
                "DB_HOST": cluster_endpoint,
                "DB_PORT": "5432",
                "DB_NAME": db_name,
                "DB_IAM_USER": db_iam_user,
                "AWS_REGION_NAME": self.region,
                "LOG_LEVEL": "INFO",
                "BURN_WINDOW_DAYS": "7",
                "ASSUMED_CREDIT_GRANT_USD": "200",
            },
            description="Cloud Frugality automated cost and resource collector (IAM DB auth).",
        )

        collector.add_to_role_policy(iam.PolicyStatement(
            sid="ConnectCollectorDbUser",
            actions=["rds-db:connect"],
            resources=[
                f"arn:aws:rds-db:{self.region}:{self.account}:dbuser:{cluster_resource_id}/{db_iam_user}"
            ],
        ))

        collector.add_to_role_policy(iam.PolicyStatement(
            sid="ReadBillingAndInventory",
            actions=[
                "ce:GetCostAndUsage",
                "ce:GetCostForecast",
                "ce:GetDimensionValues",
                "freetier:GetAccountPlanState",
                "freetier:GetFreeTierUsage",
                "tag:GetResources",
                "lambda:ListFunctions",
                "rds:DescribeDBClusters",
                "rds:DescribeDBInstances",
                "s3:ListAllMyBuckets",
            ],
            resources=["*"],
        ))

        # 2. Public Web Portal Lambda
        web_log = logs.LogGroup(
            self, "FrugalityWebLogGroup",
            log_group_name="/aws/lambda/cloud-frugality-web",
            retention=logs.RetentionDays.THREE_DAYS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        web = lambda_.Function(
            self, "FrugalityWebFunction",
            function_name="cloud-frugality-web",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="web.lambda_handler",
            code=code_asset,
            timeout=Duration.seconds(30),
            memory_size=256,
            log_group=web_log,
            reserved_concurrent_executions=5,
            environment={
                "DB_HOST": cluster_endpoint,
                "DB_PORT": "5432",
                "DB_NAME": db_name,
                "DB_READER_USER": db_reader_user,
                "AWS_REGION_NAME": self.region,
                "COST_WINDOW_DAYS": "30",
            },
            description="Cloud Frugality public web portal and JSON API (IAM DB auth).",
        )

        web.add_to_role_policy(iam.PolicyStatement(
            sid="ConnectReaderDbUser",
            actions=["rds-db:connect"],
            resources=[
                f"arn:aws:rds-db:{self.region}:{self.account}:dbuser:{cluster_resource_id}/{db_reader_user}"
            ],
        ))

        fn_url = web.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.GET],
            ),
        )

        # 3. Daily EventBridge Schedule
        sched_role = iam.Role(
            self, "FrugalityScheduleRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            description="Allows EventBridge Scheduler to trigger the Cloud Frugality collector.",
        )
        collector.grant_invoke(sched_role)

        scheduler.CfnSchedule(
            self, "FrugalityDailySchedule",
            schedule_expression="cron(0 6 * * ? *)",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="FLEXIBLE", maximum_window_in_minutes=60,
            ),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=collector.function_arn,
                role_arn=sched_role.role_arn,
                input='{"source":"scheduled"}',
            ),
            state="ENABLED",
        )

        # Stack Outputs
        CfnOutput(self, "CostWebUrl", value=fn_url.url, description="Cloud Frugality public web URL")
        CfnOutput(self, "CollectorFunctionName", value=collector.function_name)
        CfnOutput(self, "WebFunctionName", value=web.function_name)
        CfnOutput(self, "DbEndpoint", value=cluster_endpoint)
