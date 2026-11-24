from django.db import migrations, models


class Migration(migrations.Migration):
    """Add a dedicated "assignment" email preference and make other property changes opt-in.

    - Existing users get assignment=True and keep their current property_change value.
    - Only the default for NEW preference rows changes (property_change: True -> False).
    """

    dependencies = [
        ("db", "0131_report_definitions_and_project_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="usernotificationpreference",
            name="assignment",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="usernotificationpreference",
            name="property_change",
            field=models.BooleanField(default=False),
        ),
    ]
