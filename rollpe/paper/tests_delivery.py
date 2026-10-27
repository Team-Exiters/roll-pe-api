from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from heart.models import Heart
from paper.models import Paper, QueryIndexTable


class PaperDeliveryTests(APITestCase):
    def setUp(self):
        self.host, self.writer, self.receiver, self.outsider = baker.make(get_user_model(), _quantity=4)
        self.paper = Paper.objects.create(
            hostFK=self.host, receiverFK=self.receiver,
            themeFK=QueryIndexTable.objects.create(type='THEME', name='화이트'),
            ratioFK=QueryIndexTable.objects.create(type='RATIO', name='가로'),
            sizeFK=QueryIndexTable.objects.create(type='SIZE', name='A4', query={'max': 12}),
            receivingDate='2026-10-29', title='조기 전달 검증', password='local-test-only',
        )
        self.paper.invitingUser.add(self.writer)
        self.color = QueryIndexTable.objects.create(type='COLOR', name='F2EB28')
        self.heart = Heart.objects.create(paperFK=self.paper, userFK=self.writer, colorFK=self.color,
                                          context='수신자에게 전달할 마음', location=0)
        self.route = reverse('paper_send_api')
        instant = timezone.make_aware(datetime(2026, 10, 26, 9))
        clock = patch('paper.lifecycle.timezone.now', return_value=instant)
        clock.start()
        self.addCleanup(clock.stop)
        self.client.force_authenticate(self.host)

    def send(self, **extra):
        return self.client.post(self.route, {'pcode': str(self.paper.code), **extra}, format='json')

    def received_codes(self):
        response = self.client.get('/api/paper/mypage', {'type': 'my'})
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        return [item['code'] for item in (data if isinstance(data, list) else data['results'])]

    def test_host_ends_writing_without_changing_receiver_date_password_or_memos(self):
        original_password = self.paper.password
        response = self.send(receiverFK=self.outsider.pk, receivingDate='2000-01-01')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], {'code': str(self.paper.code), 'receivingStat': 1})
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.receivingStat, 1)
        self.assertEqual(self.paper.receiverFK_id, self.receiver.pk)
        self.assertEqual(str(self.paper.receivingDate), '2026-10-29')
        self.assertEqual(self.paper.password, original_password)
        self.assertTrue(check_password('local-test-only', self.paper.password))
        self.assertTrue(Heart.objects.filter(pk=self.heart.pk).exists())
        self.assertTrue(self.paper.invitingUser.filter(pk=self.writer.pk).exists())
        self.assertFalse(self.paper.invitingUser.filter(pk=self.receiver.pk).exists())

    def test_only_host_may_send_even_when_other_users_are_invited(self):
        for user, status in ((self.writer, 470), (self.receiver, 471), (self.outsider, 471), (None, 401)):
            with self.subTest(user=user.pk if user else None):
                self.client.force_authenticate(user)
                self.assertEqual(self.send().status_code, status)
                self.paper.refresh_from_db()
                self.assertEqual(self.paper.receivingStat, 0)

    def test_missing_invalid_unknown_code_and_missing_or_inactive_receiver_are_rejected(self):
        for data in ({}, {'pcode': 'bad'}, {'pcode': ['bad']}):
            self.assertEqual(self.client.post(self.route, data, format='json').status_code, 400)
        self.assertEqual(self.client.post(self.route, {'pcode': '00000000-0000-4000-8000-000000000000'}, format='json').status_code, 404)
        get_user_model().objects.filter(pk=self.receiver.pk).update(is_active=False)
        self.assertEqual(self.send().status_code, 400)
        Paper.objects.filter(pk=self.paper.pk).update(receiverFK=None)
        self.assertEqual(self.send().status_code, 400)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.receivingStat, 0)

    def test_repeat_send_is_idempotent_and_preserves_first_completion(self):
        self.assertEqual(self.send().status_code, 200)
        self.paper.refresh_from_db()
        first_update = self.paper.updatedAt
        later = timezone.make_aware(datetime(2026, 10, 26, 12))
        with patch('paper.lifecycle.timezone.now', return_value=later):
            self.assertEqual(self.send().status_code, 200)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.updatedAt, first_update)
        self.assertEqual(Heart.objects.filter(paperFK=self.paper).count(), 1)

    def test_receiver_can_read_immediately_without_private_password_or_membership(self):
        self.client.force_authenticate(self.receiver)
        self.assertEqual(self.received_codes(), [])
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 471)
        self.client.force_authenticate(self.host)
        self.assertEqual(self.send().status_code, 200)
        self.client.force_authenticate(self.receiver)
        self.assertEqual(self.received_codes(), [str(self.paper.code)])
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 200)
        self.assertEqual(self.client.get('/api/heart', {'hcode': str(self.heart.code)}).status_code, 200)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.receiver.pk).exists())
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 471)
        self.assertEqual(self.client.get('/api/heart', {'hcode': str(self.heart.code)}).status_code, 471)

    def test_delivery_blocks_heart_mutations_and_paper_delete_before_scheduled_date(self):
        self.assertEqual(self.send().status_code, 200)
        self.client.force_authenticate(self.writer)
        body = {'paperFK': self.paper.pk, 'context': '전달 후 변경 시도', 'location': 0,
                'color': 'F2EB28', 'heartPK': self.heart.pk}
        self.assertEqual(self.client.post('/api/heart', body, format='json').status_code, 483)
        self.assertEqual(self.client.patch('/api/heart', body, format='json').status_code, 483)
        self.assertEqual(self.client.delete(f'/api/heart?hcode={self.heart.code}').status_code, 483)
        self.client.force_authenticate(self.host)
        self.assertEqual(self.client.delete('/api/paper/user', {'pcode': str(self.paper.code)}, format='json').status_code, 483)
        self.heart.refresh_from_db()
        self.assertEqual(self.heart.context, '수신자에게 전달할 마음')

    def test_scheduled_delivery_appears_in_received_list_at_ten_am_korea_time(self):
        Paper.objects.filter(pk=self.paper.pk).update(receivingDate='2026-10-26')
        self.client.force_authenticate(self.receiver)
        self.assertEqual(self.received_codes(), [])
        with timezone.override('UTC'), patch('paper.lifecycle.timezone.now', return_value=datetime.fromisoformat('2026-10-26T01:00:00+00:00')):
            self.assertEqual(self.received_codes(), [str(self.paper.code)])
            self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 200)
            self.assertEqual(self.client.get('/api/heart', {'hcode': str(self.heart.code)}).status_code, 200)

    def test_delivered_content_is_receiver_only_across_public_and_private_read_routes(self):
        for public in (False, True):
            Paper.objects.filter(pk=self.paper.pk).update(viewStat=public)
            for delivery in ({'receivingStat': 1, 'receivingDate': '2026-10-29'},
                             {'receivingStat': 0, 'receivingDate': '2026-10-25'}):
                Paper.objects.filter(pk=self.paper.pk).update(**delivery)
                for user in (self.host, self.writer, self.outsider):
                    self.client.force_authenticate(user)
                    for route, query in (('/api/paper', {'pcode': str(self.paper.code)}),
                                         ('/api/heart', {'pcode': str(self.paper.code)}),
                                         ('/api/heart', {'hcode': str(self.heart.code)}),
                                         ('/api/heart/revisions', {'hcode': str(self.heart.code)}),
                                         ('/api/paper/participants', {'pcode': str(self.paper.code)})):
                        response = self.client.get(route, query)
                        self.assertNotEqual(response.status_code, 200)
                        self.assertNotIn(self.heart.context, str(response.json()))
                    self.assertEqual(self.client.get('/api/heart/my').json()['data']['count'], 0)
                self.client.force_authenticate(self.receiver)
                for route, query in (('/api/paper', {'pcode': str(self.paper.code)}),
                                     ('/api/heart', {'hcode': str(self.heart.code)}),
                                     ('/api/heart', {'pcode': str(self.paper.code)})):
                    response = self.client.get(route, query)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(self.heart.context, str(response.json()))
        self.client.force_authenticate(self.host)
        history = self.client.get('/api/paper/mypage', {'type': 'host'}).json()['data']
        self.assertEqual(history['results'][0]['code'], str(self.paper.code))
        self.assertNotIn(self.heart.context, str(history))

    def test_receiver_who_is_also_host_or_author_keeps_receiver_access(self):
        for receiver in (self.host, self.writer):
            Paper.objects.filter(pk=self.paper.pk).update(receiverFK=receiver, receivingStat=1)
            self.client.force_authenticate(receiver)
            self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 200)
            self.assertEqual(self.client.get('/api/heart', {'hcode': str(self.heart.code)}).status_code, 200)
            self.assertEqual(self.client.get('/api/heart/my').json()['data']['count'], int(receiver == self.writer))

    def test_same_day_privacy_and_own_heart_list_switch_at_exactly_ten_am(self):
        Paper.objects.filter(pk=self.paper.pk).update(receivingDate='2026-10-26')
        for instant, delivered in ((datetime(2026, 10, 26, 9, 59, 59), False),
                                   (datetime(2026, 10, 26, 10), True)):
            with patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(instant)):
                for user in (self.host, self.writer):
                    self.client.force_authenticate(user)
                    self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 471 if delivered else 200)
                    self.assertEqual(self.client.get('/api/heart', {'hcode': str(self.heart.code)}).status_code, 471 if delivered else 200)
                self.assertEqual(self.client.get('/api/heart/my').json()['data']['count'], 0 if delivered else 1)
                self.client.force_authenticate(self.receiver)
                self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 200 if delivered else 471)
