import uuid

from paper.models import Paper
from user.models import User

"""
	Paper Share Functions
"""
def is_host(user: User, paper: Paper) -> bool:
	"""
		Host인지 확인함.
	"""
	return True if paper.hostFK == user else False


def is_invited_user(user: User, paper: Paper) -> bool:
	"""
		Host이거나 초대된 유저인지를 확인함.
	"""
	return not is_blocked_user(user, paper) and (is_host(user, paper) or paper.invitingUser.filter(pk=user.pk).exists())


def is_blocked_user(user: User, paper: Paper) -> bool:
	return paper.blockedUsers.filter(pk=user.pk).exists()

def is_only_invited_user(user: User, paper: Paper) -> bool:
	"""
		초대된 유저인지를 확인함.
		호스트인지 말고 초대된 유저인지만 판단해야할 때도 있어서 추가함
	"""
	return not is_blocked_user(user, paper) and paper.invitingUser.filter(pk=user.id).exists()

"""
	Heart Share Functions
"""
def is_valid_uuid(value):
    try:
        if len(value) == 32:
            value = f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"
        uuid_obj = uuid.UUID(value, version=4)
        return str(uuid_obj) == value
    except (ValueError, TypeError):
        return False
