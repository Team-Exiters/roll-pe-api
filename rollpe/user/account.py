import uuid

from django.db.models import Q

from heart.models import Heart
from paper.models import Paper, PaperInvitation
from user.models import AppleAuthFlow, AppleCredential, SocialIdentity


def remove_account(user):
    """Caller holds the user lock. Preserve shared papers without personal identity."""
    referenced = (Paper.objects.filter(Q(hostFK=user) | Q(receiverFK=user)).exists()
                  or Heart.objects.filter(userFK=user).exists())
    if not referenced:
        user.delete()
        return

    AppleAuthFlow.objects.filter(user=user).delete()
    AppleCredential.objects.filter(user=user).delete()
    SocialIdentity.objects.filter(user=user).delete()
    PaperInvitation.objects.filter(user=user).delete()
    user.inviting_user.clear()
    user.blocked_papers.clear()
    user.groups.clear()
    user.user_permissions.clear()
    user.name = '탈퇴한 사용자'
    user.identifyCode = '탈퇴계정'
    user.email = None
    user.apple_subject = None
    user.provider = None
    user.birth = None
    user.sex = None
    user.phoneNumber = None
    user.code = uuid.uuid4()
    user.is_active = False
    user.is_staff = False
    user.is_superuser = False
    user.set_unusable_password()
    user.save(update_fields=['name', 'identifyCode', 'email', 'apple_subject', 'provider', 'birth', 'sex',
                             'phoneNumber', 'code', 'is_active', 'is_staff', 'is_superuser', 'password', 'updatedAt'])
