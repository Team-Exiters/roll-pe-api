from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from model_bakery import baker
from django.contrib.auth import get_user_model
from paper.models import Paper, QueryIndexTable
import json


class UserPaperAPITest(APITestCase):
	def setUp(self):
		self.user = baker.make(get_user_model())
		self.client.force_authenticate(user=self.user)
		self.theme = baker.make(QueryIndexTable, type='THEME')
		self.size = baker.make(QueryIndexTable, type='SIZE')
		self.ratio = baker.make(QueryIndexTable, type='RATIO')

	def test_get_papers(self):
		paper = baker.make(Paper, hostFK=self.user, themeFK=self.theme, sizeFK=self.size, ratioFK=self.ratio,
			viewStat=True, receivingDate='2099-01-01', receivingStat=0)
		url = reverse('paper_api_for_user')
		response = self.client.get(url)
		self.assertEqual(response.status_code, status.HTTP_200_OK)
		response_data = json.loads(response.content)
		self.assertIn(paper.title, [item['title'] for item in response_data['data']['results']])

	def test_create_paper(self):
		data = {
			'hostFK': self.user.id,
			'themeFK': self.theme.id,
			'sizeFK': self.size.id,
			'ratioFK': self.ratio.id,
			'receiverName': 'Test Receiver',
			'receiverTel': '01012345678',
			'receivingDate': '2023-10-01',
			'title': 'New Paper',
			'description': 'This is a new paper',
			'password': 'testpassword'
			}
		url = reverse('paper_api_for_user')
		response = self.client.post(url, data=data)
		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		response_data = json.loads(response.content)
		self.assertEqual(response_data['data']['title'], data['title'])

	def test_delete_paper(self):
		paper = baker.make(Paper, hostFK=self.user, receivingDate='2099-01-01', receivingStat=0)
		url = reverse('paper_api_for_user')
		response = self.client.delete(url, data={'pcode': str(paper.code)}, format='json')
		self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
		with self.assertRaises(Paper.DoesNotExist):
			Paper.objects.get(id=paper.id)


class PaperAPITest(APITestCase):
	def setUp(self):
		self.user = baker.make(get_user_model())
		self.client.force_authenticate(user=self.user)
		self.paper = baker.make(Paper, hostFK=self.user, receivingDate='2099-01-01', receivingStat=0)

	def test_get_paper_detail(self):
		url = reverse('paper_api') + f'?pcode={self.paper.code}'
		response = self.client.get(url)
		self.assertEqual(response.status_code, status.HTTP_200_OK)
		response_data = json.loads(response.content)
		self.assertEqual(response_data['data']['title'], self.paper.title)

	def test_post_paper(self):
		data = {
			'hostFK': self.user.id,
			'themeFK': self.paper.themeFK.id,
			'sizeFK': self.paper.sizeFK.id,
			'ratioFK': self.paper.ratioFK.id,
			'receiverName': 'Test Receiver',
			'receiverTel': '01012345678',
			'receivingDate': '2023-10-01',
			'title': 'New Paper',
			'description': 'This is a new paper',
			'password': 'testpassword'
			}
		url = reverse('paper_api')
		response = self.client.post(url, data=data)
		self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class PaperEnterManageAPITest(APITestCase):
	def setUp(self):
		self.user = baker.make(get_user_model())
		self.client.force_authenticate(user=self.user)

	def test_enter_manage_with_valid_password(self):
		paper = baker.make(Paper, hostFK=self.user, password='testpassword', receivingDate='2099-01-01')
		url = reverse('paper_invite_api')
		response = self.client.post(url, {'pcode': str(paper.code), 'password': 'testpassword'}, format='json')
		self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

	def test_enter_manage_with_invalid_password(self):
		paper = baker.make(Paper, hostFK=self.user, password='correctpassword', viewStat=False, receivingDate='2099-01-01')
		url = reverse('paper_invite_api')
		response = self.client.post(url, {'pcode': str(paper.code), 'password': 'wrongpassword'}, format='json')
		self.assertEqual(response.status_code, 472)
		self.assertFalse(paper.invitingUser.filter(pk=self.user.pk).exists())


