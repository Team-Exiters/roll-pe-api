# roll-pe-api

## Google·카카오 브라우저 로그인

기존 iPhone용 `POST /api/user/social/login/google`, `POST /api/user/social/login/kakao`는 그대로 유지합니다. 웹용 인증은 아래 경로를 사용합니다. `{provider}`는 `google` 또는 `kakao`입니다.

- `GET /api/user/social/login/{provider}/start`: `return_url`, `state`, `code_challenge`(S256)를 받고 인증 페이지로 이동합니다.
- `GET /api/user/social/login/{provider}/callback`: 제공자의 인증 응답을 검증하고 클라이언트 복귀 주소로 일회용 교환 코드를 보냅니다.
- `POST /api/user/social/login/{provider}/exchange`: JSON의 `code`, `code_verifier`를 검증한 뒤 기존 형식의 `data.access`, `data.refresh`, `data.user`를 반환합니다.

개발자 콘솔에 등록할 **서버 콜백 주소**:

| 서비스 | Redirect URI |
| --- | --- |
| Google 웹 OAuth 클라이언트 | `https://rollpe.mooo.com/api/user/social/login/google/callback` |
| 카카오 REST API 키 | `https://rollpe.mooo.com/api/user/social/login/kakao/callback` |

운영 서버의 기존 `rollpe/.env`에 다음 항목을 설정합니다. Google Client Secret과 카카오 Client Secret은 서버 전용이며 Expo의 `EXPO_PUBLIC_` 환경변수에 넣지 않습니다.

```dotenv
GOOGLE_AUTH_CLIENT_ID=발급받은_Google_웹_Client_ID
GOOGLE_AUTH_CLIENT_SECRET=발급받은_Google_Client_Secret
GOOGLE_AUTH_REDIRECT_URI=https://rollpe.mooo.com/api/user/social/login/google/callback
GOOGLE_AUTH_RETURN_URLS=http://localhost:8081/auth/google

KAKAO_AUTH_CLIENT_ID=카카오_REST_API_키
KAKAO_AUTH_APP_ID=카카오_숫자_앱_ID
KAKAO_AUTH_CLIENT_SECRET=카카오_Client_Secret
KAKAO_AUTH_REDIRECT_URI=https://rollpe.mooo.com/api/user/social/login/kakao/callback
KAKAO_AUTH_RETURN_URLS=http://localhost:8081/auth/kakao
```

