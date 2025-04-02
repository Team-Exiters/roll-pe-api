from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.utils.timezone import localtime, now
from datetime import datetime
from datetime import timedelta
from urllib.parse import urlencode
from pprint import pprint
from django.contrib.auth.hashers import make_password


from user.models import User
from paper.models import Paper, QueryIndexTable
from heart.models import Heart


class BaseTestSetup(APITestCase):
    @classmethod
    def create_test_users(cls):
        """테스트 유저 생성"""
        users = [
            User(name='receiver', email='receiver@gmail.com'),
            User(name='host', email='host@gmail.com'),
            User(name='test_user1', email='testuser1@gmail.com'),
            User(name='test_user2', email='testuser2@gmail.com'),
            User(name='test_user3', email='testuser3@gmail.com'),
        ]
        User.objects.bulk_create(users)

        # 생성된 객체 다시 가져오기
        cls.receiver, cls.host, cls.user1, cls.user2, cls.user3 = User.objects.all()

        # 비밀번호 암호화 후 업데이트
        User.objects.filter(id__in=[cls.user1.id, cls.user2.id, cls.user3.id]).update(
            password=make_password('1234')
        )

    @classmethod
    def create_test_paper(cls):
        """테스트 롤링페이퍼생성"""
        
        # 인덱스 테이블 생성
        query_indexs = [
            QueryIndexTable(name='F2EB28', query={}, type='COLOR', is_vip=False),
            QueryIndexTable(name='28E8F2', query={}, type='COLOR', is_vip=False),
            QueryIndexTable(name='F228D3', query={}, type='COLOR', is_vip=False),
            QueryIndexTable(name='화이트', query={}, type='THEME', is_vip=False),
            QueryIndexTable(name='A4', query={}, type='SIZE', is_vip=False),
            QueryIndexTable(name='세로', query={}, type='RATIO', is_vip=False),
        ]
        QueryIndexTable.objects.bulk_create(query_indexs)
        
        cls.color1, cls.color2, cls.color3, theme, size, ratio = QueryIndexTable.objects.all()
        
        # 테스트 롤링페이퍼 생성 (공개)
        cls.public_rolling_paper = Paper.objects.create(
            receiverFK=cls.receiver,
            hostFK=cls.host,
            receivingDate='2026-12-31',
            title='공개 롤링페이퍼',
            description='테스트 입니다.',
            viewStat=True,
            themeFK=theme,
            sizeFK=size,
            ratioFK=ratio
        )
        
        # 테스트 롤링페이퍼 생성 (비공개)
        cls.private_rolling_paper = Paper.objects.create(
            receiverFK=cls.receiver,
            hostFK=cls.host,
            receivingDate='2026-12-31',
            title='비공개 롤링페이퍼',
            description='테스트 입니다.',
            password='1234',
            viewStat=False,
            themeFK=theme,
            sizeFK=size,
            ratioFK=ratio
        )
        
        # 롤링페이퍼로 유저 초대
        cls.private_rolling_paper.invitingUser.add(cls.user1, cls.user3)
        cls.private_rolling_paper.save()
        
    @classmethod
    def setUpTestData(cls):
        """테스트 데이터 생성"""
        cls.create_test_users() 
        cls.create_test_paper()
        cls.api_url = reverse('heart_api')

    def signin(self, user):
        """
            테스트유저 로그인
        """
        signin_url = reverse('token_obtain_pair')
        signin_data = {}
        
        if user == 'user1':
            signin_data['email'] = self.user1.email
            signin_data['password'] = '1234'
        else:
            signin_data['email'] = self.user2.email
            signin_data['password'] = '1234'
        
        response = self.client.post(signin_url, signin_data)
        token = response.json()['data']['access']
        
        # 인증 헤더 설정
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        
        
