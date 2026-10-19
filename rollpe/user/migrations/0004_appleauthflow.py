from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    dependencies = [('user', '0003_user_provider')]

    operations = [
        migrations.CreateModel(
            name='AppleAuthFlow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('state_hash', models.CharField(max_length=64, unique=True)),
                ('nonce', models.CharField(max_length=64)),
                ('client_state', models.CharField(max_length=64)),
                ('code_challenge', models.CharField(max_length=43)),
                ('return_url', models.CharField(max_length=512)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('status', models.CharField(default='pending', max_length=16)),
                ('exchange_hash', models.CharField(max_length=64, null=True, unique=True)),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
