from model_bakery import baker

from heart.models import Heart
from paper.models import Paper, PaperInvitation, QueryIndexTable
from paper.tests_participants import PaperParticipantsFixture
from user.models import User


class PaperCapacityTests(PaperParticipantsFixture):
    def fill(self, total=12):
        # The fixture has a host and one accepted participant, without hearts.
        people = baker.make(User, _quantity=total - 2)
        self.paper.invitingUser.add(*people)
        return people

    def enter(self, user, password='local-paper-test'):
        self.client.force_authenticate(user)
        return self.client.post('/api/paper/enter', {'pcode': str(self.paper.code), 'password': password}, format='json')

    def invite(self, user):
        self.client.force_authenticate(self.host)
        self.assertEqual(self.change('post', user).status_code, 204)
        return PaperInvitation.objects.get(paper=self.paper, user=user)

    def reply(self, user, invitation, action='accept'):
        self.client.force_authenticate(user)
        return self.client.post('/api/paper/invitations', {'invitationCode': str(invitation.code), 'action': action}, format='json')

    def assert_full(self, response):
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['data'], {'reason': 'full'})
        self.assertIn('정원', response.json()['message'])

    def test_full_public_and_private_links_expose_only_a_capacity_notice(self):
        self.fill()
        for public in (False, True):
            Paper.objects.filter(pk=self.paper.pk).update(viewStat=public)
            self.client.force_authenticate(self.other)
            self.assert_full(self.client.get('/api/paper', {'pcode': str(self.paper.code)}))
            self.assert_full(self.enter(self.other))
        self.assertEqual(Heart.objects.count(), 0)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())

    def test_last_place_is_shared_by_link_entry_and_invitation_acceptance(self):
        self.fill(11)
        invitation = self.invite(self.receiver)
        self.assertEqual(self.enter(self.other).status_code, 204)
        self.assert_full(self.reply(self.receiver, invitation))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'pending')
        self.assertIsNone(invitation.respondedAt)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.receiver.pk).exists())

    def test_pending_invitations_and_receiver_only_do_not_reserve_places(self):
        self.fill(11)
        first = self.invite(self.other)
        second = self.invite(self.receiver)
        for user in baker.make(User, _quantity=13):
            self.invite(user)
        self.assertEqual(self.reply(self.other, first).status_code, 204)
        self.assert_full(self.reply(self.receiver, second))
        # Capacity refusal never removes the pending invite from its inbox.
        listing = self.client.get('/api/paper/invitations').json()['data']
        self.assertEqual(listing['count'], 1)
        self.assertEqual(listing['results'][0]['invitationCode'], str(second.code))
        self.assertEqual(self.reply(self.receiver, second, 'deny').status_code, 204)

    def test_link_acceptance_cannot_bypass_full_pending_invitation(self):
        invitation = self.invite(self.other)
        self.fill()
        self.assert_full(self.enter(self.other, ''))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'pending')
        self.assertFalse(self.paper.invitingUser.filter(pk=self.other.pk).exists())

    def test_existing_participants_keep_read_write_and_idempotent_entry_at_capacity(self):
        self.fill()
        self.assertEqual(self.enter(self.host).status_code, 204)
        # Counting the host also present in membership and hearts must not duplicate it.
        self.paper.invitingUser.add(self.host)
        for user in (self.host, self.writer):
            self.assertEqual(self.enter(user).status_code, 473)
            self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 200)
        self.assertEqual(self.write(self.writer).status_code, 201)
        heart = Heart.objects.get(userFK=self.writer)
        body = {'paperFK': self.paper.pk, 'heartPK': heart.pk, 'context': '정원 이후 수정', 'location': 0, 'color': 'F2EB28'}
        self.assertEqual(self.client.patch('/api/heart', body, format='json').status_code, 200)

    def test_leaving_releases_a_place_and_retry_can_accept_the_same_pending_invitation(self):
        invitation = self.invite(self.other)
        self.fill()
        self.assert_full(self.reply(self.other, invitation))
        self.client.force_authenticate(self.writer)
        self.assertEqual(self.client.post('/api/paper/leave', {'pcode': str(self.paper.code)}, format='json').status_code, 204)
        self.assertEqual(self.reply(self.other, invitation).status_code, 204)
        self.assertEqual(self.reply(self.other, invitation).status_code, 204)
        self.assertEqual(self.client.get('/api/paper/invitations').json()['data']['count'], 0)

    def test_kicking_releases_a_place_but_does_not_allow_the_blocked_user_back(self):
        self.fill()
        self.client.force_authenticate(self.host)
        self.assertEqual(self.change('delete', self.writer).status_code, 204)
        self.assertEqual(self.enter(self.writer).status_code, 403)
        self.assertEqual(self.enter(self.other).status_code, 204)

    def test_legacy_public_write_cannot_bypass_membership_capacity(self):
        self.fill()
        Paper.objects.filter(pk=self.paper.pk).update(viewStat=True)
        self.assert_full(self.write(self.other))
        self.assertEqual(Heart.objects.count(), 0)
        self.assertEqual(self.write(self.writer).status_code, 201)

    def test_legacy_authors_count_once_and_can_join_without_reserving_a_second_place(self):
        self.fill(11)
        self.paper.invitingUser.add(self.host)
        Heart.objects.create(paperFK=self.paper, userFK=self.host, colorFK=self.color, context='방장', location=0)
        Heart.objects.create(paperFK=self.paper, userFK=self.other, colorFK=self.color, context='기존 작성자', location=1)
        self.assert_full(self.enter(self.receiver))
        self.assertEqual(self.enter(self.other).status_code, 204)

    def test_delivery_blocking_and_authentication_still_take_precedence(self):
        self.fill()
        self.paper.blockedUsers.add(self.other)
        self.assertEqual(self.enter(self.other).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 401)
        Paper.objects.filter(pk=self.paper.pk).update(receivingStat=1)
        self.client.force_authenticate(self.receiver)
        self.assertEqual(self.client.get('/api/paper', {'pcode': str(self.paper.code)}).status_code, 200)
        self.assertEqual(self.enter(self.receiver).status_code, 483)

    def test_configured_size_limit_and_invalid_limit_fallback(self):
        QueryIndexTable.objects.filter(pk=self.paper.sizeFK_id).update(query={'max': 2})
        self.assert_full(self.enter(self.other))
        self.fill(11)
        QueryIndexTable.objects.filter(pk=self.paper.sizeFK_id).update(query={'max': True})
        self.assertEqual(self.enter(self.other).status_code, 204)
        self.assert_full(self.enter(self.receiver))
