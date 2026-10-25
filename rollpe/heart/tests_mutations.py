from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from heart.models import Heart
from paper.models import Paper, QueryIndexTable


class HeartMutationTests(APITestCase):
    def setUp(self):
        self.host, self.writer, self.other, self.receiver = baker.make(get_user_model(), _quantity=4)
        self.color = QueryIndexTable.objects.create(type='COLOR', name='F2EB28')
        self.mono = QueryIndexTable.objects.create(type='MONOCOLOR', name='999999')
        self.paper = Paper.objects.create(
            hostFK=self.host, receiverFK=self.receiver,
            themeFK=QueryIndexTable.objects.create(type='THEME', name='화이트'),
            ratioFK=QueryIndexTable.objects.create(type='RATIO', name='가로'),
            sizeFK=QueryIndexTable.objects.create(type='SIZE', name='A4', query={'max': 12}),
            receivingDate='2026-10-25', title='마음 작성 검증', password='test-only-paper-password',
        )
        self.paper.invitingUser.add(self.writer, self.other)
        self.body = {'paperFK': self.paper.pk, 'context': '축하해요!', 'location': 2, 'color': 'f2eb28'}
        self.client.force_authenticate(user=self.writer)

    def send(self, method, data=None, hour=9, minute=59, second=59, query=''):
        instant = timezone.make_aware(datetime(2026, 10, 25, hour, minute, second))
        with patch('paper.lifecycle.timezone.now', return_value=instant):
            return getattr(self.client, method)('/api/heart' + query, data, format='json')

    def create_heart(self, author=None):
        return Heart.objects.create(userFK=author or self.writer, paperFK=self.paper,
                                    colorFK=self.color, context='기존 마음', location=2)

    def test_create_uses_the_original_contract_and_private_invitation(self):
        response = self.send('post', self.body)
        self.assertEqual(response.status_code, 201)
        data = response.json()['data']
        self.assertEqual((data['index'], data['color'], data['content']), (2, 'F2EB28', '축하해요!'))
        self.assertEqual(data['author']['id'], self.writer.pk)
        self.assertNotIn('password', data)

    def test_write_edit_and_delete_close_at_exactly_ten_am(self):
        heart = self.create_heart()
        edit = {**self.body, 'heartPK': heart.pk}
        for hour, minute, second in ((10, 0, 0), (23, 59, 59)):
            self.assertEqual(self.send('post', {**self.body, 'location': 3}, hour, minute, second).status_code, 483)
            self.assertEqual(self.send('patch', edit, hour, minute, second).status_code, 483)
            self.assertEqual(self.send('delete', hour=hour, minute=minute, second=second,
                                       query=f'?hcode={heart.code}').status_code, 483)
        self.assertEqual(Heart.objects.count(), 1)

    def test_edits_are_available_until_ten_am_and_do_not_move_the_memo(self):
        heart = self.create_heart()
        body = {**self.body, 'heartPK': heart.pk, 'context': '수정한 마음'}
        self.assertEqual(self.send('patch', body).status_code, 200)
        heart.refresh_from_db()
        self.assertEqual((heart.context, heart.location), ('수정한 마음', 2))
        self.assertEqual(self.send('patch', {**body, 'location': 3}).status_code, 480)
        other_paper = baker.make(Paper, hostFK=self.host, receivingDate='2026-10-25')
        self.assertEqual(self.send('patch', {**body, 'paperFK': other_paper.pk}).status_code, 480)

    def test_one_memo_per_writer_and_per_slot(self):
        heart = self.create_heart()
        self.assertEqual(self.send('post', {**self.body, 'location': 3}).status_code, 482)
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.send('post', self.body).status_code, 485)
        self.assertEqual(self.send('post', {**self.body, 'location': 3}).status_code, 201)
        self.assertTrue(Heart.objects.filter(pk=heart.pk).exists())

    def test_content_position_palette_and_target_validation(self):
        for change in ({'context': ''}, {'context': '   '}, {'context': '가' * 41}, {'context': '가\n나'},
                       {'location': -1}, {'location': 12}, {'location': '1.5'}, {'color': 'unknown'},
                       {'color': '999999'}, {'paperFK': -1}):
            response = self.send('post', {**self.body, **change})
            self.assertEqual(response.status_code, 480, change)
        self.assertEqual(Heart.objects.count(), 0)
        self.assertEqual(self.send('post', {**self.body, 'context': '가' * 40}).status_code, 201)

    def test_memorial_uses_the_server_monochrome_palette(self):
        QueryIndexTable.objects.filter(pk=self.paper.themeFK_id).update(name='추모')
        self.assertEqual(self.send('post', self.body).status_code, 480)
        self.assertEqual(self.send('post', {**self.body, 'color': '#999999'}).status_code, 201)

    def test_permissions_cannot_be_overridden_by_body_fields(self):
        self.paper.invitingUser.remove(self.other)
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.send('post', self.body).status_code, 471)
        heart = self.create_heart()
        self.assertEqual(self.send('patch', {**self.body, 'heartPK': heart.pk}).status_code, 481)
        self.assertEqual(self.send('delete', query=f'?hcode={heart.code}').status_code, 470)
        self.client.force_authenticate(user=self.writer)
        response = self.send('patch', {**self.body, 'heartPK': heart.pk, 'userFK': self.host.pk})
        self.assertEqual(response.status_code, 200)
        heart.refresh_from_db()
        self.assertEqual(heart.userFK_id, self.writer.pk)

    def test_host_can_delete_but_cannot_edit_another_writers_memo(self):
        heart = self.create_heart()
        self.client.force_authenticate(user=self.host)
        self.assertEqual(self.send('patch', {**self.body, 'heartPK': heart.pk}).status_code, 481)
        self.assertEqual(self.send('delete', query=f'?hcode={heart.code}').status_code, 204)
        self.assertFalse(Heart.objects.filter(pk=heart.pk).exists())

    def test_author_delete_preserves_other_memos_and_frees_the_slot(self):
        heart = self.create_heart()
        other = Heart.objects.create(userFK=self.other, paperFK=self.paper,
                                     colorFK=self.color, context='다른 작성자의 마음', location=3)
        response = self.send('delete', query=f'?hcode={heart.code}')
        self.assertEqual((response.status_code, response.content), (204, b''))
        self.assertFalse(Heart.objects.filter(pk=heart.pk).exists())
        self.assertTrue(Heart.objects.filter(pk=other.pk).exists())
        self.assertTrue(Paper.objects.filter(pk=self.paper.pk).exists())
        self.assertTrue(self.paper.invitingUser.filter(pk=self.writer.pk).exists())
        detail = self.client.get('/api/paper', {'pcode': str(self.paper.code)}).json()['data']
        self.assertEqual(detail['hearts']['count'], 1)
        self.assertEqual(detail['hearts']['data'][0]['id'], other.pk)
        self.assertEqual(self.send('post', self.body).status_code, 201)

    def test_repeated_delete_and_invalid_codes_leave_existing_data_unchanged(self):
        heart = self.create_heart()
        for query in ('', '?hcode=bad', '?hcode=00000000-0000-4000-8000-000000000000'):
            self.assertEqual(self.send('delete', query=query).status_code, 404)
            self.assertTrue(Heart.objects.filter(pk=heart.pk).exists())
        self.assertEqual(self.send('delete', query=f'?hcode={heart.code}').status_code, 204)
        self.assertEqual(self.send('delete', query=f'?hcode={heart.code}').status_code, 404)
        self.assertTrue(Paper.objects.filter(pk=self.paper.pk).exists())

    def test_invited_non_author_and_removed_private_member_cannot_delete(self):
        heart = self.create_heart()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.send('delete', query=f'?hcode={heart.code}').status_code, 470)
        self.client.force_authenticate(self.writer)
        self.paper.invitingUser.remove(self.writer)
        self.assertEqual(self.send('delete', query=f'?hcode={heart.code}').status_code, 471)
        self.assertTrue(Heart.objects.filter(pk=heart.pk).exists())

    def test_anonymous_requests_are_rejected_before_mutation(self):
        self.client.force_authenticate(user=None)
        for method in ('post', 'patch', 'delete'):
            self.assertEqual(self.send(method, self.body).status_code, 401)

    def test_delivered_receiver_can_read_without_becoming_a_writer(self):
        heart = self.create_heart()
        self.client.force_authenticate(user=self.receiver)
        self.assertEqual(self.send('get', query=f'?hcode={heart.code}').status_code, 471)
        self.assertEqual(self.send('get', hour=10, minute=0, second=0, query=f'?hcode={heart.code}').status_code, 200)
        self.assertEqual(self.send('post', self.body, hour=10).status_code, 471)
        self.assertFalse(self.paper.invitingUser.filter(pk=self.receiver.pk).exists())
