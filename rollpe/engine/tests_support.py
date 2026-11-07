import uuid
from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from engine.admin import InquiryAdmin
from engine.models import Inquiry, Notice
from engine.notice_html import clean_notice_html
from paper.models import Paper
from user.account import remove_account


class InquiryTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(email='inquiry@example.test')
        self.client.force_authenticate(self.user)
        self.body = {'requestId': str(uuid.uuid4()),
                     'category': 'bug', 'content': ' 확인 부탁드립니다. '}

    def send(self, **changes):
        return self.client.post('/api/engine/inquiries', {**self.body, **changes}, format='json')

    def test_authenticated_receipt_ignores_client_identity_and_retry_preserves_the_first_inquiry(self):
        self.assertEqual(self.send(userFK=999, status='completed', email='spoofed@example.com').status_code, 201)
        self.assertEqual(self.send(content='다시 쓴 내용').status_code, 200)
        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.userFK, self.user)
        self.assertEqual(inquiry.email, self.user.email)
        self.assertEqual(inquiry.content, '확인 부탁드립니다.')
        self.assertEqual(inquiry.status, 'pending')
        self.assertEqual(self.send().json()['data'], {'received': True})

    def test_invalid_and_unauthenticated_submissions_and_app_reads_are_rejected(self):
        for body in ({'content': ' '}, {'category': 'invented'},
                     {'content': '가' * 2001}, {'requestId': 'invalid'}):
            self.assertEqual(self.send(**body).status_code, 400)
        self.assertEqual(self.client.get('/api/engine/inquiries').status_code, 405)
        self.client.force_authenticate(None)
        self.assertEqual(self.send().status_code, 401)
        self.assertFalse(Inquiry.objects.exists())

    def test_legacy_accounts_without_an_email_can_submit_using_their_authenticated_identity(self):
        get_user_model().objects.filter(pk=self.user.pk).update(email=None)
        self.assertEqual(self.send().status_code, 201)
        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.email, '')
        self.assertEqual(inquiry.userFK_id, self.user.pk)

    def test_throttle_limits_new_messages_but_allows_receipt_retries(self):
        for _ in range(10):
            self.assertEqual(self.send(requestId=str(uuid.uuid4())).status_code, 201)
        self.assertEqual(self.send().status_code, 429)
        existing = Inquiry.objects.first()
        self.assertEqual(self.send(requestId=str(existing.requestId)).status_code, 200)

    def test_withdrawal_removes_private_inquiries_when_shared_papers_keep_an_anonymous_user(self):
        self.send()
        baker.make(Paper, hostFK=self.user)
        remove_account(self.user)
        self.assertFalse(Inquiry.objects.exists())
        self.assertFalse(get_user_model().objects.get(pk=self.user.pk).is_active)

    def test_staff_can_read_inquiries_but_original_submission_fields_are_readonly(self):
        self.send()
        moderator = get_user_model().objects.create_superuser(email='support-admin@example.test')
        self.client.force_login(moderator)
        self.assertEqual(self.client.get(reverse('admin:engine_inquiry_changelist')).status_code, 200)
        model_admin = InquiryAdmin(Inquiry, admin.site)
        self.assertIn('content', model_admin.readonly_fields)
        self.assertFalse(model_admin.has_add_permission(None))


class NoticeTests(APITestCase):
    def setUp(self):
        self.notice = Notice.objects.create(title='서비스 안내', body='<p>안녕하세요.</p>', isPublished=True)

    def test_public_list_is_newest_first_and_hides_drafts_scheduled_posts_and_body(self):
        Notice.objects.create(title='초안', body='<p>초안 본문</p>')
        future = Notice.objects.create(title='예약', body='<p>예약 본문</p>', isPublished=True,
                                       publishedAt=timezone.now() + timedelta(days=1))
        newest = Notice.objects.create(title='새 공지', body='<p>새 공지 본문</p>', isPublished=True)
        response = self.client.get('/api/engine/notices')
        self.assertEqual(response.status_code, 200)
        items = response.json()['data']['results']
        self.assertEqual([item['id'] for item in items], [newest.pk, self.notice.pk])
        self.assertNotIn('body', items[0])
        self.assertEqual(self.client.get(f'/api/engine/notices/{future.pk}').status_code, 404)
        self.notice.isPublished = False
        self.notice.save()
        self.assertEqual(self.client.get(f'/api/engine/notices/{self.notice.pk}').status_code, 404)

    def test_html_keeps_formatting_but_removes_active_content_and_unsafe_links(self):
        self.notice.body = ('<h2>제목</h2><p onclick="alert(1)">내용 <strong>강조</strong></p>'
                            '<script>secret()</script><iframe src="https://example.com"></iframe>'
                            '<a href="javascript:alert(1)">위험 링크</a><a href="/admin">내부 링크</a>'
                            '<a href="https://example.com/help">안내</a>')
        self.notice.save()
        html = self.client.get(f'/api/engine/notices/{self.notice.pk}').json()['data']['body']
        self.assertIn('<strong>강조</strong>', html)
        self.assertIn('href="https://example.com/help"', html)
        self.assertIn('target="_blank"', html)
        for forbidden in ['onclick', '<script', 'secret()', '<iframe', 'javascript:', 'href="/admin"']:
            self.assertNotIn(forbidden, html)
        with self.assertRaises(ValidationError):
            clean_notice_html('<script>onlyScript()</script>')

    def test_admin_clean_sanitizes_body_and_app_cannot_publish(self):
        self.notice.body = '<p onclick="evil()">안내</p>'
        self.notice.full_clean()
        self.assertEqual(self.notice.body, '<p>안내</p>')
        self.assertEqual(self.client.post('/api/engine/notices', {}).status_code, 405)

    def test_invalid_imported_html_is_unavailable_instead_of_a_server_error(self):
        for body in ('', '<script>onlyScript()</script>', '<p>&nbsp;</p>'):
            Notice.objects.filter(pk=self.notice.pk).update(body=body)
            response = self.client.get(f'/api/engine/notices/{self.notice.pk}')
            self.assertEqual(response.status_code, 404)
