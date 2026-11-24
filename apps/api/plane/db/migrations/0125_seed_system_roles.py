# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations

ADMIN_CAPABILITIES = [
    "workspace.manage",
    "member.manage",
    "project.manage",
    "project.create",
    "type.manage",
    "workflow.manage",
    "integration.manage",
    "service_token.manage",
    "report.manage",
    "report.view",
    "report.export",
    "work_item.view",
    "work_item.create",
    "work_item.edit",
    "work_item.delete",
    "work_item.assign",
    "work_item.transition",
    "comment.create",
    "comment.delete",
    "attachment.create",
    "view.manage",
    "cycle.manage",
    "module.manage",
    "notification.manage",
    "webhook.manage",
]

MEMBER_CAPABILITIES = [
    capability
    for capability in ADMIN_CAPABILITIES
    if capability
    not in [
        "member.manage",
        "type.manage",
        "workflow.manage",
        "integration.manage",
        "service_token.manage",
        "notification.manage",
    ]
]

DEVELOPER_CAPABILITIES = [
    "work_item.view",
    "work_item.create",
    "work_item.edit",
    "work_item.assign",
    "work_item.transition",
    "comment.create",
    "attachment.create",
    "view.manage",
    "report.view",
    "report.export",
]

QA_CAPABILITIES = list(DEVELOPER_CAPABILITIES)

VIEWER_CAPABILITIES = [
    "work_item.view",
    "comment.read",
    "report.view",
]

GUEST_CAPABILITIES = [
    "work_item.view",
    "work_item.edit",
    "comment.create",
]

SYSTEM_ROLES = [
    {
        "key": "admin",
        "name": "Admin",
        "description": "Full workspace and project control.",
        "legacy_id": 20,
        "level": 60,
        "capabilities": ADMIN_CAPABILITIES,
    },
    {
        "key": "member",
        "name": "Member",
        "description": "Legacy full contributor role kept for compatibility.",
        "legacy_id": 15,
        "level": 50,
        "capabilities": MEMBER_CAPABILITIES,
    },
    {
        "key": "developer",
        "name": "Developer",
        "description": "Builds and edits work items. Cannot manage workspace settings.",
        "legacy_id": 12,
        "level": 40,
        "capabilities": DEVELOPER_CAPABILITIES,
    },
    {
        "key": "qa",
        "name": "QA",
        "description": "Tests and closes verified work.",
        "legacy_id": 11,
        "level": 30,
        "capabilities": QA_CAPABILITIES,
    },
    {
        "key": "viewer",
        "name": "Viewer",
        "description": "Read-only access to work items and reports.",
        "legacy_id": 2,
        "level": 20,
        "capabilities": VIEWER_CAPABILITIES,
    },
    {
        "key": "guest",
        "name": "Guest",
        "description": "Limited access, restricted to their own items.",
        "legacy_id": 5,
        "level": 10,
        "capabilities": GUEST_CAPABILITIES,
    },
]


def seed_system_roles(apps, schema_editor):
    Role = apps.get_model("db", "Role")
    for role in SYSTEM_ROLES:
        Role.objects.update_or_create(
            workspace=None,
            key=role["key"],
            defaults={
                "name": role["name"],
                "description": role["description"],
                "legacy_id": role["legacy_id"],
                "level": role["level"],
                "capabilities": role["capabilities"],
                "is_system": True,
                "is_active": True,
            },
        )


def remove_system_roles(apps, schema_editor):
    Role = apps.get_model("db", "Role")
    Role.objects.filter(workspace__isnull=True, is_system=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0124_add_role_ref_fields"),
    ]

    operations = [
        migrations.RunPython(seed_system_roles, remove_system_roles),
    ]
