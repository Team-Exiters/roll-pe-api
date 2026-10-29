from unittest.mock import patch
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection, IntegrityError

from heart.models import Heart, HeartRevision
from django.contrib.auth import get_user_model
from model_bakery import baker
from rest_framework.test import APITestCase

from paper.models import Paper, QueryIndexTable


class HeartRevisionTests(APITestCase):
    def setUp(self):
        self.host, self.writer, self.other, self.receiver = baker.make(get_user_model(), _quantity=4)
        self.paper = Paper.objects.create(
            hostFK=self.host, receiverFK=self.receiver, title='마음 수정 이력 검증', receivingDate='2099-10-29',
            themeFK=QueryIndexTable.objects.create(type='THEME', name='화이트'),
            ratioFK=QueryIndexTable.objects.create(type='RATIO', name='가로'),
            sizeFK=QueryIndexTable.objects.create(type='SIZE', name='A4', query={'max': 12}), password='local-history-test',
        )
        self.color = QueryIndexTable.objects.create(type='COLOR', name='F2EB28')
        self.paper.invitingUser.add(self.writer)
        self.client.force_authenticate(self.writer)

    def write(self):
        return self.client.post('/api/heart', {'paperFK': self.paper.pk, 'context': '원래 마음', 'location': 0,
                                             'color': 'F2EB28'}, format='json')

    def edit(self, **changes):
        heart = Heart.objects.get(paperFK=self.paper, userFK=self.writer)
        return self.client.patch('/api/heart', {'paperFK': self.paper.pk, 'heartPK': heart.pk,
            'context': '수정 마음', 'location': 0, 'color': 'F2EB28', **changes}, format='json')

    def history(self, code):
        return self.client.get('/api/heart/revisions', {'hcode': str(code)})

    def test_original_and_each_actual_edit_are_returned_newest_first_with_color_and_actor(self):
        self.assertEqual(self.write().status_code, 201)
        first = Heart.objects.get()
        self.assertEqual(first.revisionCount, 0)
        self.assertEqual(self.edit().json()['data']['revisionCount'], 1)
        # An identical retry must not manufacture another revision.
        self.assertEqual(self.edit().json()['data']['revisionCount'], 1)
        self.assertEqual(self.edit(context='두 번째 수정').json()['data']['revisionCount'], 2)
        data = self.history(first.code).json()['data']['revisions']
        self.assertEqual([r['number'] for r in data], [2, 1, 0])
        self.assertEqual([r['content'] for r in data], ['두 번째 수정', '수정 마음', '원래 마음'])
        self.assertTrue(all(r['color'] == 'F2EB28' and r['editor']['id'] == self.writer.pk for r in data))
        self.assertFalse(data[0]['baseline'])
        self.assertTrue(all('recordedAt' in r for r in data))

    def test_color_only_edit_is_recorded_and_unauthorized_edits_are_not(self):
        self.write()
        color = self.color.__class__.objects.create(type='COLOR', name='FFB9B9')
        self.assertEqual(self.edit(context='원래 마음', color=color.name).status_code, 200)
        self.assertEqual(Heart.objects.get().revisionCount, 1)
        self.assertEqual(HeartRevision.objects.last().color, 'FFB9B9')
        self.client.force_authenticate(self.host)
        self.assertEqual(self.edit().status_code, 481)
        self.assertEqual(HeartRevision.objects.count(), 2)

    def test_only_the_author_and_host_can_read_history_even_on_a_public_paper(self):
        self.write()
        heart = Heart.objects.get()
        self.edit()
        for user in (self.writer, self.host):
            self.client.force_authenticate(user)
            self.assertEqual(self.history(heart.code).status_code, 200)
        self.paper.invitingUser.add(self.other)
        for public in (False, True):
            self.paper.__class__.objects.filter(pk=self.paper.pk).update(viewStat=public)
            for user in (self.other, self.receiver):
                self.client.force_authenticate(user)
                self.assertEqual(self.history(heart.code).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.history(heart.code).status_code, 401)

    def test_history_failure_rolls_back_the_current_text_and_revision_count(self):
        self.write()
        with patch.object(HeartRevision.objects, 'create', side_effect=IntegrityError('local simulated failure')):
            with self.assertRaises(IntegrityError):
                self.edit()
        heart = Heart.objects.get()
        self.assertEqual((heart.context, heart.revisionCount), ('원래 마음', 0))
        self.assertEqual(HeartRevision.objects.count(), 1)

    def test_legacy_memo_uses_an_honest_baseline_and_delete_removes_the_entire_history(self):
        heart = Heart.objects.create(paperFK=self.paper, userFK=self.writer, colorFK=self.color, context='기존 내용', location=0)
        self.client.force_authenticate(self.writer)
        self.assertTrue(self.history(heart.code).json()['data']['revisions'][0]['baseline'])
        self.assertEqual(self.edit().status_code, 200)
        self.assertEqual(list(heart.revisions.values_list('content', flat=True)), ['기존 내용', '수정 마음'])
        self.assertTrue(heart.revisions.first().baseline)
        self.assertEqual(self.client.delete('/api/heart', {'hcode': str(heart.code)}).status_code, 404)
        self.assertEqual(self.client.delete(f'/api/heart?hcode={heart.code}').status_code, 204)
        self.assertFalse(HeartRevision.objects.exists())

    def test_migration_seeds_existing_text_as_a_baseline_without_changing_the_memo(self):
        heart = Heart.objects.create(paperFK=self.paper, userFK=self.writer, colorFK=self.color, context='기존 내용', location=0)
        seed = import_module('heart.migrations.0004_participants_and_heart_history').seed_baselines
        seed(apps, SimpleNamespace(connection=connection))
        version = heart.revisions.get(number=0)
        self.assertEqual((version.content, version.color, version.editorFK_id), ('기존 내용', self.color.name, self.writer.pk))
        self.assertTrue(version.baseline)
        heart.refresh_from_db()
        self.assertEqual(heart.revisionCount, 0)
        self.assertEqual(version.recordedAt, heart.updatedAt)

    def test_failed_original_snapshot_rolls_back_the_new_heart(self):
        with patch.object(HeartRevision.objects, 'create', side_effect=IntegrityError('local simulated failure')):
            with self.assertRaises(IntegrityError):
                self.write()
        self.assertFalse(Heart.objects.exists())
        self.assertFalse(HeartRevision.objects.exists())