- Google은 현재 서버 인가 코드 교환 방식이므로 웹 Client Secret이 필요합니다. Google Identity Services의 ID 토큰을 받아 검증하는 방식은 별도 구현이며 이 서버 콜백 방식과 구분합니다.
- 카카오는 해당 REST API 키의 클라이언트 시크릿 기능이 ON이면 `KAKAO_AUTH_CLIENT_SECRET`에 해당 값을 설정합니다. OFF이면 이 환경변수를 생략하거나 비워둘 수 있으며 토큰 요청에서도 `client_secret`을 생략합니다. 새 REST API 키는 시크릿 기능이 기본 활성화되고, 공식 문서에서도 사용을 권장합니다. 서버가 콘솔 설정을 바꾸지는 않습니다.
- 카카오의 최초 계정 연결에 사용할 이메일 동의항목을 설정합니다. 네이티브 앱 키와 REST API 키를 구분합니다.
- 기존 서버 환경변수를 재사용할 수 있도록 Google 웹 ID는 `WEB_GOOGLE_OAUTH_CLIENT_KEY`, 시크릿은 기존 이름인 `GOOGLE_OAUTH_CLIENT_ID`, 카카오 REST API 키는 `SOCIAL_AUTH_KAKAO_CLIENT_ID`를 대체값으로 읽습니다. 위의 새 이름을 설정하면 새 값이 우선합니다. 기존 Google iOS ID 설정은 바꾸지 않습니다.
- Android 네이티브 Google 로그인은 웹 Client ID를 대상으로 발급된 ID 토큰을 기존 `POST /api/user/social/login/google`에 보냅니다. 서버는 기존 `IOS_GOOGLE_OAUTH_CLIENT_KEY`와 `GOOGLE_AUTH_CLIENT_ID`를 허용 대상으로 검증합니다. Android OAuth Client ID는 앱 패키지·서명 등록용이며 이 ID를 웹 ID 대신 설정하지 않습니다. 네이티브 ID 토큰 검증 자체에는 웹 시크릿이 필요하지 않고, 위 웹 브라우저의 인가 코드 교환에는 필요합니다.
- 네이티브 Google·카카오도 `SocialIdentity`로 웹과 같은 계정을 조회합니다. 기존 같은 공급자의 회원은 검증된 이메일로 최초 연결하고, 이후 공급자의 사용자 ID로 조회합니다. 다른 로그인 방식의 회원과 비활성 회원은 연결하지 않습니다. 기존 iOS 요청 필드(`accessToken`)와 응답 형식은 유지하며 `0006` 이후 새 마이그레이션은 없습니다.
- 네이티브 카카오는 `/v1/user/access_token_info`로 발급 앱 ID·만료 여부·회원번호를 확인한 뒤 사용자 정보를 조회합니다. `KAKAO_AUTH_APP_ID`는 카카오 디벨로퍼스에 표시되는 숫자 앱 ID이며 REST API 키나 네이티브 앱 키가 아닙니다. 이 값이 없으면 네이티브 카카오 로그인은 503으로 거절하므로 기존 iOS 앱을 포함해 서버 배포 전에 설정합니다. 웹은 서버가 직접 인가 코드를 교환하므로 이 추가 설정과 독립적입니다.
- `*_AUTH_RETURN_URLS`는 인증 후 돌아갈 **클라이언트 주소** 허용 목록입니다. 쉼표로 구분하며 실제 웹 배포 후 해당 도메인의 `/auth/google`, `/auth/kakao`를 각각 추가합니다. 쿼리 문자열·fragment가 없는 정확한 복귀 주소를 사용합니다. 등록된 HTTP(S) origin만 해당 API의 CORS 허용 목록에도 추가됩니다.
- 향후 Android 브라우저 로그인을 연결하면 각각 `rollpe://auth/google`, `rollpe://auth/kakao`를 해당 허용 목록에 추가합니다. 개발자 콘솔의 서버 콜백 주소는 그대로 유지합니다.
- 인증 요청과 클라이언트 교환 모두 S256 PKCE로 연결하고, 서버 state는 한 번만 처리합니다. Google은 `openid email profile`만 요청하고 서명·issuer·audience·만료·nonce를 검증합니다. 카카오는 서버가 받은 액세스 토큰으로 사용자 ID와 이메일 인증 여부를 확인합니다.
- 계정은 Google `sub`·카카오 사용자 ID로 식별합니다. 기존 계정과 처음 연결할 때만 같은 제공자의 인증된 이메일을 사용합니다. 다른 제공자/일반 이메일 계정, 이미 다른 subject와 연결된 계정, 비활성 계정에는 자동 연결하지 않습니다. 최초 연결 시 인증된 이메일이 없으면 `email_required`로 실패합니다.
- 제공자 식별자는 SHA-256 해시로 조회하고 중복을 제한하여 DB의 문자열 collation에 관계없이 대소문자를 구분합니다. Google의 `email_verified`는 불리언 `true`와 문서에 명시된 문자열 `"true"`만 인증 완료로 처리합니다.
- Google·카카오의 액세스/리프레시 토큰과 ID 토큰은 이 로그인 흐름에서 DB나 클라이언트에 저장하지 않습니다. 로그인 결과 URL에는 60초 동안 한 번만 교환할 수 있는 코드와 클라이언트 state만 넣습니다. 실패 시 `cancelled`, `authentication_failed`, `email_required`, `account_conflict`, `account_inactive` 중 하나를 반환합니다.
- 인증 요청은 10분 동안 유효합니다. 만료된 `SocialAuthFlow` 레코드는 운영 중 주기적으로 정리합니다. 프록시·애플리케이션 로그에 콜백 쿼리 문자열과 토큰 요청 본문을 기록하지 않습니다.

배포 시 코드와 서버 `.env`를 반영하고, 아래 명령이 성공한 뒤 실행 중인 API를 재시작합니다. `0006`은 인증 상태와 제공자 식별 정보를 위한 두 테이블을 추가하며 기존 회원 데이터를 변경하지 않습니다.

```bash
cd rollpe
python manage.py check
python manage.py migrate
```

실제 로그인에는 클라이언트의 `/auth/google`, `/auth/kakao` 콜백 화면과 위 `start`·`exchange` 호출 연결도 필요합니다. 서버 기능만 배포한 상태에서는 RN 웹의 Google·카카오 버튼이 활성화되지 않습니다.

