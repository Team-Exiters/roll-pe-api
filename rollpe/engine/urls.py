from django.urls import path

from engine.apis import SearchAPI
from engine.support import InquiriesAPI, NoticeAPI, NoticesAPI

urlpatterns = [
	path('/inquiries', InquiriesAPI.as_view(), name='inquiries'),
	path('/notices', NoticesAPI.as_view(), name='notices'),
	path('/notices/<int:pk>', NoticeAPI.as_view(), name='notice'),
	path('/search', SearchAPI.as_view(), name='paper_search_api'),
	path('/serach', SearchAPI.as_view(), name='search_api'),
	]
