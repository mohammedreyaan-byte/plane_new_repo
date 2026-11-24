# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations

LEGACY_ID_TO_KEY = {
    20: "admin",
    15: "member",
    12: "developer",
    11: "qa",
    2: "viewer",
    5: "guest",
}

MEMBERSHIP_MODELS = [
    "WorkspaceMember",
    "WorkspaceMemberInvite",
    "ProjectMember",
    "ProjectMemberInvite",
]


def backfill_role_refs(apps, schema_editor):
    Role = apps.get_model("db", "Role")
    system_roles = {
        role.key: role
        for role in Role.objects.filter(workspace__isnull=True, key__in=LEGACY_ID_TO_KEY.values())
    }

    for model_name in MEMBERSHIP_MODELS:
        Model = apps.get_model("db", model_name)
        for legacy_id, key in LEGACY_ID_TO_KEY.items():
            role = system_roles.get(key)
            if role is None:
                continue
            Model.objects.filter(role=legacy_id, role_ref__isnull=True).update(role_ref=role)


def clear_role_refs(apps, schema_editor):
    for model_name in MEMBERSHIP_MODELS:
        Model = apps.get_model("db", model_name)
        Model.objects.filter(role_ref__isnull=False).update(role_ref=None)


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0125_seed_system_roles"),
    ]

    operations = [
        migrations.RunPython(backfill_role_refs, clear_role_refs),
    ]
