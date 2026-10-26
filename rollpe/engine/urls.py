from django.urls import path

from engine.apis import SearchAPI

urlpatterns = [
	path('/search', SearchAPI.as_view(), name='paper_search_api'),
	path('/serach', SearchAPI.as_view(), name='search_api'),
	]