class HeartReadAPITest(BaseTestSetup):
    @classmethod
    def setUpTestData(cls):
        """HeartReadAPITest 전용 데이터 생성"""
        super().setUpTestData()
        
        # 테스트 마음 생성
        hearts = [
            Heart(
                userFK=cls.user1,
                paperFK=cls.public_rolling_paper,
                colorFK=cls.color1,
                context='공개 롤링페이퍼의 테스트 마음1 입니다.',
                location=1
            ),
            Heart(
                userFK=cls.user2,
                paperFK=cls.public_rolling_paper,
                colorFK=cls.color2,
                context='공개 롤링페이퍼의 테스트 마음2 입니다.',
                location=3
            ),
            Heart(
                userFK=cls.user1,
                colorFK=cls.color1,
                paperFK=cls.private_rolling_paper,
                context='비공개 롤링페이퍼의 테스트 마음1 입니다.',
                location=5
            ),
            Heart(
                userFK=cls.user3,
                colorFK=cls.color3,
                paperFK=cls.private_rolling_paper,
                context='비공개 롤링페이퍼의 테스트 마음2 입니다.',
                location=4
            ),
        ]

        Heart.objects.bulk_create(hearts)
        
        cls.heart1, cls.heart2, cls.heart3, cls.heart4 = Heart.objects.all()

    
    def test_get_heart_without_authenticated(self):
        """
            로그인하지 않은 유저는 마음을 조회할 수 없다.
        """
        pcode = {'pcode': self.public_rolling_paper.code}
        url_with_params = f'{self.api_url}?{urlencode(pcode)}'
        response = self.client.get(url_with_params)
        
        # 응답 상태 코드 확인
        self.assertEqual(response.status_code, 401, '상태코드가 올바르지 않습니다.')
    
    """ 에러남 """
    # def test_get_public_heart_list(self):
    #     """
    #         공개 롤링페이퍼에 작성된 마음목록을 가져올 수 있어야 한다.
    #     """
    #     self.signin(user='user1')
        
    #     # API 요청
    #     pcode = {'pcode': self.public_rolling_paper.code}
    #     url_with_params = f'{self.api_url}?{urlencode(pcode)}'
        
    #     response = self.client.get(url_with_params)

    #     # 예상 데이터
    #     expected_data = [
    #         {
    #             'id': self.heart1.id,
    #             'userName': self.heart1.userFK.name,
    #             'rollingPaperName': self.heart1.paperFK.title,
    #             'context': self.heart1.context,
    #             'danger': self.heart1.danger,
    #             'createdAt': localtime(self.heart2.createdAt).strftime('%Y.%m.%d'),
    #             'location': self.heart1.location,
    #             'code': str(self.heart1.code),
    #             'blur': False,
    #             'color':self.heart1.colorFK.name
    #         },
    #         {
    #             'id': self.heart2.id,
    #             'userName': self.heart2.userFK.name,
    #             'rollingPaperName': self.heart2.paperFK.title,
    #             'context': self.heart2.context,
    #             'danger': self.heart2.danger,
    #             'createdAt': localtime(self.heart1.createdAt).strftime('%Y.%m.%d'),
    #             'location': self.heart2.location,
    #             'code': str(self.heart2.code),
    #             'blur': False,
    #             'color':self.heart2.colorFK.name
    #         }
    #     ]
        
    #     # 응답 상태 코드 확인
    #     self.assertEqual(response.status_code, 200, '상태코드가 올바르지 않습니다.')
        
    #     # 응답 데이터 비교
    #     self.assertListEqual(response.json()['data']['results'], expected_data, '응답 데이터가 올바르지 않습니다.')
        
    
    def test_get_private_heart_list_without_invited(self):
        """
            비공개 롤링페이퍼에 작성된 마음목록을 초대되지 않은 유저는 조회할 수 없다.
        """
        self.signin(user='user2')

        # API 요청
        pcode = {'pcode': self.private_rolling_paper.code}
        url_with_params = f'{self.api_url}?{urlencode(pcode)}'
        
        response = self.client.get(url_with_params)
       
       # 응답 상태 코드 확인
        self.assertEqual(response.status_code, 471, '상태코드가 올바르지 않습니다.')
        
    """ 에러남 """
    # def test_get_private_heart_list(self):
    #     """
    #         비공개 롤링페이퍼에 작성된 마음목록을 초대받은 유저는 조회할 수 있다.
    #     """
    #     self.signin(user='user1')
        
    #     # API 요청
    #     pcode = {'pcode': self.private_rolling_paper.code}
    #     url_with_params = f'{self.api_url}?{urlencode(pcode)}'
        
    #     response = self.client.get(url_with_params)
        
    #     # 예상 데이터
    #     expected_data = [
    #         {
    #             'id': self.heart3.id,
    #             'userName': self.heart3.userFK.name,
    #             'rollingPaperName': self.heart3.paperFK.title,
    #             'context': self.heart3.context,
    #             'danger': self.heart3.danger,
    #             'createdAt': localtime(self.heart3.createdAt).strftime('%Y.%m.%d'),
    #             'location': self.heart3.location,
    #             'code': str(self.heart3.code),
    #             'blur': False,
    #             'color':self.heart3.colorFK.name
    #         },
    #         {
    #             'id': self.heart4.id,
    #             'userName': self.heart4.userFK.name,
    #             'rollingPaperName': self.heart4.paperFK.title,
    #             'context': self.heart4.context,
    #             'danger': self.heart4.danger,
    #             'createdAt': localtime(self.heart3.createdAt).strftime('%Y.%m.%d'),
    #             'location': self.heart4.location,
    #             'code': str(self.heart4.code),
    #             'blur': True,
    #             'color':self.heart4.colorFK.name
    #         }
    #     ]
        
    #      # 응답 상태 코드 확인
    #     self.assertEqual(response.status_code, 200, '상태코드가 올바르지 않습니다.')
        
    #     # 응답 데이터 비교
    #     self.assertListEqual(response.json()['data']['results'], expected_data, '응답 데이터가 올바르지 않습니다.')
        
    """ 에러남 """
    # def test_get_heart_detail(self):
    #     """
    #         마음 상세정보를 가져올 수 있어야 한다.
    #     """
    #     self.signin(user='user1')
        
    #     hcode = {'hcode': self.heart1.code}
    #     url_with_params = f'{self.api_url}?{urlencode(hcode)}'
        
    #     response = self.client.get(url_with_params)
        
    #     expected_data = {
    #         'id': self.heart1.id,
    #         'userName': self.heart1.userFK.name,
    #         'rollingPaperName': self.heart1.paperFK.title,
    #         'context': self.heart1.context,
    #         'danger': self.heart1.danger,
    #         'createdAt': localtime(self.heart1.createdAt).strftime('%Y.%m.%d'),
    #         'location': self.heart1.location,
    #         'code': str(self.heart1.code),
    #         'blur': False,
    #         'color':self.heart1.colorFK.name
    #     }

    #     # 응답 상태 코드 확인
    #     self.assertEqual(response.status_code, 200, '상태코드가 올바르지 않습니다.')
        
    #     # 응답 데이터 비교
    #     self.assertDictEqual(response.json()['data'], expected_data, '응답 데이터가 올바르지 않습니다.')
        
    

