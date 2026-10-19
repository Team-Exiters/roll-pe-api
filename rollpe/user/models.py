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
        
        # extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        # extra_fields.setdefault('user_role', 2)
        
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
