from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone


KOREA = ZoneInfo('Asia/Seoul')


def delivery_deadline(paper):
    return timezone.make_aware(datetime.combine(paper.receivingDate, time(hour=10)), KOREA)


def is_delivered(paper):
    return paper.receivingStat == 1 or timezone.now() >= delivery_deadline(paper)


def delivered_paper_filter(prefix=''):
    now = timezone.localtime(timezone.now(), KOREA)
    scheduled = Q(**{f'{prefix}receivingDate__lt': now.date()})
    if now.hour >= 10:
        scheduled |= Q(**{f'{prefix}receivingDate': now.date()})
    return Q(**{f'{prefix}receivingStat': 1}) | scheduled
