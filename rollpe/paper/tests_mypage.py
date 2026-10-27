from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from heart.models import Heart
from paper.models import Paper, PaperInvitation, QueryIndexTable


class MyPagePaperTests(APITestCase):
    def setUp(self):
        self.user, self.other, self.receiver = baker.make(get_user_model(), _quantity=3)
        self.theme = baker.make(QueryIndexTable, type='THEME', name='화이트')
        self.ratio = baker.make(QueryIndexTable, type='RATIO', name='가로')
        self.size = baker.make(QueryIndexTable, type='SIZE', name='A4', query={'max': 12})
        self.client.force_authenticate(self.user)
        clock = patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 26, 9)))
        clock.start()
        self.addCleanup(clock.stop)

    def paper(self, **kwargs):
        return Paper.objects.create(**{**dict(hostFK=self.other, receiverFK=self.receiver, receivingDate='2026-10-29',
            title='마이페이지 목록', themeFK=self.theme, ratioFK=self.ratio, sizeFK=self.size), **kwargs})

    def listing(self, kind, **query):
        return self.client.get('/api/paper/mypage', {'type': kind, **query})

    def codes(self, kind):
        response = self.listing(kind)
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        return [item['code'] for item in ([] if data == [] else data['results'])]

    def test_personal_lists_require_authentication_and_unknown_types_are_invalid(self):
        self.assertEqual(self.listing('unknown').status_code, 400)
        self.client.force_authenticate(None)
        for kind in ('main', 'host', 'my', 'inviting', 'participating'):
            self.assertEqual(self.listing(kind).status_code, 401)

    def test_created_list_includes_only_owned_papers_and_retains_private_and_delivered_history(self):
        opened = self.paper(hostFK=self.user, password='local-mypage-paper')
        delivered = self.paper(hostFK=self.user, receivingStat=1)
        self.paper()
        self.assertEqual(set(self.codes('host')), {str(opened.code), str(delivered.code)})

    def test_participating_is_open_membership_excluding_host_pending_invites_and_blocked_users(self):
        active = self.paper(password='local-private-participation')
        own = self.paper(hostFK=self.user)
        early = self.paper(receivingStat=1)
        scheduled = self.paper(receivingDate='2026-10-25')
        blocked = self.paper()
        blocked.blockedUsers.add(self.user)
        for paper in (active, own, early, scheduled, blocked):
            paper.invitingUser.add(self.user)
        pending = self.paper()
        PaperInvitation.objects.create(paper=pending, user=self.user)
        self.assertEqual(self.codes('participating'), [str(active.code)])
        self.assertEqual(set(self.codes('inviting')), {str(paper.code) for paper in (active, own, early, scheduled)})

    def test_received_requires_designated_receiver_and_delivery_including_early_and_exact_korea_deadline(self):
        today = self.paper(receiverFK=self.user, receivingDate='2026-10-26')
        early = self.paper(receiverFK=self.user, receivingStat=1)
        self.paper(receiverFK=self.user)
        self.paper(receivingStat=1)
        self.assertEqual(self.codes('my'), [str(early.code)])
        with patch('paper.lifecycle.timezone.now', return_value=timezone.make_aware(datetime(2026, 10, 26, 10))):
            self.assertEqual(set(self.codes('my')), {str(today.code), str(early.code)})

    def test_personal_list_summaries_never_include_heart_content_or_members(self):
        paper = self.paper(hostFK=self.user)
        paper.invitingUser.add(self.other)
        color = baker.make(QueryIndexTable, type='COLOR', name='F2EB28')
        Heart.objects.create(paperFK=paper, userFK=self.other, colorFK=color, context='상세에서만 보여야 할 마음', location=0)
        item = self.listing('host').json()['data']['results'][0]
        self.assertEqual(item['hearts'], {'count': 1})
        self.assertEqual(item['invitingUser'], [])
        self.assertNotIn('password', item)
        self.assertNotIn('상세에서만 보여야 할 마음', str(item))

    def test_empty_legacy_lists_and_new_pagination_keep_their_contracts(self):
        for kind in ('host', 'my', 'inviting'):
            self.assertEqual(self.listing(kind).json()['data'], [])
        self.assertEqual(self.listing('participating').json()['data'], {'count': 0, 'next': None, 'previous': None, 'results': []})
        self.assertEqual(self.listing('participating', page=2).status_code, 404)

    def test_personal_lists_have_stable_nonoverlapping_pagination(self):
        for _ in range(23):
            self.paper(hostFK=self.user)
        first, second = [self.listing('host', page=page).json()['data'] for page in (1, 2)]
        self.assertEqual(first['count'], 23)
        self.assertEqual(len(first['results']), 20)
        self.assertEqual(len(second['results']), 3)
        self.assertTrue({item['code'] for item in first['results']}.isdisjoint(item['code'] for item in second['results']))

    def test_accept_and_leave_update_participating_without_changing_created_or_received(self):
        paper = self.paper(password='local-accept-list-test')
        invitation = PaperInvitation.objects.create(paper=paper, user=self.user)
        self.assertEqual(self.codes('participating'), [])
        self.assertEqual(self.client.post('/api/paper/invitations', {'invitationCode': str(invitation.code), 'action': 'accept'}, format='json').status_code, 204)
        self.assertEqual(self.codes('participating'), [str(paper.code)])
        self.assertEqual(self.codes('host'), [])
        self.assertEqual(self.codes('my'), [])
        self.assertEqual(self.client.post('/api/paper/leave', {'pcode': str(paper.code)}, format='json').status_code, 204)
        self.assertEqual(self.codes('participating'), [])

    def test_profile_counts_use_owned_papers_and_authored_hearts(self):
        mine = self.paper(hostFK=self.user)
        other = self.paper()
        color = baker.make(QueryIndexTable, type='COLOR', name='F2EB28')
        Heart.objects.create(paperFK=other, userFK=self.user, colorFK=color, context='내 마음', location=0)
        Heart.objects.create(paperFK=mine, userFK=self.other, colorFK=color, context='다른 사람 마음', location=0)
        self.assertEqual(self.listing('main').json()['data'], {'host': 1, 'heart': 1})
