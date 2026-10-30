from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from paper.models import Paper, QueryIndexTable


class PaperDiscoveryTests(APITestCase):
    def setUp(self):
        self.host, self.viewer = baker.make(get_user_model(), _quantity=2)
        self.theme = QueryIndexTable.objects.create(type='THEME', name='화이트')
        self.ratio = QueryIndexTable.objects.create(type='RATIO', name='가로')
        self.size = QueryIndexTable.objects.create(type='SIZE', name='A4', query={'max': 12})
        clock = patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 29, 9)))
        clock.start()
        self.addCleanup(clock.stop)

    def paper(self, **values):
        return Paper.objects.create(**{
            'hostFK': self.host, 'themeFK': self.theme, 'ratioFK': self.ratio,
            'sizeFK': self.size, 'title': '검색 검증', 'viewStat': True,
            'receivingDate': '2026-10-30', 'receivingStat': 0, **values,
        })

    def codes(self, params):
        response = self.client.get('/api/paper/user', params)
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        return [item['code'] for item in (data if isinstance(data, list) else data['results'])]

    def test_discovery_excludes_scheduled_early_delivered_private_and_blocked_papers(self):
        available = self.paper()
        self.paper(receivingDate='2026-10-28')
        self.paper(receivingStat=1)
        self.paper(viewStat=False, password='local-paper-test')
        blocked = self.paper()
        blocked.blockedUsers.add(self.viewer)
        self.client.force_authenticate(self.viewer)
        for params in ({'type': 'hot'}, {}):
            with self.subTest(params=params):
                self.assertEqual(self.codes(params), [str(available.code)])

    def test_same_day_discovery_closes_exactly_at_ten_am_korea_time(self):
        paper = self.paper(receivingDate='2026-10-29')
        for hour, minute, second, available in ((9, 59, 59, True), (10, 0, 0, False)):
            instant = timezone.make_aware(datetime(2026, 10, 29, hour, minute, second))
            with self.subTest(hour=hour), patch('paper.lifecycle.timezone.now', return_value=instant):
                self.assertEqual(self.codes({'type': 'hot'}), [str(paper.code)] if available else [])

    def test_hot_limit_applies_after_filtering_closed_papers(self):
        available = [self.paper() for _ in range(7)]
        for _ in range(6):
            self.paper(receivingStat=1)
        self.assertEqual(self.codes({'type': 'hot'}), [str(paper.code) for paper in reversed(available[-6:])])

    def test_empty_discovery_preserves_existing_response_shapes(self):
        self.paper(receivingStat=1)
        self.assertEqual(self.codes({'type': 'hot'}), [])
        self.assertEqual(self.client.get('/api/paper/user').status_code, 404)
