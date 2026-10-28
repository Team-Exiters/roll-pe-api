from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from heart.models import Heart
from paper.models import Paper, QueryIndexTable


class PaperSettingsTests(APITestCase):
    def setUp(self):
        self.host, self.writer, self.receiver = baker.make(get_user_model(), _quantity=3)
        self.paper = Paper.objects.create(
            hostFK=self.host, receiverFK=self.receiver, title='설정 수정 테스트', receivingDate='2026-10-29',
            themeFK=baker.make(QueryIndexTable, type='THEME', name='화이트'),
            ratioFK=baker.make(QueryIndexTable, type='RATIO', name='가로'),
            sizeFK=baker.make(QueryIndexTable, type='SIZE', name='A4', query={'max': 12}),
            password='local-paper-settings-only',
        )
        self.paper.invitingUser.add(self.writer)
        self.heart = Heart.objects.create(paperFK=self.paper, userFK=self.writer,
                                         colorFK=baker.make(QueryIndexTable, type='COLOR', name='F2EB28'),
                                         context='보존되는 마음', location=0)
        clock = patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 27, 9)))
        clock.start()
        self.addCleanup(clock.stop)
        self.client.force_authenticate(self.host)

    def change(self, **settings):
        return self.client.patch('/api/paper', {'pcode': str(self.paper.code), **settings}, format='json')

    def test_only_host_can_change_settings_and_closed_papers_cannot_be_reopened(self):
        for user, expected in ((self.writer, 403), (self.receiver, 403), (None, 401)):
            self.client.force_authenticate(user)
            self.assertEqual(self.change(viewStat=True).status_code, expected)
        self.client.force_authenticate(self.host)
        for changes in ({'receivingStat': 1}, {'receivingDate': '2026-10-26'}):
            Paper.objects.filter(pk=self.paper.pk).update(**changes)
            self.assertEqual(self.change(receivingDate='2026-11-01').status_code, 483)
            Paper.objects.filter(pk=self.paper.pk).update(receivingStat=0, receivingDate='2026-10-29')
        Paper.objects.filter(pk=self.paper.pk).update(receivingDate='2026-10-27')
        with patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 27, 10))):
            self.assertEqual(self.change(receivingDate='2026-11-01').status_code, 483)

    def test_date_only_change_preserves_password_membership_receiver_and_hearts(self):
        original_hash = self.paper.password
        response = self.change(receivingDate='2026-11-01')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], {'code': str(self.paper.code), 'viewStat': False, 'receivingDate': '2026-11-01'})
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.password, original_hash)
        self.assertEqual(self.paper.receiverFK_id, self.receiver.pk)
        self.assertTrue(self.paper.invitingUser.filter(pk=self.writer.pk).exists())
        self.assertTrue(Heart.objects.filter(pk=self.heart.pk).exists())

    def test_public_and_private_transitions_hash_new_password_once_and_update_search(self):
        self.assertEqual(self.change(viewStat=True).status_code, 200)
        self.paper.refresh_from_db()
        self.assertIsNone(self.paper.password)
        self.assertTrue(self.paper.viewStat)
        self.assertIn(str(self.paper.code), str(self.client.get('/api/paper/user', {'type': 'hot'}).json()['data']))
        self.assertEqual(self.change(viewStat=False).status_code, 400)
        self.assertEqual(self.change(viewStat=False, password='new-local-paper-key').status_code, 200)
        self.paper.refresh_from_db()
        self.assertFalse(self.paper.viewStat)
        self.assertTrue(check_password('new-local-paper-key', self.paper.password))
        self.assertNotIn(str(self.paper.code), str(self.client.get('/api/paper/user', {'type': 'hot'}).json()['data']))
        self.assertNotIn('password', self.change(password='new-local-paper-key').json()['data'])
        self.assertEqual(self.change(password='changed-local-paper-key').status_code, 200)
        self.paper.refresh_from_db()
        self.assertTrue(check_password('changed-local-paper-key', self.paper.password))

    def test_invalid_fields_bodies_and_dates_never_partially_update_settings(self):
        original_hash = self.paper.password
        for values in ({}, {'hostFK': self.writer.pk}, {'receiverFK': self.writer.pk}, {'receivingStat': 1},
                       {'viewStat': 'false'}, {'password': 1234}, {'password': ' '}, {'password': 'x' * 51},
                       {'viewStat': True, 'password': 'conflicting-key'}, {'receivingDate': '2026-02-30'},
                       {'receivingDate': '2026-10-26'}, {'receivingDate': '2026-10-27'}, {'receivingDate': '2026-11-27'},
                       {'viewStat': True, 'receivingDate': 'bad'}):
            with self.subTest(values=values):
                self.assertEqual(self.change(**values).status_code, 400)
                self.paper.refresh_from_db()
                self.assertEqual(self.paper.password, original_hash)
                self.assertFalse(self.paper.viewStat)
                self.assertEqual(str(self.paper.receivingDate), '2026-10-29')
        for body in ([], {}, {'pcode': 'bad'}, {'pcode': ['bad']}):
            self.assertEqual(self.client.patch('/api/paper', body, format='json').status_code, 400)

    def test_unchanged_same_day_delivery_can_keep_password_and_date_updates_use_korean_dates(self):
        Paper.objects.filter(pk=self.paper.pk).update(receivingDate='2026-10-27')
        self.assertEqual(self.change(viewStat=False, password='', receivingDate='2026-10-27').status_code, 200)
        with timezone.override('UTC'), patch('paper.lifecycle.timezone.now', return_value=datetime.fromisoformat('2026-10-27T16:00:00+00:00')):
            Paper.objects.filter(pk=self.paper.pk).update(receivingDate='2026-11-01')
            self.assertEqual(self.change(receivingDate='2026-10-28').status_code, 400)
            self.assertEqual(self.change(receivingDate='2026-10-29').status_code, 200)
