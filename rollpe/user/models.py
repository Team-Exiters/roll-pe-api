import uuid
from django.db import models
from django.contrib.auth.models import BaseUserManager, AbstractBaseUser, PermissionsMixin

class BaseTimeModel(models.Model):
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True
        
# Create your models here.
class UserManager(BaseUserManager):
    
    def create_user(self, email, password=None, **extra_fields):
        
        if not email:
            raise ValueError('The Email field must be set')
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        for flag in ('is_staff', 'is_superuser'):
            if extra_fields[flag] is not True:
                raise ValueError(f'Superuser must have {flag}=True.')
        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin, BaseTimeModel):
    name = models.CharField(
        max_length=25,
    )
    
    email = models.EmailField(
        unique=True,
        null=True,
        blank=True,
    )

    apple_subject = models.CharField(max_length=255, unique=True, null=True, editable=False)
    
    birth = models.CharField(
        max_length=6,
        null=True,
        blank=True
    )
    
    sex = models.BooleanField(
        null=True,
        blank=True
    )
    
    phoneNumber = models.CharField(
        max_length=11,
        null=True,
        blank=True
    )
    
    is_staff = models.BooleanField(
        # django에서 필요한 필드
        default=False
    )

    is_active = models.BooleanField(
        # django에서 필요한 필드
        default=True
    )
    code = models.UUIDField(
        # uuid 필드
        default=uuid.uuid4, 
        editable=True,
        null=True
    )
    identifyCode = models.CharField(
        max_length=6,
        null=True,
        blank=True
    )
    provider = models.CharField(
        max_length=15,
        null=True,
        blank=True
    )
    
    objects = UserManager()
    USERNAME_FIELD = 'email'
    # REQUIRED_FIELDS = ['name','email']


class AppleAuthFlow(models.Model):
    """Shared, single-use browser login state (also works across Gunicorn workers)."""

    state_hash = models.CharField(max_length=64, unique=True)
    nonce = models.CharField(max_length=64)
    client_state = models.CharField(max_length=64)
    code_challenge = models.CharField(max_length=43)
    return_url = models.CharField(max_length=512)
    expires_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16, default='pending')
    exchange_hash = models.CharField(max_length=64, null=True, unique=True)
    user = models.ForeignKey(User, null=True, on_delete=models.CASCADE)
    credential = models.ForeignKey('AppleCredential', null=True, on_delete=models.CASCADE)


class AppleCredential(models.Model):
    """One Apple authorization and its encrypted server-only token response."""

    user = models.ForeignKey(User, related_name='apple_credentials', on_delete=models.CASCADE)
    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    client_id = models.CharField(max_length=255)
    token_response = models.TextField(editable=False)
    verified_at = models.DateTimeField()
    checked_at = models.DateTimeField(null=True)
    invalidated_at = models.DateTimeField(null=True)
    apple_revoked_at = models.DateTimeField(null=True)


class SocialIdentity(models.Model):
    """Verified provider subject; email is only used for a legacy account's first binding."""

    provider = models.CharField(max_length=8, choices=[('google', 'Google'), ('kakao', 'Kakao')])
    subject = models.CharField(max_length=255, editable=False)
    subject_hash = models.CharField(max_length=64, editable=False)
    user = models.ForeignKey(User, related_name='social_identities', on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['provider', 'subject_hash'], name='unique_social_subject'),
            models.UniqueConstraint(fields=['user', 'provider'], name='unique_user_social_provider'),
        ]


class SocialAuthFlow(models.Model):
    """Single-use browser authorization and client PKCE proof shared by all workers."""

    provider = models.CharField(max_length=8, choices=[('google', 'Google'), ('kakao', 'Kakao')])
    state_hash = models.CharField(max_length=64, unique=True)
    nonce = models.CharField(max_length=64)
    provider_verifier = models.CharField(max_length=128, editable=False)
    client_state = models.CharField(max_length=64)
    code_challenge = models.CharField(max_length=43)
    return_url = models.CharField(max_length=512)
    expires_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16, default='pending')
    exchange_hash = models.CharField(max_length=64, null=True, unique=True)
    identity = models.ForeignKey(SocialIdentity, null=True, on_delete=models.CASCADE)


class UserBlock(models.Model):
    blocker = models.ForeignKey(User, related_name='blocked_users', on_delete=models.CASCADE)
    blocked = models.ForeignKey(User, related_name='blocked_by', on_delete=models.CASCADE)
    createdAt = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['blocker', 'blocked'], name='unique_user_block'),
            models.CheckConstraint(condition=~models.Q(blocker=models.F('blocked')), name='prevent_self_block'),
        ]


class ContentReport(BaseTimeModel):
    class Target(models.TextChoices):
        PAPER = 'paper', '롤페'
        HEART = 'heart', '마음'

    class Reason(models.TextChoices):
        SPAM = 'spam', '스팸·광고'
        ABUSE = 'abuse', '욕설·혐오·괴롭힘'
        INAPPROPRIATE = 'inappropriate', '음란·불법·부적절한 내용'
        OTHER = 'other', '기타'

    class Status(models.TextChoices):
        PENDING = 'pending', '접수'
        RESOLVED = 'resolved', '처리 완료'
        DISMISSED = 'dismissed', '반려'

    reporterFK = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='content_reports')
    reportedUserFK = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='received_reports')
    paperFK = models.ForeignKey('paper.Paper', on_delete=models.SET_NULL, null=True)
    heartFK = models.ForeignKey('heart.Heart', on_delete=models.SET_NULL, null=True)
    targetType = models.CharField(max_length=5, choices=Target.choices)
    targetCode = models.UUIDField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    description = models.TextField(max_length=500, blank=True)
    # Keep the content as seen when reported, even after an edit or deletion. No credentials or contact details.
    snapshot = models.JSONField(editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    staffNote = models.TextField(blank=True)

    class Meta:
        verbose_name = '콘텐츠 신고'
        verbose_name_plural = '콘텐츠 신고'
        ordering = ['-createdAt', '-pk']
        constraints = [models.UniqueConstraint(fields=['reporterFK', 'targetType', 'targetCode'], name='unique_content_report')]
