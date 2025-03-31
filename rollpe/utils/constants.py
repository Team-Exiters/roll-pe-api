class SystemCodeManager:

	CODE_MESSAGES = {
		200: {
			"code": "SUCCESS",
			"link": None,
			"message": "정상 처리되었습니다."
			},
		201: {
			"code": "SUCCESS",
			"link": None,
			"message": "정상적으로 생성되었습니다."
			},
		204: {
			"code": "NO_CONTENT",
			"link": None,
			"message": "정상적으로 삭제되었습니다."
			},
		400: {
			"code": "CLIENT ERROR",
			"link": None,
			"message": "오류가 발생했습니다."
			},
		401: {
			"code": "UNAUTHORIZED",
			"link": "/login",
			"message": "로그인이 필요합니다."
			},
		403: {
			"code": "FORBIDDEN",
			"link": "/login",
			"message": "로그인이 필요합니다."
			},
		404: {
			"code": "NOT_FOUND",
			"link": None,
			"message": "요청하신 리소스를 찾을 수 없습니다."
			},
		# Paper Custom Response
		470: {
			"code": "CANCELLED_YOUR_NOT_HOST",
			"link": None,
			"message": "삭제할 수 있는 권한이 없습니다."
			},
		471: {
			"code": "CANCELLED_YOUR_NOT_INVITED",
			"link": None,
			"message": "초대된 유저가 아닙니다."
			},
		472: {
			"code": "PASSWORD_IS_NOT_CORRECT",
			"link": None,
			"message": "롤페의 비밀번호가 틀립니다."
			},
		473: {
			"code": "ALREADY_ENTERED_USER",
			"link": None,
			"message": "이미 추가된 유저입니다."
			},
		# Heart Custom Response
		480: {
			"code": "SERIALIZER ERROR",
			"link": None,
			"message": "입력 데이터가 올바르지 않습니다."
			},
  		481: {
			"code": "CANCELLED_YOUR_NOT_WRITER",
			"link": None,
			"message": "수정 및 삭제할 수 있는 권한이 없습니다."
			},
  		482: {
			"code": "DUPLICATE_CREATION_NOT_ALLOWED",
			"link": None,
			"message": "해당 롤링페이퍼에 이미 마음을 작성하셨습니다."
			},
		483: {
			"code": "TIME_LIMIT_EXCEEDED",
			"link": None,
			"message": "유효시간이 지나 수정을 할 수 없습니다."
			},
		484: {
			"code": "YOUR_NOT_ADMIN",
			"link": None,
			"message": "해당 요청은 관리자 권한으로만 수행할 수 있습니다."
			},
  		485: {
			"code": "DUPLICATE_INDEX",
			"link": None,
			"message": "다른 사용자가 이미 작성한 마음입니다."
			},
		}

	@classmethod
	def get_message(cls, key: int, default: str = None) -> str:
		item = cls.CODE_MESSAGES.get(key)
		if item is not None:
			return item["message"]
		return default or f"Unknown key: {key}"

	@classmethod
	def get_code(cls, key: int, default: str = None) -> str:
		item = cls.CODE_MESSAGES.get(key)
		if item is not None:
			return item["code"]
		return default or f"UNKNOWN_CODE_{key}"

	@classmethod
	def get_link(cls, key: int, default: str = None) -> str:
		item = cls.CODE_MESSAGES.get(key)
		if item is not None:
			return item["link"]
		return default or f"UNKNOWN_CODE_{key}"
