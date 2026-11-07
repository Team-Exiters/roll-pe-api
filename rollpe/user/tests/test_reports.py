import uuid
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from heart.models import Heart
from paper.models import Paper
from paper.tests_participants import PaperParticipantsFixture
from user.admin import ContentReportAdmin
from user.models import ContentReport, UserBlock
from user.reports import content_snapshot


class ContentReportsTests(PaperParticipantsFixture):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.write()
        self.heart = Heart.objects.get(paperFK=self.paper)
        self.client.force_authenticate(self.host)

    def report(self, **changes):
        body = {'targetType': 'heart', 'targetCode': str(self.heart.code), 'reason': 'abuse',
                'description': ' 확인 부탁드립니다. ', **changes}
        return self.client.post('/api/user/reports', body, format='json')

    def test_heart_report_uses_authenticated_identity_and_server_snapshot_without_exposing_details(self):
        response = self.report(reporterFK=self.other.pk, reportedUserFK=self.receiver.pk, snapshot={'content': '가짜'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['data'], {'alreadyReported': False})
        report = ContentReport.objects.get()
        self.assertEqual(report.reporterFK, self.host)
        self.assertEqual(report.reportedUserFK, self.writer)
        self.assertEqual(report.heartFK, self.heart)
        self.assertEqual(report.paperFK, self.paper)
        self.assertEqual(report.description, '확인 부탁드립니다.')
        self.assertEqual(report.snapshot['heart']['content'], '원래 마음')
        self.assertEqual(report.status, 'pending')
        self.assertNotIn('password', str(report.snapshot))
        self.assertNotIn('email', str(report.snapshot))
        self.assertNotIn('원래 마음', str(response.json()))

    def test_same_report_is_idempotent_and_preserves_original_evidence_reason_and_moderation_state(self):
        self.assertEqual(self.report().status_code, 201)
        report = ContentReport.objects.get()
        ContentReport.objects.filter(pk=report.pk).update(status='resolved')
        Heart.objects.filter(pk=self.heart.pk).update(context='나중에 바뀐 마음')
        for _ in range(2):
            response = self.report(reason='spam', description='변경된 신고')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['data']['alreadyReported'])
        self.assertEqual(ContentReport.objects.count(), 1)
        report.refresh_from_db()
        self.assertEqual(report.reason, 'abuse')
        self.assertEqual(report.status, 'resolved')
        self.assertEqual(report.snapshot['heart']['content'], '원래 마음')

    def test_paper_reports_from_a_participant_snapshot_visible_memos_and_exclude_blocked_writers(self):
        self.paper.invitingUser.add(self.other)
        self.client.force_authenticate(self.other)
        UserBlock.objects.create(blocker=self.other, blocked=self.writer)
        response = self.report(targetType='paper', targetCode=str(self.paper.code), reason='other', description='')
        self.assertEqual(response.status_code, 201)
        report = ContentReport.objects.get()
        self.assertEqual(report.reportedUserFK, self.host)
        self.assertEqual(report.snapshot, {'title': self.paper.title, 'paperCode': str(self.paper.code), 'hearts': []})
        self.assertIsNone(report.heartFK)

    def test_repeated_paper_reports_do_not_read_or_rebuild_memo_evidence(self):
        self.client.force_authenticate(self.writer)
        with patch('user.reports.content_snapshot', wraps=content_snapshot) as snapshot:
            self.assertEqual(self.report(targetType='paper', targetCode=str(self.paper.code)).status_code, 201)
            self.assertEqual(self.report(targetType='paper', targetCode=str(self.paper.code)).status_code, 200)
        self.assertEqual(snapshot.call_count, 1)
        self.assertEqual(ContentReport.objects.get().snapshot['hearts'][0]['content'], '원래 마음')

    def test_only_delivered_receiver_can_report_after_delivery(self):
        Paper.objects.filter(pk=self.paper.pk).update(receivingStat=1)
        for user in (self.host, self.writer, self.other):
            self.client.force_authenticate(user)
            self.assertEqual(self.report().status_code, 403)
        self.client.force_authenticate(self.receiver)
        self.assertEqual(self.report().status_code, 201)
        self.assertEqual(self.report(targetType='paper', targetCode=str(self.paper.code)).status_code, 201)

    def test_private_outsiders_kicked_and_personally_blocked_targets_cannot_be_reported(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.report().status_code, 403)
        self.paper.invitingUser.add(self.other)
        self.paper.blockedUsers.add(self.other)
        self.assertEqual(self.report().status_code, 403)
        self.client.force_authenticate(self.host)
        UserBlock.objects.create(blocker=self.host, blocked=self.writer)
        self.assertEqual(self.report().status_code, 403)
        self.assertFalse(ContentReport.objects.exists())

    def test_self_reports_anonymous_missing_and_malformed_requests_are_rejected(self):
        self.client.force_authenticate(self.writer)
        self.assertEqual(self.report().status_code, 400)
        self.client.force_authenticate(self.host)
        self.assertEqual(self.report(targetType='paper', targetCode=str(self.paper.code)).status_code, 400)
        for body in ({}, [], {'targetType': 'user'}, {'reason': 'invented'},
                     {'targetCode': 'bad'}, {'description': '가' * 501}, {'description': []}):
            response = self.client.post('/api/user/reports', body, format='json') if not body or isinstance(body, list) else self.report(**body)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.report(targetCode=str(uuid.uuid4())).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.report().status_code, 401)
        self.assertFalse(ContentReport.objects.exists())

    def test_report_list_and_evidence_are_not_exposed_through_app_api(self):
        self.report()
        for method in ('get', 'patch', 'delete'):
            response = getattr(self.client, method)('/api/user/reports')
            self.assertEqual(response.status_code, 405)
            self.assertNotIn('원래 마음', str(response.content))

    def test_evidence_remains_after_content_and_accounts_are_deleted(self):
        self.report()
        report = ContentReport.objects.get()
        code = report.targetCode
        self.paper.delete()
        report.refresh_from_db()
        self.assertIsNone(report.paperFK)
        self.assertIsNone(report.heartFK)
        self.assertEqual(report.targetCode, code)
        self.assertEqual(report.snapshot['heart']['content'], '원래 마음')
        self.host.delete()
        self.writer.delete()
        report.refresh_from_db()
        self.assertIsNone(report.reporterFK)
        self.assertIsNone(report.reportedUserFK)
        model_admin = ContentReportAdmin(ContentReport, admin.site)
        self.assertEqual(model_admin.reporter(report), '삭제된 사용자')
        self.assertEqual(model_admin.reported_user(report), '삭제된 사용자')

    def test_rate_limit_is_per_authenticated_user_and_preserves_response_envelope(self):
        with self.settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'report-rate-test'}}):
            cache.clear()
            for _ in range(20):
                self.assertIn(self.report().status_code, (200, 201))
            response = self.report()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()['status_code'], 429)
            self.assertGreater(response.json()['data']['retryAfter'], 0)
            self.client.force_authenticate(self.receiver)
            self.paper.invitingUser.add(self.receiver)
            self.assertEqual(self.report().status_code, 201)

    def test_staff_can_review_reports_but_users_cannot_access_admin(self):
        self.report()
        moderator = get_user_model().objects.create_superuser(email='moderator@example.test')
        self.client.force_login(moderator)
        url = reverse('admin:user_contentreport_changelist')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        report = ContentReport.objects.get()
        self.assertEqual(self.client.get(reverse('admin:user_contentreport_change', args=[report.pk])).status_code, 200)
        model_admin = ContentReportAdmin(ContentReport, admin.site)
        self.assertIn('snapshot', model_admin.readonly_fields)
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))
        self.client.logout()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_superuser_creation_rejects_missing_admin_privileges(self):
        users = get_user_model().objects
        for flag in ('is_staff', 'is_superuser'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                users.create_superuser(email='invalid-admin@example.test', **{flag: False})
        self.assertFalse(users.filter(email='invalid-admin@example.test').exists())
        user = users.create_user(email='ordinary-user@example.test')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
