from django.urls import path

from engine.apis import SearchAPI
from engine.support import InquiriesAPI

urlpatterns = [
	path('/inquiries', InquiriesAPI.as_view(), name='inquiries'),
	path('/search', SearchAPI.as_view(), name='paper_search_api'),
	path('/serach', SearchAPI.as_view(), name='search_api'),
	]
