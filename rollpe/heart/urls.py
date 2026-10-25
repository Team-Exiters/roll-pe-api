
from django.urls import path
from heart.apis import HeartAPI, get_my_heart_list
from heart.revisions import HeartRevisionsAPI

urlpatterns = [
    path('', HeartAPI.as_view(), name='heart_api'),
    path('/my', get_my_heart_list, name='get_my_heart_list'),
    path('/revisions', HeartRevisionsAPI.as_view(), name='heart_revisions_api'),
]
