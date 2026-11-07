# Split by feature from the unreleased inquiry/notice migration.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('engine', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Inquiry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('createdAt', models.DateTimeField(auto_now_add=True)),
                ('updatedAt', models.DateTimeField(auto_now=True)),
                ('requestId', models.UUIDField(editable=False)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('category', models.CharField(choices=[('bug', '버그 제보'), ('suggestion', '건의사항'), ('other', '기타 문의사항')], max_length=10)),
                ('content', models.TextField(max_length=2000)),
                ('status', models.CharField(choices=[('pending', '접수'), ('completed', '처리 완료')], default='pending', max_length=10)),
                ('staffNote', models.TextField(blank=True)),
                ('userFK', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='inquiries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': '1:1 문의',
                'verbose_name_plural': '1:1 문의',
                'ordering': ['-createdAt', '-pk'],
                'constraints': [models.UniqueConstraint(fields=('userFK', 'requestId'), name='unique_user_inquiry_request')],
            },
        )
    ]
