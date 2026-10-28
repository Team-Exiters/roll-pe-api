
from django.contrib import admin
from django.urls import path

from paper.apis import UserPaperAPI, PaperAPI, PaperEnterManageAPI, MyPagePaperAPI, PaperSendAPI
from paper.participants import PaperParticipantsAPI, PaperLeaveAPI
from paper.invitations import PaperInvitationsAPI

urlpatterns = [
	path('', PaperAPI.as_view(), name='paper_api'),
	path('/user', UserPaperAPI.as_view(), name='paper_api_for_user'),
	path('/mypage', MyPagePaperAPI.as_view(), name='user_mypage_paper_api'),
	path('/enter', PaperEnterManageAPI.as_view(), name='paper_invite_api'),
	path('/send', PaperSendAPI.as_view(), name='paper_send_api'),
	path('/participants', PaperParticipantsAPI.as_view(), name='paper_participants_api'),
	path('/leave', PaperLeaveAPI.as_view(), name='paper_leave_api'),
	path('/invitations', PaperInvitationsAPI.as_view(), name='paper_invitations_api'),
]
