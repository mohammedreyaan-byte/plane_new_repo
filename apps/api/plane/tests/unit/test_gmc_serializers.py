# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Serializer tests for encrypted secrets and validation rules."""

import json

import pytest
from rest_framework.exceptions import ValidationError

from plane.app.serializers import AutomationRuleSerializer, ExternalAccountIntegrationSerializer, GmcImporterSerializer
from plane.db.models import APIToken, ExternalAccountIntegration, Importer, Project, ProjectMember
from plane.license.utils.encryption import encrypt_data

pytestmark = pytest.mark.unit


@pytest.fixture
def gmc_project(db, create_user, workspace):
    project = Project.objects.create(name="GMC Project", identifier="GMC", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(workspace=workspace, project=project, member=create_user, role=20)
    return project


def test_integration_serializer_never_exposes_tokens(gmc_project, workspace):
    integration = ExternalAccountIntegration.objects.create(
        workspace=workspace,
        provider="github",
        provider_account_id="12345",
        account_name="Company GitHub",
    )
    integration.set_access_token("super-secret-token")
    integration.set_webhook_secret("super-secret-webhook")
    integration.refresh_token = encrypt_data("super-secret-refresh")
    integration.save()

    integration.refresh_from_db()
    assert integration.access_token != "super-secret-token"
    assert integration.get_access_token() == "super-secret-token"
    assert integration.get_webhook_secret() == "super-secret-webhook"

    payload = json.dumps(ExternalAccountIntegrationSerializer(integration).data, default=str)
    assert "super-secret-token" not in payload
    assert "super-secret-webhook" not in payload
    assert "super-secret-refresh" not in payload
    assert "access_token" not in payload


def test_import_serializer_masks_encrypted_configuration(gmc_project, workspace, create_user):
    token = APIToken.objects.create(user=create_user, workspace=workspace, label="gmc-test")
    importer = Importer.objects.create(
        project=gmc_project,
        workspace=workspace,
        initiated_by=create_user,
        token=token,
        service="github",
        status="queued",
        config={
            "token": encrypt_data("ghp-secret"),
            "owner": encrypt_data("company"),
            "repo": encrypt_data("private-repo"),
        },
    )

    data = GmcImporterSerializer(importer).data
    assert data["config"]["token"] == "********"
    assert data["config"]["owner"] == "********"
    assert data["config"]["repo"] == "********"
    payload = json.dumps(data, default=str)
    assert "ghp-secret" not in payload


def test_automation_serializer_validates_conditions_and_actions():
    valid = AutomationRuleSerializer(
        data={
            "name": "Escalate high priority",
            "trigger": "created",
            "conditions": [{"field": "priority", "operator": "is", "value": "high"}],
            "actions": [{"type": "add_label", "value": "Escalated"}],
        }
    )
    assert valid.is_valid(), valid.errors

    invalid_condition = AutomationRuleSerializer(
        data={
            "name": "Bad",
            "trigger": "created",
            "conditions": [{"field": "password", "operator": "is", "value": "x"}],
            "actions": [],
        }
    )
    with pytest.raises(ValidationError):
        invalid_condition.is_valid(raise_exception=True)

    invalid_action = AutomationRuleSerializer(
        data={"name": "Bad", "trigger": "created", "conditions": [], "actions": [{"type": "delete_all", "value": "x"}]}
    )
    with pytest.raises(ValidationError):
        invalid_action.is_valid(raise_exception=True)
