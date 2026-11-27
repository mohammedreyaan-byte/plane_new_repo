# PLN-015: service token workspace/project scope, capabilities and revocation.

import uuid
from django.db import migrations, models
import django.contrib.postgres.fields


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0141_email_unsubscribe_tokens"),
    ]

    operations = [
        migrations.AddField(
            model_name="apitoken",
            name="token_hash",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="apitoken",
            name="token_prefix",
            field=models.CharField(db_index=True, default="", max_length=24),
        ),
        migrations.AddField(
            model_name="apitoken",
            name="projects",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.UUIDField(default=uuid.uuid4), blank=True, null=True, size=None
            ),
        ),
        migrations.AddField(
            model_name="apitoken",
            name="capabilities",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="apitoken",
            name="revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