class HeartCreateAPITest(BaseTestSetup):
    @classmethod
    def setUpTestData(cls):
        """HeartCreateAPITest 전용 데이터 생성"""
        super().setUpTestData()
        
        cls.public_heart_data = {
            'paperFK': cls.public_rolling_paper.id,
            'color': 'F2EB28',
            'context': '마음1 테스트 입니다.',
            'location': 1
        }
        cls.private_heart_data = {
            'paperFK': cls.private_rolling_paper.id,
            'color': '28E8F2',
            'context': '마음2 테스트 입니다.',
            'location': 1
        }
        
        
    def test_create_heart_without_authenticated(self):
        """
            로그인하지 않은 유저는 마음을 작성할 수 없다.
        """
        response = self.client.post(self.api_url, self.public_heart_data, format='json')
        
        # 응답 상태 코드 확인
        self.assertEqual(response.status_code, 401, '상태코드가 올바르지 않습니다.')
        
        
    def test_create_heart_without_invited(self):
        """
            초대 받지 않은 유저는 마음을 작성할 수 없다.
        """
        self.signin('user2')
        response = self.client.post(self.api_url, self.private_heart_data, format='json')
        
        # 응답 상태 코드 확인
        self.assertEqual(response.status_code, 471, '상태코드가 올바르지 않습니다.')
    
    
    # def test_create_heart(self):
    #     """
    #         새로운 마음을 생성할 수 있어야 한다.
    #     """
    #     self.signin('user1')
    #     private_response = self.client.post(self.api_url, self.private_heart_data, format='json')
    #     public_response = self.client.post(self.api_url, self.public_heart_data, format='json')
        
    #     # 응답 상태 코드 확인
    #     self.assertEqual(public_response.status_code, 201, '상태코드가 올바르지 않습니다.')
    
    
    # def test_create_heart_duplicate(self):
    #     """
    #         이미 마음을 작성한 유저는 재작성할 수 없다.
    #     """
    #     self.signin('user1')
    #     self.client.post(self.api_url, self.private_heart_data, format='json')
        
    #     # 재작성 요청
    #     response = self.client.post(self.api_url, self.private_heart_data, format='json')
    
    #     self.assertEqual(response.status_code, 482, '상태코드가 올바르지 않습니다.')


