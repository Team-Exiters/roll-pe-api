from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from paper.models import Paper, QueryIndexTable


class PaperInfoAccessTests(APITestCase):
    def setUp(self):
        self.host, self.writer, self.receiver, self.outsider = baker.make(get_user_model(), _quantity=4)
        self.paper = Paper.objects.create(
            hostFK=self.host, receiverFK=self.receiver,
            themeFK=QueryIndexTable.objects.create(type='THEME', name='화이트'),
            ratioFK=QueryIndexTable.objects.create(type='RATIO', name='가로'),
            sizeFK=QueryIndexTable.objects.create(type='SIZE', name='A4', query={'max': 12}),
            receivingDate='2026-10-25', title='정보 조회 테스트', password='test-only-paper-password',
        )
        self.paper.invitingUser.add(self.writer)
        self.url = reverse('paper_api') + f'?pcode={self.paper.code}'

    def read_as(self, user, hour, minute=0, second=0):
        self.client.force_authenticate(user=user)
        now = timezone.make_aware(datetime(2026, 10, 25, hour, minute, second))
        with patch('paper.apis.timezone.now', return_value=now):
            return self.client.get(self.url)

    def test_host_and_explicitly_invited_writer_do_not_need_a_private_paper_password(self):
        for user in (self.host, self.writer):
            response = self.read_as(user, 9)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['data']['code'], str(self.paper.code))
            self.assertNotIn('password', response.json()['data'])

    def test_uninvited_receiver_cannot_read_before_the_ten_am_deadline(self):
        self.assertEqual(self.read_as(self.receiver, 9, 59, 59).status_code, 471)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.receiver.pk).exists())

    def test_receiver_can_read_from_the_deadline_without_becoming_a_writer(self):
        for hour in (10, 11, 23):
            response = self.read_as(self.receiver, hour)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['data']['receive']['receiver']['id'], self.receiver.pk)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.receiver.pk).exists())

    def test_other_users_cannot_bypass_private_paper_access_before_or_after_delivery(self):
        for hour in (9, 10, 23):
            self.assertEqual(self.read_as(self.outsider, hour).status_code, 471)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.outsider.pk).exists())

    def test_anonymous_and_invalid_links_do_not_grant_membership(self):
        self.assertEqual(self.read_as(None, 10).status_code, 401)
        self.client.force_authenticate(user=self.outsider)
        self.assertEqual(self.client.get(reverse('paper_api'), {'pcode': 'bad-code'}).status_code, 400)

    def test_public_paper_requires_explicit_entry_and_can_be_entered_without_password(self):
        # Avoid Paper.save rehashing the existing private password when changing test visibility.
        Paper.objects.filter(pk=self.paper.pk).update(viewStat=True, password=None)
        self.assertEqual(self.read_as(self.outsider, 9).status_code, 471)
        with patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 25, 9))):
            response = self.client.post(reverse('paper_invite_api'), {'pcode': str(self.paper.code)}, format='json')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.read_as(self.outsider, 9).status_code, 200)
