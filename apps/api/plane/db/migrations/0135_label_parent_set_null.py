from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Deleting a parent label promotes children to root labels (PLN-002)."""

    dependencies = [
        ("db", "0134_state_unique_default_per_project"),
    ]

    operations = [
        migrations.AlterField(
            model_name="label",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="parent_label",
                to="db.label",
            ),
        ),
    ]
