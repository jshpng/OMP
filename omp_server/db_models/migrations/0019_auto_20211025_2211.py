# Generated by Django 3.1.4 on 2021-10-25 22:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('db_models', '0018_inspectionreport_file_name'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='inspectionreport',
            name='tag_error_num',
        ),
        migrations.RemoveField(
            model_name='inspectionreport',
            name='tag_total_num',
        ),
        migrations.AddField(
            model_name='inspectionreport',
            name='scan_info',
            field=models.JSONField(blank=True, help_text='扫描统计', null=True),
        ),
        migrations.AddField(
            model_name='inspectionreport',
            name='scan_result',
            field=models.JSONField(blank=True, help_text='分析结果', null=True),
        ),
        migrations.AlterField(
            model_name='inspectionhistory',
            name='hosts',
            field=models.JSONField(blank=True, help_text="巡检主机:['10.0.9.158']", null=True),
        ),
        migrations.AlterField(
            model_name='inspectionhistory',
            name='services',
            field=models.JSONField(blank=True, help_text='巡检组件: [8,9]', null=True),
        ),
    ]