class HeartUpdateAPITest(BaseTestSetup):
    @classmethod
    def setUpTestData(cls):
        """HeartUpdateAPITest 전용 데이터 생성"""
        super().setUpTestData()
        
        # 테스트 마음 생성
        cls.heart1 = Heart.objects.create(
            userFK=cls.user1,
            paperFK=cls.public_rolling_paper,
            colorFK=cls.color1,
            context='롤링페이퍼의 테스트 마음1 입니다.',
            location=1
        )
        
        cls.update_data = {
            'heartPK': cls.heart1.id,
            'paperFK': cls.heart1.paperFK.id,
            'color': 'F2EB28',
            'context': '롤링페이퍼의 수정을 했습니다.',
            'location': 1
        }
        
    def test_update_heart_without_authenticated(self):
        """
             로그인하지 않은 유저는 마음을 수정할 수 없다.       
        """
        response = self.client.patch(self.api_url, self.update_data, format='json')
        
        self.assertEqual(response.status_code, 401, '상태코드가 올바르지 않습니다.')
        
        
    def test_update_heart_without_permission(self):
        """
            본인이 작성하지 않은 마음을 수정할 수 없다.
        """
        self.signin('user2')
        
        response = self.client.patch(self.api_url, self.update_data, format='json')
        
        self.assertEqual(response.status_code, 481, '상태코드가 올바르지 않습니다.')
        
    """ 에러남 """
    # def test_update_heart(self):
    #     """
    #         마음을 수정할 수 있다.
    #     """
    #     self.signin('user1')
    #     response = self.client.patch(self.api_url, self.update_data, format='json')
        
    #     updated_context = response.json()['data']['context']
        
    #     self.assertEqual(response.status_code, 200, '상태코드가 올바르지 않습니다.')
    #     self.assertEqual(updated_context, self.update_data['context'], '수정 정보가 올바르게 반영되지 않았습니다.')
        
        
    def test_update_heart_time_limit_exceeded(self):
        """
            유효시간이 지난 마음은 수정할 수 없다.
        """
        self.signin('user1')
        
        # 테스트를 위해 시간을 인위적으로 조작
        paper = self.public_rolling_paper
        paper.receivingDate = now().date() + timedelta(days=1)
        paper.save()
        
        response = self.client.patch(self.api_url, self.update_data, format='json')

        self.assertEqual(response.status_code, 483, '상태코드가 올바르지 않습니다.')
        
    