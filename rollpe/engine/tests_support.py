import uuid

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from model_bakery import baker
from rest_framework.test import APITestCase

from engine.admin import InquiryAdmin
from engine.models import Inquiry
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
