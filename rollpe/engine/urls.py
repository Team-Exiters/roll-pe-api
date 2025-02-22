from django.urls import path

from engine.apis import SearchAPI

urlpatterns = [
	path('/serach', SearchAPI.as_view(), name='search_api'),
	]