#!/usr/bin/env python3
"""
CDK application entry point for Cloud Frugality.
"""
import os
import aws_cdk as cdk
from frugality_stack import CloudFrugalityStack

app = cdk.App()

# Mandatory tagging: All resources must carry the "Frugality" tag
cdk.Tags.of(app).add("Frugality", "true")
cdk.Tags.of(app).add("Project", "Frugality")
cdk.Tags.of(app).add("ApplicationName", "CloudFrugality")

account = os.environ.get("CDK_DEFAULT_ACCOUNT", "596090776030")
region = os.environ.get("CDK_DEFAULT_REGION", "us-east-2")
env = cdk.Environment(account=account, region=region)

CloudFrugalityStack(
    app,
    "CloudFrugalityStack",
    env=env,
    description="Dedicated Cloud Frugality cost, credit, and resource tracking service.",
)

app.synth()
