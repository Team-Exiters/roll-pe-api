from django.contrib.auth import get_user_model
from django.urls import reverse
from model_bakery import baker
from rest_framework.test import APITestCase

from paper.models import Paper


class SearchTests(APITestCase):
    def test_missing_or_blank_keyword_returns_client_error(self):
        self.client.force_authenticate(baker.make(get_user_model()))
        for query in ({}, {'k': ''}, {'k': '   '}):
            self.assertEqual(self.client.get(reverse('search_api'), query).status_code, 400)

    def test_search_requires_authentication_and_returns_existing_envelope(self):
        self.assertEqual(self.client.get(reverse('search_api'), {'k': 'hello'}).status_code, 401)
        host = baker.make(get_user_model())
        self.client.force_authenticate(host)
        baker.make(Paper, hostFK=host, title='hello world')
        response = self.client.get(reverse('search_api'), {'k': 'hello'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['results'][0]['title'], 'hello world')
