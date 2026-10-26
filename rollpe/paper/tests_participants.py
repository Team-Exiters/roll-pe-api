from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from heart.models import Heart, HeartRevision
from paper.models import Paper, QueryIndexTable


class PaperParticipantsFixture(APITestCase):
    def setUp(self):
        self.host, self.writer, self.other, self.receiver = baker.make(get_user_model(), _quantity=4)
        self.paper = Paper.objects.create(
            hostFK=self.host, receiverFK=self.receiver, title='참여자 관리 검증', receivingDate='2026-10-29',
            themeFK=QueryIndexTable.objects.create(type='THEME', name='화이트'),
            ratioFK=QueryIndexTable.objects.create(type='RATIO', name='가로'),
            sizeFK=QueryIndexTable.objects.create(type='SIZE', name='A4', query={'max': 12}), password='local-paper-test',
        )
        self.color = QueryIndexTable.objects.create(type='COLOR', name='F2EB28')
        self.paper.invitingUser.add(self.writer)
        self.client.force_authenticate(self.host)
        clock = patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 26, 9)))
        clock.start()
        self.addCleanup(clock.stop)

    def change(self, method, user=None):
        return getattr(self.client, method)('/api/paper/participants', {
            'pcode': str(self.paper.code), 'userId': (user or self.writer).pk,
        }, format='json')

    def write(self, user=None):
        self.client.force_authenticate(user or self.writer)
        return self.client.post('/api/heart', {'paperFK': self.paper.pk, 'context': '원래 마음', 'location': 0,
                                             'color': 'F2EB28'}, format='json')


