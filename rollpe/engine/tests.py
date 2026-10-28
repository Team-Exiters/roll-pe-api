from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from heart.models import Heart
from paper.models import Paper, QueryIndexTable


class SearchTests(APITestCase):
    def setUp(self):
        self.user, self.host = baker.make(get_user_model(), _quantity=2)
        self.client.force_authenticate(self.user)
        clock = patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 26, 9)))
        clock.start()
        self.addCleanup(clock.stop)
        self.theme = baker.make(QueryIndexTable, type='THEME', name='화이트')
        self.ratio = baker.make(QueryIndexTable, type='RATIO', name='가로')
        self.size = baker.make(QueryIndexTable, type='SIZE', name='A4', query={'max': 12})

    def paper(self, **kwargs):
        values = dict(hostFK=self.host, themeFK=self.theme, ratioFK=self.ratio, sizeFK=self.size,
                      title='생일 축하', receivingDate='2026-10-27', receivingStat=0)
        return Paper.objects.create(**{**values, **kwargs})

    def search(self, keyword='생일', **query):
        return self.client.get(reverse('paper_search_api'), {'k': keyword, **query})

    def test_missing_blank_and_oversized_keyword_returns_client_error(self):
        for query in ({}, {'k': ''}, {'k': '   '}, {'k': 'x' * 101}):
            self.assertEqual(self.client.get(reverse('paper_search_api'), query).status_code, 400)

    def test_search_requires_authentication_and_preserves_legacy_route_and_envelope(self):
        self.paper(title='hello world')
        for name in ('paper_search_api', 'search_api'):
            self.client.force_authenticate(None)
            self.assertEqual(self.client.get(reverse(name), {'k': 'hello'}).status_code, 401)
            self.client.force_authenticate(self.user)
            response = self.client.get(reverse(name), {'k': 'hello'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json()), {'status_code', 'message', 'code', 'link', 'data'})
            self.assertEqual(response.json()['data']['results'][0]['title'], 'hello world')

    def test_only_open_public_matches_are_discoverable_even_by_host_and_invited_user(self):
        visible = self.paper()
        private = self.paper(password='local-private-paper-test')
        private.invitingUser.add(self.user)
        self.paper(receivingStat=1)
        self.paper(receivingDate='2026-10-25')
        blocked = self.paper()
        blocked.blockedUsers.add(self.user, self.host)
        self.paper(title='다른 제목')
        for user in (self.user, self.host):
            self.client.force_authenticate(user)
            response = self.search('  생일  ')
            self.assertEqual(response.status_code, 200)
            data = response.json()['data']
            self.assertEqual(data['count'], 1)
            self.assertEqual([item['code'] for item in data['results']], [str(visible.code)])
        self.assertTrue(private.invitingUser.filter(pk=self.user.pk).exists())
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(private.code)}).status_code, 200)

    def test_search_closes_exactly_at_ten_am_korea_time(self):
        self.paper(receivingDate='2026-10-26')
        for hour, minute, second, count in ((9, 59, 59, 1), (10, 0, 0, 0)):
            with patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 26, hour, minute, second))):
                self.assertEqual(self.search().json()['data']['count'], count)

    def test_empty_results_are_successful_and_separate_from_invalid_pages(self):
        response = self.search('없는 제목')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], {'count': 0, 'next': None, 'previous': None, 'results': []})
        self.assertEqual(self.search(page=999).status_code, 404)

    def test_results_never_contain_memo_contents_participant_lists_or_passwords(self):
        paper = self.paper()
        writer = baker.make(get_user_model(), identifyCode='W12345')
        paper.invitingUser.add(writer)
        color = baker.make(QueryIndexTable, type='COLOR', name='F2EB28')
        Heart.objects.create(paperFK=paper, userFK=writer, colorFK=color, context='검색에 노출하면 안 되는 마음', location=0)
        item = self.search().json()['data']['results'][0]
        self.assertEqual(item['hearts'], {'count': 1})
        self.assertEqual(item['invitingUser'], [])
        self.assertNotIn('password', item)
        self.assertNotIn('검색에 노출하면 안 되는 마음', str(item))
        self.assertNotIn(str(writer.identifyCode), str(item))
        self.assertFalse(paper.invitingUser.filter(pk=self.user.pk).exists())

    def test_pagination_filters_before_counting_and_keeps_a_stable_order(self):
        for number in range(23):
            self.paper(title=f'생일 {number:02d}')
        self.paper(password='another-local-test')
        first = self.search().json()['data']
        second = self.search(page=2).json()['data']
        self.assertEqual(first['count'], 23)
        self.assertEqual(len(first['results']), 20)
        self.assertEqual(len(second['results']), 3)
        self.assertIsNotNone(first['next'])
        self.assertIsNone(second['next'])
        self.assertTrue(set(item['code'] for item in first['results']).isdisjoint(item['code'] for item in second['results']))

    def test_discovery_lists_hide_private_papers_but_host_and_invitation_lists_retain_them(self):
        public, private = self.paper(), self.paper(password='local-discovery-private-test')
        private.invitingUser.add(self.user)
        for user in (None, self.user, self.host):
            self.client.force_authenticate(user)
            for params in ({'type': 'hot'}, {}):
                response = self.client.get('/api/paper/user', params)
                data = response.json()['data']
                items = data if isinstance(data, list) else data['results']
                self.assertEqual([item['code'] for item in items], [str(public.code)])
        self.client.force_authenticate(self.user)
        data = self.client.get('/api/paper/mypage', {'type': 'inviting'}).json()['data']
        self.assertEqual([item['code'] for item in data['results']], [str(private.code)])
        self.client.force_authenticate(self.host)
        data = self.client.get('/api/paper/mypage', {'type': 'host'}).json()['data']
        self.assertIn(str(private.code), [item['code'] for item in data['results']])
