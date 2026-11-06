from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from model_bakery import baker

from heart.models import Heart, HeartRevision
from paper.models import Paper, PaperInvitation
from paper.tests_participants import PaperParticipantsFixture
from user.account import remove_account
from user.models import UserBlock


class UserBlockingTests(PaperParticipantsFixture):
    def block(self, target=None, method='post'):
        return getattr(self.client, method)('/api/user/blocks', {'userId': (target or self.writer).pk}, format='json')

    def test_authenticated_private_list_and_idempotent_block_unblock(self):
        self.assertEqual(self.block().status_code, 204)
        self.assertEqual(self.block().status_code, 204)
        self.assertEqual(UserBlock.objects.count(), 1)
        data = self.client.get('/api/user/blocks').json()['data']
        self.assertEqual([item['id'] for item in data['results']], [self.writer.pk])
        self.assertNotIn('email', str(data))
        self.assertNotIn('password', str(data))
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/user/blocks').json()['data']['count'], 0)
        self.assertEqual(self.block(method='delete').status_code, 204)
        self.assertEqual(UserBlock.objects.count(), 1)
        self.client.force_authenticate(self.host)
        for _ in range(2):
            self.assertEqual(self.block(method='delete').status_code, 204)
        self.assertFalse(UserBlock.objects.exists())
        self.client.force_authenticate(None)
        for method in ('get', 'post', 'delete'):
            self.assertEqual(getattr(self.client, method)('/api/user/blocks').status_code, 401)

    def test_invalid_self_missing_and_inactive_targets_do_not_create_blocks(self):
        for body in ({}, [], {'userId': True}, {'userId': -1}, {'userId': []}, {'userId': self.host.pk}):
            self.assertEqual(self.client.post('/api/user/blocks', body, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/user/blocks', {'userId': 999999}, format='json').status_code, 404)
        get_user_model().objects.filter(pk=self.writer.pk).update(is_active=False)
        self.assertEqual(self.block().status_code, 404)
        self.assertFalse(UserBlock.objects.exists())
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserBlock.objects.create(blocker=self.host, blocked=self.host)

    def test_redaction_preserves_slot_but_never_sends_blocked_content_or_history(self):
        self.assertEqual(self.write().status_code, 201)
        heart = Heart.objects.get()
        self.client.patch('/api/heart', {'paperFK': self.paper.pk, 'heartPK': heart.pk, 'context': '비공개 수정 내용',
                                        'location': 0, 'color': 'F2EB28'}, format='json')
        self.client.force_authenticate(self.host)
        self.assertEqual(self.block().status_code, 204)
        for path, params in (('/api/paper', {'pcode': str(self.paper.code)}),
                             ('/api/heart', {'pcode': str(self.paper.code)})):
            response = self.client.get(path, params)
            self.assertEqual(response.status_code, 200)
            data = response.json()['data']
            memo = data['hearts']['data'][0] if path == '/api/paper' else data['results'][0]
            self.assertTrue(memo['hidden'])
            self.assertEqual(memo['index'], 0)
            self.assertEqual(memo['content'], '')
            self.assertEqual(memo['revisionCount'], 0)
            self.assertNotIn('비공개 수정 내용', str(data))
            self.assertNotIn(self.writer.name, str(data))
        for path in ('/api/heart', '/api/heart/revisions'):
            self.assertEqual(self.client.get(path, {'hcode': str(heart.code)}).status_code, 403)
        self.assertEqual(Heart.objects.count(), 1)
        self.assertEqual(HeartRevision.objects.count(), 2)
        self.assertEqual(self.block(method='delete').status_code, 204)
        self.assertEqual(self.client.get('/api/heart/revisions', {'hcode': str(heart.code)}).status_code, 200)
        data = self.client.get('/api/paper', {'pcode': str(self.paper.code)}).json()['data']
        self.assertEqual(data['hearts']['data'][0]['content'], '비공개 수정 내용')
        self.assertNotIn('hidden', data['hearts']['data'][0])

    def test_block_is_personal_and_does_not_kick_or_hide_content_from_other_viewers(self):
        self.assertEqual(self.write().status_code, 201)
        self.client.force_authenticate(self.host)
        self.block()
        self.assertTrue(self.paper.invitingUser.filter(pk=self.writer.pk).exists())
        self.assertFalse(self.paper.blockedUsers.exists())
        self.paper.invitingUser.add(self.other)
        self.client.force_authenticate(self.other)
        response = self.client.get('/api/paper', {'pcode': str(self.paper.code)})
        self.assertEqual(response.json()['data']['hearts']['data'][0]['content'], '원래 마음')

    def test_blocked_hosts_are_hidden_in_discovery_search_personal_and_legacy_lists(self):
        Paper.objects.filter(pk=self.paper.pk).update(viewStat=True)
        self.paper.invitingUser.add(self.receiver)
        self.client.force_authenticate(self.receiver)
        self.block(self.host)
        self.assertEqual(self.client.get('/api/paper/user', {'type': 'hot'}).json()['data'], [])
        self.assertEqual(self.client.get('/api/engine/search', {'k': self.paper.title}).json()['data']['count'], 0)
        self.assertEqual(self.client.get('/api/paper/mypage', {'type': 'participating'}).json()['data']['count'], 0)
        self.assertEqual(self.client.get('/api/user/papers/inviting-user/').json()['data']['count'], 0)
        self.assertEqual(self.client.get('/api/user/papers/receiver/').json()['data']['count'], 0)
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 403)
        self.assertEqual(self.client.post('/api/paper/enter', {'pcode': str(self.paper.code)}, format='json').status_code, 403)
        Paper.objects.filter(pk=self.paper.pk).update(receivingStat=1)
        self.assertEqual(self.client.get('/api/paper/mypage', {'type': 'my'}).json()['data'], [])
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 403)

    def test_block_cancels_pending_invites_in_both_directions_and_unblock_does_not_resurrect_them(self):
        invitation = PaperInvitation.objects.create(paper=self.paper, user=self.other)
        other_paper = baker.make(Paper, hostFK=self.other, receiverFK=self.host)
        reverse = PaperInvitation.objects.create(paper=other_paper, user=self.host)
        self.assertEqual(self.block(self.other).status_code, 204)
        for item in (invitation, reverse):
            item.refresh_from_db()
            self.assertEqual(item.status, PaperInvitation.Status.DENIED)
        self.assertEqual(self.change('post', self.other).status_code, 403)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/paper/invitations').json()['data']['count'], 0)
        response = self.client.post('/api/paper/invitations', {'invitationCode': str(invitation.code), 'action': 'accept'}, format='json')
        self.assertIn(response.status_code, (403, 409))
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())
        self.client.force_authenticate(self.host)
        self.block(self.other, method='delete')
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, PaperInvitation.Status.DENIED)
        self.assertEqual(self.change('post', self.other).status_code, 204)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, PaperInvitation.Status.PENDING)
        self.assertNotEqual(invitation.code, reverse.code)

    def test_existing_or_legacy_pending_invitation_cannot_bypass_block(self):
        invitation = PaperInvitation.objects.create(paper=self.paper, user=self.other)
        UserBlock.objects.create(blocker=self.other, blocked=self.host)
        self.client.force_authenticate(self.other)
        response = self.client.post('/api/paper/invitations', {'invitationCode': str(invitation.code), 'action': 'accept'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post('/api/paper/enter', {'pcode': str(self.paper.code)}, format='json').status_code, 403)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())

    def test_invite_and_user_search_respect_either_direction(self):
        self.block(self.other)
        self.assertEqual(self.change('post', self.other).status_code, 403)
        response = self.client.get('/api/user/search-user/', {'nameCode': self.other.name})
        self.assertEqual(response.status_code, 404)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/user/search-user/', {'nameCode': self.host.name}).status_code, 404)
        self.client.force_authenticate(self.host)
        self.block(self.other, method='delete')
        self.assertEqual(self.client.get('/api/user/search-user/', {'nameCode': self.other.name}).status_code, 200)

    def test_block_prevents_new_delivery_without_removing_host_record(self):
        self.block(self.receiver)
        self.assertEqual(self.client.post('/api/paper/send', {'pcode': str(self.paper.code)}, format='json').status_code, 403)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.receivingStat, 0)
        self.assertEqual(self.client.get('/api/paper/mypage', {'type': 'host'}).json()['data']['count'], 1)
        body = {'receiverFK': self.receiver.pk, 'receivingDate': '2026-10-29', 'title': '제한 검증',
                'themeFK': self.paper.themeFK_id, 'sizeFK': self.paper.sizeFK_id, 'ratioFK': self.paper.ratioFK_id,
                'viewStat': True}
        for path in ('/api/paper', '/api/paper/user'):
            self.assertEqual(self.client.post(path, body, format='json').status_code, 400)
        self.block(self.receiver, method='delete')
        self.assertEqual(self.client.post('/api/paper/send', {'pcode': str(self.paper.code)}, format='json').status_code, 200)

    def test_deactivated_author_remains_hidden_and_outgoing_preferences_are_erased_on_withdrawal(self):
        self.write()
        self.client.force_authenticate(self.host)
        self.block()
        UserBlock.objects.create(blocker=self.writer, blocked=self.other)
        remove_account(self.writer)
        self.assertTrue(UserBlock.objects.filter(blocker=self.host, blocked=self.writer).exists())
        self.assertFalse(UserBlock.objects.filter(blocker=self.writer).exists())
        blocked = self.client.get('/api/user/blocks').json()['data']['results']
        self.assertEqual(blocked[0]['name'], '탈퇴한 사용자')
        data = self.client.get('/api/paper', {'pcode': str(self.paper.code)}).json()['data']
        self.assertTrue(data['hearts']['data'][0]['hidden'])
        self.assertEqual(self.block(method='delete').status_code, 204)
