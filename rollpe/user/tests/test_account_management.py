from unittest.mock import patch

from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from heart.models import Heart, HeartRevision
from paper.models import Paper, PaperInvitation, QueryIndexTable
from user.models import SocialIdentity, User


class AccountManagementTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='account@example.com', name='계정', password='Old-password1!',
                                             identifyCode='ACCT01', birth='010101', phoneNumber='01012345678')
        self.other = User.objects.create_user(email='other@example.com', name='다른 사용자', identifyCode='ACCT02')
        self.token = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.access_token}')

    def paper(self, **kwargs):
        return baker.make(Paper, hostFK=kwargs.pop('hostFK', self.user), receiverFK=kwargs.pop('receiverFK', self.other),
                          receivingDate='2099-10-27', receivingStat=0, **kwargs)

    def withdraw(self):
        return self.client.delete('/api/user/drop-user', {'refresh': str(self.token), 'identifyCode': 'ACCT01'}, format='json')

    def test_withdraw_preserves_shared_papers_hearts_and_revisions_without_personal_identity(self):
        paper = self.paper()
        color = baker.make(QueryIndexTable, type='COLOR', name='F2EB28')
        heart = Heart.objects.create(paperFK=paper, userFK=self.user, colorFK=color, context='보존하는 마음', location=0)
        revision = HeartRevision.objects.create(heartFK=heart, number=0, content=heart.context, color='F2EB28',
                                                editorFK=self.user, recordedAt=timezone.now())
        paper.invitingUser.add(self.user, self.other)
        self.assertEqual(self.withdraw().status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertFalse(self.user.has_usable_password())
        self.assertEqual(self.user.name, '탈퇴한 사용자')
        self.assertEqual(self.user.identifyCode, '탈퇴계정')
        for field in ('email', 'birth', 'phoneNumber', 'sex', 'provider', 'apple_subject'):
            self.assertIsNone(getattr(self.user, field))
        self.assertTrue(Paper.objects.filter(pk=paper.pk).exists())
        self.assertEqual(Heart.objects.get(pk=heart.pk).context, '보존하는 마음')
        self.assertEqual(HeartRevision.objects.get(pk=revision.pk).content, '보존하는 마음')
        self.assertTrue(paper.invitingUser.filter(pk=self.other.pk).exists())
        self.assertFalse(paper.invitingUser.filter(pk=self.user.pk).exists())
        self.assertEqual(self.client.get('/api/paper/mypage', {'type': 'main'}).status_code, 401)
        self.assertEqual(self.client.post('/api/user/token/refresh', {'refresh': str(self.token)}, format='json').status_code, 401)
        # The original email can be used for a new account; it no longer identifies the author.
        self.assertIsNotNone(User.objects.create_user(email='account@example.com', name='새 사용자').pk)

    def test_receiver_or_heart_reference_alone_is_sufficient_to_preserve_the_anonymous_author(self):
        for source in ('receiver', 'heart'):
            with self.subTest(source=source):
                user = User.objects.create_user(email=f'{source}@example.com', name='참여자', identifyCode='ACCT03')
                token = RefreshToken.for_user(user)
                paper = self.paper(hostFK=self.other, receiverFK=user if source == 'receiver' else self.other)
                if source == 'heart':
                    baker.make(Heart, paperFK=paper, userFK=user)
                self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
                self.assertEqual(self.client.delete('/api/user/drop-user', {'refresh': str(token), 'identifyCode': 'ACCT03'}, format='json').status_code, 200)
                user.refresh_from_db()
                self.assertEqual(user.name, '탈퇴한 사용자')
                self.assertFalse(user.is_active)

    def test_withdraw_removes_provider_binding_pending_invites_and_search_visibility(self):
        self.paper()
        User.objects.filter(pk=self.user.pk).update(provider='google')
        SocialIdentity.objects.create(user=self.user, provider='google', subject='local-subject', subject_hash='a' * 64)
        PaperInvitation.objects.create(paper=self.paper(hostFK=self.other), user=self.user)
        self.assertEqual(self.withdraw().status_code, 200)
        self.assertFalse(SocialIdentity.objects.filter(user=self.user).exists())
        self.assertFalse(PaperInvitation.objects.filter(user=self.user).exists())
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/user/search-user/', {'nameCode': '탈퇴한 사용자'}).status_code, 404)

    def test_unreferenced_account_retains_existing_hard_delete_behavior(self):
        user_id = self.user.pk
        self.assertEqual(self.withdraw().status_code, 200)
        self.assertFalse(User.objects.filter(pk=user_id).exists())

    def test_failed_anonymization_rolls_back_account_and_token_changes(self):
        self.paper()
        with patch.object(User, 'save', side_effect=RuntimeError('local rollback check')):
            with self.assertRaises(RuntimeError):
                self.withdraw()
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.email, 'account@example.com')
        RefreshToken(str(self.token))

    def test_password_change_blocks_social_users_and_invalid_passwords(self):
        for password in ('short', 'onlyletters', 'No-number!', ' Missing-trim1! '):
            self.assertEqual(self.client.patch('/api/user/change-password', {'refresh': str(self.token), 'newPassword': password}, format='json').status_code, 400)
            self.user.refresh_from_db()
            self.assertTrue(self.user.check_password('Old-password1!'))
        User.objects.filter(pk=self.user.pk).update(provider='google')
        self.assertEqual(self.client.patch('/api/user/change-password', {'refresh': str(self.token), 'newPassword': 'New-password1!'}, format='json').status_code, 403)

    def test_password_change_invalidates_refresh_tokens_on_all_devices(self):
        other_token = RefreshToken.for_user(self.user)
        self.assertEqual(self.client.patch('/api/user/change-password', {'refresh': str(self.token), 'newPassword': 'New-password1!'}, format='json').status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('New-password1!'))
        for token in (self.token, other_token):
            with self.assertRaises(TokenError):
                RefreshToken(str(token))
