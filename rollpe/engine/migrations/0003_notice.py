# Split by feature from the unreleased inquiry/notice migration.

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('engine', '0002_inquiry'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('createdAt', models.DateTimeField(auto_now_add=True)),
                ('updatedAt', models.DateTimeField(auto_now=True)),
                ('title', models.CharField(max_length=100)),
                ('body', models.TextField(help_text='문단, 제목, 목록, 링크, 표 등 HTML로 작성합니다.', max_length=100000)),
                ('isPublished', models.BooleanField(default=False, verbose_name='게시 여부')),
                ('publishedAt', models.DateTimeField(default=django.utils.timezone.now, verbose_name='게시 일시')),
            ],
            options={
                'verbose_name': '공지사항',
                'verbose_name_plural': '공지사항',
                'ordering': ['-publishedAt', '-pk'],
            },
        )
    ]
