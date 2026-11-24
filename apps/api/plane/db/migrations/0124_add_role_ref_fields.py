# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db", "0123_add_role_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspacemember",
            name="role_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="db.role",
            ),
        ),
        migrations.AddField(
            model_name="workspacememberinvite",
            name="role_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="db.role",
            ),
        ),
        migrations.AddField(
            model_name="projectmember",
            name="role_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="db.role",
            ),
        ),
        migrations.AddField(
            model_name="projectmemberinvite",
            name="role_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="db.role",
            ),
        ),
    ]
