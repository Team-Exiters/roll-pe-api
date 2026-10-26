from datetime import datetime
from unittest.mock import patch

from django.utils import timezone
from model_bakery import baker

from paper.models import Paper, PaperInvitation
from paper.tests_participants import PaperParticipantsFixture


class PaperInvitationsTests(PaperParticipantsFixture):
    def invite(self):
        self.client.force_authenticate(self.host)
        self.assertEqual(self.change('post', self.other).status_code, 204)
        return PaperInvitation.objects.get(paper=self.paper, user=self.other)

    def reply(self, invitation, action='accept'):
        return self.client.post('/api/paper/invitations', {
            'invitationCode': str(invitation.code), 'action': action,
        }, format='json')

    def listing(self):
        response = self.client.get('/api/paper/invitations')
        self.assertEqual(response.status_code, 200)
        return response.json()['data']

    def test_inviting_creates_only_one_pending_record_and_never_grants_membership(self):
        invitation = self.invite()
        self.change('post', self.other)
        self.assertEqual(PaperInvitation.objects.count(), 1)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())
        self.client.force_authenticate(self.other)
        metadata = self.client.get('/api/paper', {'pcode': str(self.paper.code)}).json()['data']
        self.assertEqual(metadata['invitationCode'], str(invitation.code))
        self.assertEqual(metadata['title'], self.paper.title)
        self.assertNotIn('hearts', metadata)
        self.assertEqual(self.write(self.other).status_code, 471)

    def test_pending_list_is_personal_minimal_and_private_invitations_are_visible(self):
        invitation = self.invite()
        self.client.force_authenticate(self.other)
        data = self.listing()
        self.assertEqual(data['count'], 1)
        item = data['results'][0]
        self.assertEqual(item['invitationCode'], str(invitation.code))
        self.assertFalse(item['isPublic'])
        self.assertEqual(set(item), {'invitationCode', 'sentAt', 'code', 'title', 'theme', 'host', 'receivingDate', 'isPublic'})
        self.assertEqual(set(item['host']), {'name'})
        for viewer in (self.host, self.writer, self.receiver):
            self.client.force_authenticate(viewer)
            self.assertEqual(self.listing()['count'], 0)

    def test_accept_removes_pending_adds_membership_and_private_access_without_password(self):
        invitation = self.invite()
        password_hash = self.paper.password
        self.client.force_authenticate(self.other)
        for _ in range(2):
            self.assertEqual(self.reply(invitation).status_code, 204)
        self.assertEqual(self.listing()['count'], 0)
        self.assertTrue(self.paper.invitingUser.filter(pk=self.other.pk).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'accepted')
        self.assertIsNotNone(invitation.respondedAt)
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 200)
        self.assertEqual(self.client.get('/api/paper/mypage', {'type': 'inviting'}).json()['data']['count'], 1)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.password, password_hash)

    def test_deny_removes_pending_without_membership_ban_or_restoring_old_invite(self):
        invitation = self.invite()
        self.client.force_authenticate(self.other)
        for _ in range(2):
            self.assertEqual(self.reply(invitation, 'deny').status_code, 204)
        self.assertEqual(self.listing()['count'], 0)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())
        self.assertFalse(self.paper.blockedUsers.filter(pk=self.other.pk).exists())
        self.assertEqual(self.reply(invitation).status_code, 409)
        self.assertNotIn('invitationCode', self.client.get('/api/paper', {'pcode': str(self.paper.code)}).json()['data'])
        self.assertEqual(self.client.post('/api/paper/enter', {'pcode': str(self.paper.code)}, format='json').status_code, 400)

    def test_conflicting_response_cannot_undo_acceptance(self):
        invitation = self.invite()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.reply(invitation).status_code, 204)
        self.assertEqual(self.reply(invitation, 'deny').status_code, 409)
        self.assertTrue(self.paper.invitingUser.filter(pk=self.other.pk).exists())

    def test_reinvitation_after_denial_uses_a_new_identity_and_old_response_is_rejected(self):
        old = self.invite()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.reply(old, 'deny').status_code, 204)
        new = self.invite()
        self.assertNotEqual(old.code, new.code)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.reply(old).status_code, 404)
        self.assertEqual(self.listing()['count'], 1)
        self.assertEqual(self.reply(new).status_code, 204)

    def test_existing_members_are_preserved_and_not_added_to_the_pending_list(self):
        self.assertEqual(self.change('post', self.writer).status_code, 409)
        self.assertEqual(self.change('post', self.host).status_code, 409)
        self.assertFalse(PaperInvitation.objects.exists())
        self.assertTrue(self.paper.invitingUser.filter(pk=self.writer.pk).exists())

    def test_link_entry_also_settles_pending_invitation_but_does_not_accept_without_explicit_post(self):
        invitation = self.invite()
        self.client.force_authenticate(self.other)
        self.client.get('/api/paper', {'pcode': str(self.paper.code)})
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'pending')
        self.assertEqual(self.client.post('/api/paper/enter', {'pcode': str(self.paper.code)}, format='json').status_code, 204)
        self.assertEqual(self.listing()['count'], 0)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'accepted')

    def test_only_the_invited_account_can_respond_and_anonymous_requests_are_rejected(self):
        invitation = self.invite()
        for account in (self.host, self.writer, self.receiver, None):
            self.client.force_authenticate(account)
            self.assertEqual(self.reply(invitation).status_code, 401 if account is None else 404)
        self.assertEqual(self.client.get('/api/paper/invitations').status_code, 401)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())

    def test_scheduled_and_early_delivery_remove_pending_and_disallow_both_decisions(self):
        invitation = self.invite()
        for stat, date in ((1, '2026-10-29'), (0, '2026-10-26')):
            Paper.objects.filter(pk=self.paper.pk).update(receivingStat=stat, receivingDate=date)
            with patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 26, 10))):
                self.client.force_authenticate(self.other)
                self.assertEqual(self.listing()['count'], 0)
                for action in ('accept', 'deny'):
                    self.assertEqual(self.reply(invitation, action).status_code, 483)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())

    def test_blocked_invitee_cannot_use_a_stale_invitation(self):
        invitation = self.invite()
        self.paper.blockedUsers.add(self.other)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.listing()['count'], 0)
        self.assertEqual(self.reply(invitation).status_code, 403)

    def test_failed_accept_rolls_back_membership_and_pending_state(self):
        invitation = self.invite()
        self.client.force_authenticate(self.other)
        with patch.object(PaperInvitation, 'save', side_effect=RuntimeError('local rollback test')):
            with self.assertRaises(RuntimeError):
                self.reply(invitation)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'pending')

    def test_paper_deletion_removes_pending_invitation(self):
        invitation = self.invite()
        self.paper.delete()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.listing()['count'], 0)
        self.assertEqual(self.reply(invitation).status_code, 404)

    def test_invalid_decisions_do_not_change_pending_state(self):
        invitation = self.invite()
        self.client.force_authenticate(self.other)
        for body in ({}, {'invitationCode': 'bad', 'action': 'accept'}, {'invitationCode': str(invitation.code), 'action': 'other'}):
            self.assertEqual(self.client.post('/api/paper/invitations', body, format='json').status_code, 400)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'pending')

    def test_pending_pagination_is_stable_and_invalid_pages_are_errors(self):
        papers = baker.make(Paper, hostFK=self.host, receivingDate='2099-01-01', receivingStat=0, _quantity=23)
        for paper in papers:
            PaperInvitation.objects.create(paper=paper, user=self.other)
        self.client.force_authenticate(self.other)
        first = self.listing()
        second = self.client.get('/api/paper/invitations', {'page': 2}).json()['data']
        self.assertEqual(first['count'], 23)
        self.assertEqual(len(first['results']), 20)
        self.assertEqual(len(second['results']), 3)
        self.assertFalse({item['invitationCode'] for item in first['results']} & {item['invitationCode'] for item in second['results']})
        self.assertEqual(self.client.get('/api/paper/invitations', {'page': 3}).status_code, 404)

    def test_inactive_hosts_do_not_offer_pending_invitation_bypass(self):
        invitation = self.invite()
        type(self.host).objects.filter(pk=self.host.pk).update(is_active=False)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.listing()['count'], 0)
        self.assertEqual(self.reply(invitation).status_code, 403)
        self.assertNotIn('invitationCode', self.client.get('/api/paper', {'pcode': str(self.paper.code)}).json()['data'])
        self.assertEqual(self.client.post('/api/paper/enter', {'pcode': str(self.paper.code)}, format='json').status_code, 400)

    def test_retrying_acceptance_after_leaving_does_not_restore_membership(self):
        invitation = self.invite()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.reply(invitation).status_code, 204)
        self.assertEqual(self.client.post('/api/paper/leave', {'pcode': str(self.paper.code)}, format='json').status_code, 204)
        self.assertEqual(self.reply(invitation).status_code, 204)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())
        self.assertEqual(self.listing()['count'], 0)
