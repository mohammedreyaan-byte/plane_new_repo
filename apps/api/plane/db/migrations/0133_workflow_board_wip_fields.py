from django.db import migrations, models


class Migration(migrations.Migration):
    """Add WIP settings used by workflow-aware boards.

    WIP is warn-only by default for existing projects; a workflow state gets a
    limit only when an admin sets one explicitly.
    """

    dependencies = [
        ("db", "0132_notification_assignment_preference"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="board_wip_hard_limit",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="workflowstate",
            name="wip_limit",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
