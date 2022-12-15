# Generated by Django 3.2.11 on 2022-12-15 08:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "django_aws_api_gateway_websockets",
            "0005_apigatewayadditionalroute_deployed",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="apigatewayadditionalroute",
            name="route_key",
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterUniqueTogether(
            name="apigatewayadditionalroute",
            unique_together={("api_gateway", "route_key")},
        ),
    ]