class PaperParticipantsTests(PaperParticipantsFixture):
    def test_host_list_includes_non_writers_and_edited_state_but_not_passwords_or_history(self):
        self.assertEqual(self.write().status_code, 201)
        heart = Heart.objects.get()
        self.client.patch('/api/heart', {'paperFK': self.paper.pk, 'heartPK': heart.pk, 'context': '수정 마음',
                                       'location': 0, 'color': 'F2EB28'}, format='json')
        self.paper.invitingUser.add(self.other)
        self.client.force_authenticate(self.host)
        response = self.client.get('/api/paper/participants', {'pcode': str(self.paper.code)})
        users = {user['id']: user for user in response.json()['data']['users']}
        self.assertEqual(set(users), {self.host.pk, self.writer.pk, self.other.pk})
        self.assertEqual(users[self.writer.pk]['revisionCount'], 1)
        self.assertTrue(users[self.writer.pk]['hasWritten'])
        self.assertFalse(users[self.other.pk]['hasWritten'])
        self.assertTrue(users[self.host.pk]['isHost'])
        self.assertNotIn('수정 마음', str(response.json()))
        self.assertNotIn('password', str(response.json()))

    def test_only_host_can_list_invite_and_kick(self):
        for user in (self.writer, self.other, None):
            self.client.force_authenticate(user)
            expected = 401 if user is None else 403
            self.assertEqual(self.client.get('/api/paper/participants', {'pcode': str(self.paper.code)}).status_code, expected)
            self.assertEqual(self.change('post', self.other).status_code, expected)
            self.assertEqual(self.change('delete').status_code, expected)
        self.assertTrue(self.paper.invitingUser.filter(pk=self.writer.pk).exists())

    def test_invitation_is_idempotent_and_private_entry_needs_no_password(self):
        for _ in range(2):
            self.assertEqual(self.change('post', self.other).status_code, 204)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 471)
        self.assertEqual(self.client.post('/api/paper/enter', {'pcode': str(self.paper.code)}, format='json').status_code, 204)
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 200)
        self.paper.refresh_from_db()
        self.assertTrue(check_password('local-paper-test', self.paper.password))

    def test_leave_deletes_own_memo_and_all_revisions_without_banning_reentry(self):
        self.assertEqual(self.write().status_code, 201)
        heart = Heart.objects.get()
        self.assertTrue(HeartRevision.objects.filter(heartFK=heart).exists())
        for _ in range(2):
            self.assertEqual(self.client.post('/api/paper/leave', {'pcode': str(self.paper.code)}, format='json').status_code, 204)
        self.assertFalse(Heart.objects.filter(pk=heart.pk).exists())
        self.assertFalse(HeartRevision.objects.exists())
        self.assertFalse(self.paper.invitingUser.filter(pk=self.writer.pk).exists())
        self.assertFalse(self.paper.blockedUsers.filter(pk=self.writer.pk).exists())
        self.assertEqual(self.client.post('/api/paper/enter', {'pcode': str(self.paper.code), 'password': 'local-paper-test'}, format='json').status_code, 204)

    def test_kick_deletes_memo_and_history_and_blocks_all_reentry_and_reinvite(self):
        self.assertEqual(self.write().status_code, 201)
        self.client.force_authenticate(self.host)
        for _ in range(2):
            self.assertEqual(self.change('delete').status_code, 204)
        self.assertFalse(Heart.objects.exists())
        self.assertFalse(HeartRevision.objects.exists())
        self.assertFalse(self.paper.invitingUser.filter(pk=self.writer.pk).exists())
        self.assertTrue(self.paper.blockedUsers.filter(pk=self.writer.pk).exists())
        self.assertEqual(self.change('post').status_code, 403)
        self.client.force_authenticate(self.writer)
        for public in (False, True):
            Paper.objects.filter(pk=self.paper.pk).update(viewStat=public)
            self.assertEqual(self.client.post('/api/paper/enter', {'pcode': str(self.paper.code), 'password': 'local-paper-test'}, format='json').status_code, 403)
            self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 403)
            self.assertEqual(self.write().status_code, 403)
            self.assertEqual(self.client.get('/api/heart', {'pcode': str(self.paper.code)}).status_code, 471)
        self.assertFalse(self.client.get('/api/paper/user', {'type': 'hot'}).json()['data'])

    def test_host_and_receiver_are_protected_from_kicks_and_host_cannot_leave(self):
        self.paper.invitingUser.add(self.receiver)
        for user in (self.host, self.receiver):
            self.assertEqual(self.change('delete', user).status_code, 403)
        self.assertEqual(self.client.post('/api/paper/leave', {'pcode': str(self.paper.code)}, format='json').status_code, 403)
        self.assertFalse(self.paper.blockedUsers.exists())

    def test_kick_only_changes_the_target_and_the_specified_paper(self):
        self.assertEqual(self.write().status_code, 201)
        another = baker.make(Paper, hostFK=self.host)
        other_heart = Heart.objects.create(paperFK=another, userFK=self.writer, colorFK=self.color, context='다른 롤페', location=0)
        self.paper.invitingUser.add(self.other)
        self.client.force_authenticate(self.host)
        self.assertEqual(self.change('delete').status_code, 204)
        self.assertTrue(Heart.objects.filter(pk=other_heart.pk).exists())
        self.assertTrue(self.paper.invitingUser.filter(pk=self.other.pk).exists())
        self.assertFalse(another.blockedUsers.exists())

    def test_invalid_missing_and_inactive_targets_never_modify_membership(self):
        for body in ({}, {'pcode': 'bad'}, {'pcode': []}, {'pcode': str(self.paper.code), 'userId': -1}):
            self.assertEqual(self.client.post('/api/paper/participants', body, format='json').status_code, 400)
        self.assertEqual(self.change('delete', self.other).status_code, 404)
        get_user_model().objects.filter(pk=self.other.pk).update(is_active=False)
        self.assertEqual(self.change('post', self.other).status_code, 404)
        self.assertTrue(self.paper.invitingUser.filter(pk=self.writer.pk).exists())

    def test_scheduled_and_early_delivery_freeze_membership_and_preserve_memos(self):
        self.assertEqual(self.write().status_code, 201)
        for status, date in ((1, '2026-10-29'), (0, '2026-10-26')):
            Paper.objects.filter(pk=self.paper.pk).update(receivingStat=status, receivingDate=date)
            with patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 26, 10))):
                self.client.force_authenticate(self.host)
                self.assertEqual(self.change('post', self.other).status_code, 483)
                self.assertEqual(self.change('delete').status_code, 483)
                self.client.force_authenticate(self.writer)
                self.assertEqual(self.client.post('/api/paper/leave', {'pcode': str(self.paper.code)}, format='json').status_code, 483)
                self.client.force_authenticate(self.other)
                self.assertEqual(self.client.post('/api/paper/enter', {'pcode': str(self.paper.code), 'password': 'local-paper-test'}, format='json').status_code, 483)
        self.assertTrue(Heart.objects.exists())

    def test_failed_kick_rolls_back_memo_and_membership_deletion(self):
        self.assertEqual(self.write().status_code, 201)
        self.client.force_authenticate(self.host)
        manager_type = type(self.paper.blockedUsers)
        with patch.object(manager_type, 'add', side_effect=RuntimeError('local simulated failure')):
            with self.assertRaises(RuntimeError):
                self.change('delete')
        self.assertTrue(Heart.objects.exists())
        self.assertTrue(HeartRevision.objects.exists())
        self.assertTrue(self.paper.invitingUser.filter(pk=self.writer.pk).exists())

    def test_public_card_lists_do_not_disclose_memo_content_or_participant_lists(self):
        self.assertEqual(self.write().status_code, 201)
        Paper.objects.filter(pk=self.paper.pk).update(viewStat=True)
        self.client.force_authenticate(None)
        for params in ({'type': 'hot'}, {}):
            response = self.client.get('/api/paper/user', params)
            self.assertEqual(response.status_code, 200)
            data = response.json()['data']
            item = data[0] if isinstance(data, list) else data['results'][0]
            self.assertEqual(item['hearts'], {'count': 1})
            self.assertEqual(item['invitingUser'], [])
