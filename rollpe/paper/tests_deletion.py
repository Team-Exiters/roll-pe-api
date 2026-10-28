from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from heart.models import Heart
from paper.models import Paper, QueryIndexTable


class PaperDeletionTests(APITestCase):
    def setUp(self):
        self.host, self.writer, self.receiver, self.outsider = baker.make(get_user_model(), _quantity=4)
        self.theme = QueryIndexTable.objects.create(type='THEME', name='화이트')
        self.size = QueryIndexTable.objects.create(type='SIZE', name='A4', query={'max': 12})
        self.ratio = QueryIndexTable.objects.create(type='RATIO', name='가로')
        self.color = QueryIndexTable.objects.create(type='COLOR', name='F2EB28')
        self.paper = self.make_paper('삭제할 롤페')
        self.other_paper = self.make_paper('보존할 롤페')
        self.heart = self.make_heart(self.paper)
        self.other_heart = self.make_heart(self.other_paper)
        self.route = reverse('paper_api_for_user')
        self.client.force_authenticate(self.host)

    def make_paper(self, title, **kwargs):
        paper = Paper.objects.create(hostFK=self.host, receiverFK=self.receiver,
                                     themeFK=self.theme, sizeFK=self.size, ratioFK=self.ratio,
                                     title=title, receivingDate='2026-10-27',
                                     password='local-test-only', **kwargs)
        paper.invitingUser.add(self.host, self.writer, self.receiver)
        return paper

    def make_heart(self, paper):
        return Heart.objects.create(paperFK=paper, userFK=self.writer, colorFK=self.color,
                                    context='보존 범위 확인용 마음', location=0)

    def delete(self):
        instant = timezone.make_aware(datetime(2026, 10, 27, 9, 59, 59))
        with patch('paper.apis.timezone.now', return_value=instant):
            return self.client.delete(self.route, {'pcode': str(self.paper.code)}, format='json')

    def test_host_delete_removes_only_target_paper_memos_and_memberships(self):
        users = list(get_user_model().objects.values_list('pk', flat=True))
        catalog = list(QueryIndexTable.objects.values_list('pk', flat=True))
        response = self.delete()
        self.assertEqual((response.status_code, response.content), (204, b''))
        self.assertFalse(Paper.objects.filter(pk=self.paper.pk).exists())
        self.assertFalse(Heart.objects.filter(pk=self.heart.pk).exists())
        self.assertFalse(Paper.invitingUser.through.objects.filter(paper_id=self.paper.pk).exists())
        self.assertTrue(Paper.objects.filter(pk=self.other_paper.pk).exists())
        self.assertTrue(Heart.objects.filter(pk=self.other_heart.pk).exists())
        self.assertEqual(self.other_paper.invitingUser.count(), 3)
        self.assertEqual(list(get_user_model().objects.values_list('pk', flat=True)), users)
        self.assertEqual(list(QueryIndexTable.objects.values_list('pk', flat=True)), catalog)

    def test_deleted_paper_disappears_from_detail_lists_and_counts(self):
        self.assertEqual(self.delete().status_code, 204)
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 404)
        self.assertEqual(self.client.get('/api/heart', {'hcode': str(self.heart.code)}).status_code, 404)
        listing = self.client.get('/api/paper/mypage', {'type': 'host'}).json()['data']
        self.assertEqual([item['code'] for item in listing['results']], [str(self.other_paper.code)])
        summary = self.client.get('/api/paper/mypage', {'type': 'main'}).json()['data']
        self.assertEqual(summary['host'], 1)
        self.client.force_authenticate(self.writer)
        summary = self.client.get('/api/paper/mypage', {'type': 'main'}).json()['data']
        self.assertEqual(summary['heart'], 1)

    def test_repeated_delete_returns_not_found_without_affecting_other_paper(self):
        self.assertEqual(self.delete().status_code, 204)
        self.assertEqual(self.delete().status_code, 404)
        self.assertTrue(Paper.objects.filter(pk=self.other_paper.pk).exists())
        self.assertTrue(Heart.objects.filter(pk=self.other_heart.pk).exists())

    def test_writer_receiver_outsider_and_anonymous_cannot_delete(self):
        for user, expected in ((self.writer, 470), (self.receiver, 470), (self.outsider, 471), (None, 401)):
            with self.subTest(user=user.pk if user else None):
                self.client.force_authenticate(user)
                self.assertEqual(self.delete().status_code, expected)
                self.assertTrue(Paper.objects.filter(pk=self.paper.pk).exists())
                self.assertTrue(Heart.objects.filter(pk=self.heart.pk).exists())
                self.assertEqual(self.paper.invitingUser.count(), 3)

    def test_delivery_deadline_blocks_delete_at_exactly_ten_am(self):
        for hour, minute, second in ((10, 0, 0), (23, 59, 59)):
            instant = timezone.make_aware(datetime(2026, 10, 27, hour, minute, second))
            with patch('paper.apis.timezone.now', return_value=instant):
                response = self.client.delete(self.route, {'pcode': str(self.paper.code)}, format='json')
            self.assertEqual(response.status_code, 483)
            self.assertTrue(Paper.objects.filter(pk=self.paper.pk).exists())
            self.assertTrue(Heart.objects.filter(pk=self.heart.pk).exists())
            self.assertEqual(self.paper.invitingUser.count(), 3)

    def test_already_delivered_paper_is_preserved_even_before_its_date(self):
        Paper.objects.filter(pk=self.paper.pk).update(receivingStat=1)
        self.assertEqual(self.delete().status_code, 483)
        self.assertTrue(Heart.objects.filter(pk=self.heart.pk).exists())

    def test_host_may_delete_public_paper_without_membership_before_delivery(self):
        Paper.objects.filter(pk=self.paper.pk).update(password=None, viewStat=True)
        self.paper.invitingUser.clear()
        self.assertEqual(self.delete().status_code, 204)
        self.assertFalse(Paper.objects.filter(pk=self.paper.pk).exists())