class PaperAuthorizationTests(APITestCase):
    def setUp(self):
        self.host = baker.make(get_user_model())
        self.other = baker.make(get_user_model())
        self.paper = baker.make(Paper, hostFK=self.host)
        self.payload = {
            'themeFK': self.paper.themeFK_id, 'sizeFK': self.paper.sizeFK_id,
            'ratioFK': self.paper.ratioFK_id, 'receiverFK': self.other.pk,
            'title': 'Authenticated creation', 'receivingDate': '2026-10-20',
        }

    def test_create_requires_authentication_on_both_routes(self):
        for route in ('paper_api', 'paper_api_for_user'):
            self.assertEqual(self.client.post(reverse(route), self.payload).status_code, 401)
        self.assertEqual(Paper.objects.count(), 1)

    def test_both_routes_reject_host_spoof_and_derive_current_host(self):
        self.client.force_authenticate(self.host)
        for route in ('paper_api', 'paper_api_for_user'):
            self.assertEqual(self.client.post(reverse(route), {**self.payload, 'hostFK': self.other.pk}).status_code, 400)
            self.assertEqual(self.client.post(reverse(route), self.payload).status_code, 201)
        self.assertEqual(Paper.objects.count(), 3)
        self.assertFalse(Paper.objects.exclude(hostFK=self.host).exists())

    def test_optional_null_phone_is_valid_with_registered_receiver(self):
        self.client.force_authenticate(self.host)
        response = self.client.post(reverse('paper_api'), {**self.payload, 'receiverTel': None}, format='json')
        self.assertEqual(response.status_code, 201)

    def test_delete_handles_anonymous_missing_invalid_and_unknown_codes(self):
        route = reverse('paper_api_for_user')
        self.assertEqual(self.client.delete(route, {'pcode': str(self.paper.code)}).status_code, 401)
        self.client.force_authenticate(self.host)
        for payload in ({}, {'pcode': 'bad-uuid'}, {'pcode': ['bad']}):
            self.assertEqual(self.client.delete(route, payload, format='json').status_code, 400)
        self.assertEqual(self.client.delete(route, {'pcode': '00000000-0000-0000-0000-000000000000'}).status_code, 404)
        self.assertTrue(Paper.objects.filter(pk=self.paper.pk).exists())

    def test_only_host_can_delete_and_legacy_denials_remain(self):
        self.client.force_authenticate(self.other)
        route = reverse('paper_api_for_user')
        self.assertEqual(self.client.delete(route, {'pcode': str(self.paper.code)}).status_code, 471)
        self.paper.invitingUser.add(self.other)
        self.assertEqual(self.client.delete(route, {'pcode': str(self.paper.code)}).status_code, 470)
        self.assertTrue(Paper.objects.filter(pk=self.paper.pk).exists())

    def test_malformed_detail_and_entry_codes_return_client_error(self):
        self.client.force_authenticate(self.host)
        self.assertEqual(self.client.get(reverse('paper_api'), {'pcode': 'bad'}).status_code, 400)
        self.assertEqual(self.client.post(reverse('paper_invite_api'), {'pcode': 'bad'}).status_code, 400)


class QueryIndexAuthorizationTests(APITestCase):
    def test_catalog_get_is_public_and_post_requires_staff(self):
        route = reverse('query_index')
        payload = {'name': 'Test theme', 'type': 'THEME', 'query': {}}
        self.assertEqual(self.client.get(route).status_code, 200)
        self.assertEqual(self.client.post(route, payload, format='json').status_code, 401)
        self.client.force_authenticate(baker.make(get_user_model(), is_staff=False))
        self.assertEqual(self.client.post(route, payload, format='json').status_code, 403)
        self.assertFalse(QueryIndexTable.objects.exists())
        self.client.force_authenticate(baker.make(get_user_model(), is_staff=True))
        self.assertEqual(self.client.post(route, payload, format='json').status_code, 201)
        self.assertEqual(QueryIndexTable.objects.count(), 1)
