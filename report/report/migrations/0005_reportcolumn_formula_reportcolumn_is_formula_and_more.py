# Generated by Django 5.1.5 on 2025-02-02 09:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('report', '0004_reportsorting'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportcolumn',
            name='formula',
            field=models.TextField(blank=True, help_text="Python expression for field concatenation. Use field names in curly braces, e.g. {first_name} + ' ' + {last_name}", null=True),
        ),
        migrations.AddField(
            model_name='reportcolumn',
            name='is_formula',
            field=models.BooleanField(default=False, help_text='Whether this column is a formula-based field'),
        ),
        migrations.DeleteModel(
            name='ReportSorting',
        ),
    ]