기준 문서: [Google 웹 OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Google 사용자 식별·토큰 검증](https://developers.google.com/identity/openid-connect/openid-connect), [카카오 REST API](https://developers.kakao.com/docs/ko/kakaologin/rest-api).

## Apple 브라우저 로그인

기존 iOS 로그인 API의 주소와 응답 형식을 유지하며, 웹·Android용 브라우저 인증 경로를 별도로 제공합니다.

- `GET /api/user/social/login/apple/start`: `return_url`, `state`, `code_challenge`(S256)를 받아 Apple 인증 화면으로 이동합니다.
- `POST /api/user/social/login/apple/callback`: Apple의 `form_post` 응답을 검증하고 앱·웹으로 돌아갑니다.
- `POST /api/user/social/login/apple/exchange`: JSON의 `code`, `code_verifier`를 검증하여 기존 로그인 API와 동일한 `data.access`, `data.refresh`, `data.user`를 반환합니다.

배포 전 준비:

1. 서버의 기존 `rollpe/.env`에 `APPLE_AUTH_CLIENT_ID`와 `APPLE_AUTH_REDIRECT_URI`를 설정합니다. Services ID는 Apple Developer에 등록한 실제 값을 사용하며, Apple에 등록한 Return URL은 `https://rollpe.mooo.com/api/user/social/login/apple/callback`입니다.
2. 서버의 기존 키를 사용해 `APPLE_AUTH_TEAM_ID`, `APPLE_AUTH_KEY_ID`, `APPLE_AUTH_PRIVATE_KEY_FILE`을 설정합니다. 네이티브 Client ID는 `APPLE_AUTH_NATIVE_CLIENT_ID=dev.hugesilver.Roll-Pe`로 설정합니다. 기존 `APP_APPLE_BUNDEL_ID`도 대체값으로 지원하며 새 이름이 우선합니다. Team ID는 앱과 연결된 실제 팀(`42NW282TDP`)인지 확인합니다. 키 파일은 저장소와 Expo 환경변수에 넣지 않습니다.
3. `APPLE_AUTH_TOKEN_ENCRYPTION_KEYS`에 서버에서 생성한 Fernet 키를 설정합니다. Apple 토큰 응답을 DB에 암호화해 보관하는 용도이며, `.p8` 키와는 별개입니다. 쉼표로 여러 키를 지정하면 첫 번째 키로 암호화하고 나머지 키도 복호화에 사용합니다. 기존 토큰을 읽을 수 있도록 키를 백업하고 교체 시 이전 키도 유지합니다.
4. `APPLE_AUTH_RETURN_URLS`에는 서버 검증 후 돌아갈 앱·웹 주소만 정확히 나열합니다. 로컬 웹은 `http://localhost:8081/auth/apple`, 네이티브 앱은 `rollpe://auth/apple`입니다. 실제 웹 도메인 배포 시 해당 도메인의 `/auth/apple`을 추가합니다.
5. 코드와 설정을 서버에 반영한 뒤 `python manage.py migrate`로 `0004`·`0005` 마이그레이션을 적용하고 API를 재시작합니다. 기존 회원 데이터는 유지됩니다.
6. Expo의 로컬 `.env.local` 또는 EAS 환경변수에 `EXPO_PUBLIC_API_URL=https://rollpe.mooo.com`을 설정하고, 서버 배포 후 `EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED=true`로 활성화합니다. Crypto/SecureStore를 포함한 네이티브 앱은 새 개발 빌드가 필요합니다.

암호화 키는 서버 터미널에서 생성한 뒤 서버 `.env`에만 보관합니다.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

로그인 요청 상태와 일회용 교환 코드는 데이터베이스에서 검증하므로 여러 서버 프로세스에서도 공유됩니다. 인증 요청은 10분, 완료 후 교환 코드는 60초 동안 유효합니다. 운영 시 만료된 `AppleAuthFlow` 레코드를 주기적으로 정리합니다. 로그인 토큰은 리디렉션 URL에 넣지 않습니다.

## 세션과 회원 탈퇴

- Apple 사용자 식별에는 검증된 `sub`를 사용합니다. 기존 Apple 회원은 검증된 이메일이 일치하고 아직 `sub`가 없는 경우에만 최초 연결합니다. 다른 로그인 제공자의 계정은 자동 연결하지 않습니다.
- Apple이 이메일을 제공하지 않는 계정도 가입할 수 있습니다. 이때 `user.email`은 `null`이며, 일반 이메일 회원가입은 이메일이 계속 필수입니다.
- Apple의 identity/access/refresh token은 암호화해 서버에 보관하고, 클라이언트에는 Roll-pe 토큰만 반환합니다.
- `POST /api/user/token/refresh`는 Apple 계정 상태를 24시간 간격으로 확인합니다. Apple에서 `invalid_grant`가 반환되면 해당 로그인 세션의 기존 access/refresh token을 모두 거부합니다. 일시적인 통신 오류는 계정을 삭제하거나 연결을 해제하지 않고 `503`으로 반환합니다. 확인 시도도 하루 한 번으로 제한되므로 실패 후 바로 사용하려면 다시 로그인합니다.
- `POST /api/user/logout`은 해당 기기의 Roll-pe 로그인 세션을 종료합니다. Apple 동의는 유지하고, 저장된 토큰은 추후 탈퇴 때 함께 폐기합니다.
- `DELETE /api/user/drop-user`는 기존의 `identifyCode`, `refresh`와 인증 헤더를 사용합니다. 저장된 Apple 토큰을 `/auth/revoke`로 폐기한 뒤 모든 Roll-pe refresh token을 무효화하고 회원 데이터를 삭제합니다. Apple 통신 오류가 나면 회원과 토큰을 보존하여 재시도할 수 있습니다.
- 예전 iOS처럼 `identityToken`만 보낸 계정은 폐기에 필요한 Apple 토큰이 없으므로 탈퇴를 완료한 뒤 `data.appleRevocationRequired=true`와 수동 연결 해제 안내를 반환합니다. 새 클라이언트는 기존 Apple 로그인 API에도 `code`와 요청의 `nonce`를 보내 자동 폐기를 지원할 수 있습니다. identityToken만 보낸 세션은 24시간 뒤 다시 로그인해야 합니다.

기존 Apple 계정은 다음 로그인에서 새 세션 형식으로 전환합니다. `sub` 연결 이후에는 이전 형식의 Roll-pe 토큰으로 재인증할 수 없으므로 다른 기기도 다시 로그인해야 합니다. Apple 쪽 연결 해제는 다음 토큰 갱신 시 확인하며, 즉시 알림 방식은 아닙니다.

Expo는 네이티브에서 SecureStore, 웹에서는 현재 탭의 sessionStorage에 인증 결과를 보관합니다. 현재 RN 홈·설정 화면은 이식 전이므로 로그인 성공 후에는 완료 안내까지만 표시합니다. 설정 화면 연결 시 로그아웃·탈퇴 후 로컬 인증 정보도 삭제하고, `appleRevocationRequired=true`이면 Apple 계정에서 수동으로 연결을 해제하도록 안내해야 합니다.

기준 문서: [사용자 검증](https://developer.apple.com/documentation/signinwithapple/verifying-a-user), [계정 삭제와 토큰 폐기](https://developer.apple.com/documentation/technotes/tn3194-handling-account-deletions-and-revoking-tokens-for-sign-in-with-apple).

외부 인증·운영 DB를 사용하지 않는 로컬 검사:

```bash
cd rollpe
python manage.py test --settings=config.test_settings
python manage.py makemigrations --check --dry-run --settings=config.test_settings
```

## 운영 설정 점검과 만료 상태 정리

```bash
cd rollpe
python manage.py check_social_auth
python manage.py cleanup_auth_flows --limit 1000
# 미리보기 확인 후 만료된 지 24시간이 지난 상태만 삭제 (모델별 최대 1000개)
python manage.py cleanup_auth_flows --apply --limit 1000 --older-than-hours 24
```

설정 점검은 값·키 내용을 출력하지 않고 DB나 외부 서버에 접속하지 않습니다. 설정 존재 여부, 키 파일 읽기 가능 여부와 Fernet 키 형식만 확인하므로 실제 인증 성공을 보장하지 않습니다. 기본 Django 설정 로딩에는 기존 운영 환경설정이 필요합니다.

기존 Apple `identityToken` 검증은 공개 JWKS와 네이티브 Client ID를 사용하며 `.p8` 자체는 필요하지 않습니다. 새 네이티브 인가 코드 교환·자동 토큰 폐기에는 Team ID, Key ID, `.p8`, 토큰 암호화 키가 추가로 필요합니다. 브라우저 로그인에는 Services ID·서버 Return URL·클라이언트 복귀 허용 목록도 필요합니다. 네이티브 Client ID 하나만 설정된 상태는 전체 Apple 인증 설정 완료가 아닙니다. 서명·암호화·Client Secret은 서버 전용입니다.

정리 명령은 기본적으로 미리보기입니다. `--apply`는 `AppleAuthFlow`·`SocialAuthFlow`의 만료된 임시 상태만 지우며 회원·제공자 연결·Apple 자격 증명은 보존합니다. 모델별 제한은 1~10000개, 만료 후 보존 기간은 최소 1시간입니다. 실제 운영 실행·주기 등록은 별도로 판단합니다.

## 비밀번호 재설정

이메일 요청(`POST /api/user/forgot-password`)은 유지합니다. 새 메일은 `https://rollpe.mooo.com/api/user/password-reset/{identifyCode}#token=...`으로 연결되고 30분 동안 유효합니다. 설치된 검증 앱은 같은 HTTPS 주소를 재설정 화면으로 열고, 앱이 없거나 연결되지 않으면 기존 Django 서버의 폼에서 완료합니다. 별도 웹 사이트나 RN 웹 배포는 필요하지 않습니다. 토큰은 fragment에만 넣어 서버 요청 URL·접근 로그로 전달하지 않습니다. 커스텀 scheme으로 토큰을 전달하지 않습니다.

재설정 API의 `PATCH /api/user/forgot-password`는 `identifyCode`, `newPassword`, `token`을 요구합니다. 공개 식별자만으로는 변경할 수 없으며 이전 재설정 링크 대신 새 메일을 요청합니다.

## 배포 전 메일 설정

현재 발신 계정은 `projectrollpe@gmail.com`이며 Gmail SMTP(`smtp.gmail.com:587`, TLS)를 사용합니다. **Gmail 앱 비밀번호**는 이 계정으로 서버가 메일을 보낼 때 사용하는 16자리 암호입니다. 새 Gmail 계정을 만들라는 뜻은 아닙니다.

1. `projectrollpe@gmail.com`의 Google 계정에서 **2단계 인증**을 켭니다.
2. 같은 계정의 [앱 비밀번호](https://myaccount.google.com/apppasswords)에서 `Roll-pe 서버` 등의 이름으로 암호를 생성합니다.
3. 이 발신 계정에서 생성한 암호를 서버의 기존 `rollpe/.env` 또는 서버 환경변수 **`EMAIL_HOST_PASSWORD`**에 입력합니다. Google 계정의 일반 로그인 비밀번호를 넣지 않습니다. 앱·`EXPO_PUBLIC_`·Git에 넣거나 채팅으로 공유하지 않습니다.

앱 비밀번호 메뉴가 없다면 계정 정책·보안 설정에 따라 사용이 제한될 수 있습니다. [Google 공식 안내](https://support.google.com/mail/answer/185833?hl=ko)를 확인합니다. Google 계정 비밀번호를 변경하면 앱 비밀번호도 폐기되므로 새 값을 서버에 반영해야 합니다. 이전 저장소에 포함된 SMTP 암호는 교체합니다. 다른 발신 계정의 기존 앱 비밀번호는 새 계정에 사용할 수 없습니다. 로컬 설정은 운영 서버에 자동 반영되지 않습니다.

| 설정 | 필요한 경우 |
| --- | --- |
| `EMAIL_HOST_PASSWORD` | 회원가입 인증·재설정 메일 발송에 필수. 위 발신 계정에서 생성한 앱 비밀번호 |
| `API_DOMAIN` | 필수. 이메일 인증·재설정 링크의 실제 API 호스트를 스킴·경로 없이 지정. 미설정·잘못된 주소이면 시작 중단 |
| `DJANGO_DEBUG=False` | 운영 서버에서는 디버그 비활성화. 미설정 시에도 `False`이며 문자열을 불리언으로 변환 |
| `DJANGO_ALLOWED_HOSTS` | 선택. 쉼표로 구분한 요청 허용 호스트. 미설정 시 API 호스트와 로컬 프록시용 루프백 호스트를 허용하며 `*`는 거부 |
| `ANDROID_APP_LINKS_SHA256_FINGERPRINTS` | Android 앱 자동 열기를 사용할 때 실제 설치 앱의 서명 SHA-256 등록. 미설정이어도 브라우저 재설정 가능 |

현재 발신 주소·SMTP 호스트·포트는 코드 설정이므로 별도 `EMAIL_USER`·`EMAIL_PASSWORD` 환경변수는 사용하지 않습니다. `BASE_DOMAIN`도 새 재설정 메일에는 사용하지 않습니다. 메일 발송과 실제 기기에서의 앱 자동 열기는 배포 후 별도로 확인합니다.

Google·카카오의 서버 콜백 기본 주소와 HTTPS CSRF 허용 주소도 `API_DOMAIN`을 사용합니다. 별도로 등록한 `GOOGLE_AUTH_REDIRECT_URI`·`KAKAO_AUTH_REDIRECT_URI`는 유지합니다. 운영 CSRF 허용 주소에서 예전 도메인을 제거했으며 로컬 개발용 주소는 `DJANGO_DEBUG=True`일 때만 추가합니다. 설정을 바꾼 뒤에는 Gunicorn을 리로드합니다.

## 요청 처리 변경

- 회원가입은 권한 필드와 `is_test`를 무시하고 항상 이메일 인증을 요구합니다. 메일 발송 실패 시 회원을 만들지 않고 `503`을 반환합니다.
- 롤페 생성은 로그인한 사용자를 호스트로 지정합니다. `/api/index`의 `POST`는 staff만 사용할 수 있으며 `GET`은 기존 동작을 유지합니다.

## 검증된 앱 링크 배포

iOS는 `42NW282TDP.dev.hugesilver.Roll-Pe`와 `/api/user/password-reset/*`·`/rollpe/*`를 AASA에 등록합니다. Apple Developer에서 해당 App ID의 Associated Domains 기능을 활성화하고 새 네이티브 빌드를 설치해야 합니다. Android는 패키지 `dev.hugesilver.RollPe`의 **실제 설치 앱 서명 인증서 SHA-256**이 필요합니다. EAS 빌드 인증서 또는 Play App Signing을 사용하는 경우 Play의 앱 서명 인증서와 일치시킵니다. 업로드 키와 혼동하지 않습니다.

초대 링크는 `https://api.example.com/rollpe/<UUID>` 형식입니다. RN은 `EXPO_PUBLIC_WEB_URL`에 배포된 HTTPS 웹 주소가 있으면 우선 사용하고, 없으면 `EXPO_PUBLIC_API_URL`을 사용합니다. 별도 웹 배포 없이 API 서버의 같은 경로를 사용할 수 있습니다. 검증된 앱 링크는 OS가 앱으로 직접 전달합니다. 브라우저로 열린 경우에는 흰 화면에서 iOS·Android 앱 열기를 한 번 시도하며, 로고·문구·버튼은 표시하지 않습니다. 브라우저가 자동 실행을 차단하거나 앱이 미설치된 경우 흰 화면에 남을 수 있습니다. 데스크톱·백그라운드 문서에서는 앱을 자동 실행하지 않고, 반복 실행이나 설치 여부 추적도 하지 않습니다. 페이지는 DB·인증·외부 서비스에 접근하지 않으며, 조회만으로 초대 수락이나 참가를 실행하지 않습니다. 앱에서는 기존 로그인 및 참가 확인을 거칩니다. 앱 미설치 시 설치 후 원래 링크를 다시 열어야 하며 설치 과정에서 초대를 자동 복원하지 않습니다.

RN은 API 도메인의 재설정·초대 경로와, 별도 웹 도메인이 설정된 경우 그 도메인의 초대 경로를 앱 링크로 등록합니다. 웹 도메인을 따로 쓰면 그 **웹 도메인**의 `/.well-known/`에도 동일한 앱 연결 메타데이터를 제공해야 합니다. API 도메인에만 등록한 것으로 별도 웹 도메인이 검증되지는 않습니다.

서버 `ANDROID_APP_LINKS_SHA256_FINGERPRINTS`에는 `AA:BB:...` 형식의 32바이트 지문을 쉼표로 구분해 설정합니다. 미설정·잘못된 형식이면 `assetlinks.json`은 빈 배열을 반환하고 Android 자동 열기를 허용하지 않습니다. 브라우저 폼은 계속 사용할 수 있습니다. 로컬 생성 프로젝트의 debug 서명은 배포/EAS/Play 서명을 증명하지 않으므로 자동 등록하지 않았습니다.

Nginx가 `/api`만 Django로 전달한다면 기존 API 설정을 유지하고 아래 메타데이터 두 경로와 초대 안내 경로도 같은 Django upstream으로 전달합니다. `http://127.0.0.1:8000`은 현재 API의 `proxy_pass` 대상이 다르면 그 값으로 맞춥니다. 별도 RN 웹 사이트가 `/rollpe/`를 제공하는 호스트에서는 그 웹 라우트를 유지합니다.

```nginx
location = /.well-known/apple-app-site-association {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
location = /.well-known/assetlinks.json {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
location ^~ /rollpe/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

사용자가 배포 후 `sudo nginx -t`로 검사하고 승인한 설정을 반영한 다음 확인합니다. 아래 요청은 비밀값이나 메일 발송 없이 공개 메타데이터만 조회합니다. 두 응답 모두 리디렉션 없는 `200`, `Content-Type: application/json`이어야 합니다.

```bash
curl -i https://rollpe.mooo.com/.well-known/apple-app-site-association
curl -i https://rollpe.mooo.com/.well-known/assetlinks.json
```

앱 설정 변경이 있으므로 새 네이티브 빌드를 설치한 뒤 메일의 재설정 링크와 외부 메신저의 초대 링크를 눌러 iOS·Android의 종료/실행 중 상태를 확인합니다. 미로그인 초대는 로그인 후 원래 롤페로 돌아와 참가 여부를 확인하며, 이미 로그인한 경우 바로 참가 확인으로 이어집니다. 초대 링크가 브라우저로 열리면 흰 배경이어야 하며, 자동 실행이 차단되더라도 반복 실행되지 않아야 합니다. Apple CDN 캐시나 사용자 브라우저 선택에 따라 브라우저가 열릴 수 있으며, 같은 도메인 브라우저 내부 이동만으로 Universal Link 성공을 판단하지 않습니다. Expo Go로 검증하지 않습니다.

기준: [Expo iOS Universal Links](https://docs.expo.dev/linking/ios-universal-links/), [Expo Android App Links](https://docs.expo.dev/linking/android-app-links/), [Apple Associated Domains](https://developer.apple.com/documentation/xcode/supporting-associated-domains), [Android 사이트 연결](https://developer.android.com/training/app-links/configure-assetlinks).

## 참여자 관리와 마음 수정 이력

- `/api/paper/participants`: 방장 전용 GET(목록), POST(`pcode`, `userId`로 초대), DELETE(강퇴). 초대된 사용자는 비공개 롤페도 비밀번호 없이 조회할 수 있습니다. 방장과 지정 수신자는 강퇴할 수 없습니다.
- `/api/paper/leave`: POST(`pcode`)로 본인만 나갑니다. 방장은 나갈 수 없습니다. 나가기·강퇴는 해당 롤페의 본인 마음과 수정 이력을 함께 삭제합니다. 나가기는 재입장을 허용하지만 강퇴는 링크 입장·재초대를 차단합니다.
- 전달 완료 또는 전달일 오전 10시(KST) 이후에는 초대·강퇴·나가기를 막아 완성본을 유지합니다. 참여자 변경과 마음 변경은 동일한 롤페 행을 잠그는 트랜잭션으로 처리합니다.
- `/api/heart/revisions?hcode=...`: 해당 마음의 작성자와 방장만 조회할 수 있습니다. 각 기록에는 `number`(원본 0, 이후 1..N), `content`, `color`, `editor`, `recordedAt`, `baseline`이 있습니다. 내용 또는 색상이 실제로 바뀔 때만 새 기록을 추가합니다. 일반 마음 응답에는 `revisionCount`만 추가되며, 이전 본문은 포함하지 않습니다.
- 기존 마음은 마이그레이션 적용 시점의 내용을 `baseline=true`인 기준본으로 저장합니다. 이미 덮어쓴 과거 원본은 복원할 수 없습니다. Django 관리자에서 마음별 이력을 읽기 전용으로 확인할 수 있습니다.
- 공개 카드 목록에서는 마음 본문과 참여자 명단을 반환하지 않습니다. 상세 조회와 이력 조회의 접근 검사를 목록으로 우회할 수 없도록 합니다.
- 서버 배포 시 `python manage.py migrate`로 `paper.0005_participants_and_heart_history`, `heart.0004_participants_and_heart_history`를 적용한 뒤 Gunicorn을 다시 로드합니다. 새 환경변수나 외부 서비스 설정은 필요하지 않습니다.
