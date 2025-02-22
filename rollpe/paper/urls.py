
from django.contrib import admin
from django.urls import path

from paper.apis import UserPaperAPI, PaperAPI, PaperEnterManageAPI, MyPagePaperAPI

urlpatterns = [
	path('', PaperAPI.as_view(), name='paper_api'),
	path('/user', UserPaperAPI.as_view(), name='paper_api_for_user'),
	path('/mypage', MyPagePaperAPI.as_view(), name='user_mypage_paper_api'),
	path('/enter', PaperEnterManageAPI.as_view(), name='paper_invite_api'),
]
