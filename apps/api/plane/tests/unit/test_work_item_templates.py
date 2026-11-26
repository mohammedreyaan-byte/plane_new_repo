# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for work item template validation."""

from uuid import uuid4

import pytest
from rest_framework.exceptions import ValidationError

from plane.app.serializers import WorkItemTemplateSerializer

pytestmark = pytest.mark.unit


def test_template_serializer_accepts_supported_fields():
    label_id = str(uuid4())
    serializer = WorkItemTemplateSerializer(
        data={
            "name": "  Bug report  ",
            "description": "Pre-fill common fields",
            "template_data": {
                "title_template": "Bug: ",
                "description_template": "Steps to reproduce",
                "priority": "high",
                "label_ids": [label_id],
                "assignee_id": str(uuid4()),
                "type_id": str(uuid4()),
                "state_id": str(uuid4()),
                "module_id": str(uuid4()),
                "cycle_id": str(uuid4()),
            },
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["name"] == "Bug report"


@pytest.mark.parametrize(
    "template_data",
    [
        {"not_a_field": "value"},
        {"label_ids": ["not-a-uuid"]},
        {"priority": 42},
        {"assignee_id": "not-a-uuid"},
    ],
)
def test_template_serializer_rejects_invalid_template_data(template_data):
    serializer = WorkItemTemplateSerializer(data={"name": "Invalid", "template_data": template_data})
    with pytest.raises(ValidationError):
        serializer.is_valid(raise_exception=True)


def test_template_serializer_rejects_blank_name():
    serializer = WorkItemTemplateSerializer(data={"name": "   ", "template_data": {}})
    with pytest.raises(ValidationError):
        serializer.is_valid(raise_exception=True)
