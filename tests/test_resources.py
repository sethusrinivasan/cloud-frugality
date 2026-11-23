"""
Unit tests for active resource inventory parsing and enrichment.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
sys.path.insert(0, SRC)

import resources


def test_parse_arn():
    svc, rtype = resources.parse_arn("arn:aws:lambda:us-east-2:123456789012:function:my-function")
    assert svc == "lambda"
    assert rtype == "function"

    svc_rds, rtype_rds = resources.parse_arn("arn:aws:rds:us-east-2:123456789012:cluster:my-cluster")
    assert svc_rds == "rds"
    assert rtype_rds == "cluster"


def test_sweep_resources():
    mock_tagging = MagicMock()
    mock_paginator = MagicMock()
    mock_tagging.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {
            "ResourceTagMappingList": [
                {
                    "ResourceARN": "arn:aws:lambda:us-east-2:123456789012:function:cloud-frugality-web",
                    "Tags": [
                        {"Key": "Frugality", "Value": "true"},
                        {"Key": "Project", "Value": "Frugality"},
                    ],
                }
            ]
        }
    ]

    res = resources.sweep_resources(mock_tagging)
    assert len(res) == 1
    arn = "arn:aws:lambda:us-east-2:123456789012:function:cloud-frugality-web"
    assert arn in res
    assert res[arn]["service"] == "lambda"
    assert res[arn]["resource_type"] == "function"
    assert "Frugality" in res[arn]["tags"]
