"""Bounded housekeeping for expired temporary browser authorization state."""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from user.models import AppleAuthFlow, SocialAuthFlow


class Command(BaseCommand):
    help = 'Preview expired browser flows; --apply deletes at most --limit rows per model.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Delete the previewed expired rows.')
        parser.add_argument('--limit', type=int, default=1000)
        parser.add_argument('--older-than-hours', type=int, default=24,
                            help='Retention after expiry (minimum 1 hour; default 24).')

    def handle(self, *args, **options):
        limit = options['limit']
        retention = options['older_than_hours']
        if not 1 <= limit <= 10000:
            raise CommandError('--limit must be between 1 and 10000.')
        if retention < 1:
            raise CommandError('--older-than-hours must be at least 1.')
        try:
            cutoff = timezone.now() - timedelta(hours=retention)
        except OverflowError:
            raise CommandError('--older-than-hours is too large.')
        for model in (AppleAuthFlow, SocialAuthFlow):
            expired = model.objects.filter(expires_at__lt=cutoff)
            ids = list(expired.order_by('expires_at', 'pk').values_list('pk', flat=True)[:limit])
            if options['apply']:
                # Recheck expiry to preserve a flow completed since selection.
                count, _ = model.objects.filter(pk__in=ids, expires_at__lt=cutoff).delete()
                action = 'deleted'
            else:
                count = len(ids)
                action = 'would delete'
            self.stdout.write(f'{model.__name__}: {action} {count} (limit {limit})')
