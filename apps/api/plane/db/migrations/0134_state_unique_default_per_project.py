from django.db import migrations, models
from django.db.models import Q


def keep_one_default_state(apps, schema_editor):
    """Repair legacy rows before adding the partial unique constraint."""
    State = apps.get_model("db", "State")
    project_ids = (
        State.objects.filter(default=True, deleted_at__isnull=True)
        .values_list("project_id", flat=True)
        .distinct()
    )
    for project_id in project_ids:
        defaults = State.objects.filter(
            project_id=project_id,
            default=True,
            deleted_at__isnull=True,
        ).order_by("created_at", "id")
        keep = defaults.first()
        if keep is not None:
            defaults.exclude(pk=keep.pk).update(default=False)


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    """One active default state per project (PLN-002)."""

    dependencies = [
        ("db", "0133_workflow_board_wip_fields"),
    ]

    operations = [
        migrations.RunPython(keep_one_default_state, noop),
        migrations.AddConstraint(
            model_name="state",
            constraint=models.UniqueConstraint(
                fields=["project"],
                condition=Q(default=True, deleted_at__isnull=True),
                name="state_unique_default_per_project_when_active",
            ),
        ),
    ]
