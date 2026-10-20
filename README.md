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
KAKAO_AUTH_CLIENT_SECRET=카카오_Client_Secret
KAKAO_AUTH_REDIRECT_URI=https://rollpe.mooo.com/api/user/social/login/kakao/callback
KAKAO_AUTH_RETURN_URLS=http://localhost:8081/auth/kakao
```

- 카카오는 해당 REST API 키의 클라이언트 시크릿을 활성화하고, 최초 계정 연결에 사용할 이메일 동의항목을 설정합니다. 네이티브 앱 키와 REST API 키를 구분합니다.
- 기존 서버 환경변수를 재사용할 수 있도록 Google 웹 ID는 `WEB_GOOGLE_OAUTH_CLIENT_KEY`, 시크릿은 기존 이름인 `GOOGLE_OAUTH_CLIENT_ID`, 카카오 REST API 키는 `SOCIAL_AUTH_KAKAO_CLIENT_ID`를 대체값으로 읽습니다. 위의 새 이름을 설정하면 새 값이 우선합니다. 기존 Google iOS ID 설정은 바꾸지 않습니다.
- `*_AUTH_RETURN_URLS`는 인증 후 돌아갈 **클라이언트 주소** 허용 목록입니다. 쉼표로 구분하며 실제 웹 배포 후 해당 도메인의 `/auth/google`, `/auth/kakao`를 각각 추가합니다. 쿼리 문자열·fragment가 없는 정확한 복귀 주소를 사용합니다. 등록된 HTTP(S) origin만 해당 API의 CORS 허용 목록에도 추가됩니다.
- 향후 Android 브라우저 로그인을 연결하면 각각 `reactnativerollpe://auth/google`, `reactnativerollpe://auth/kakao`를 해당 허용 목록에 추가합니다. 개발자 콘솔의 서버 콜백 주소는 그대로 유지합니다.
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
2. 서버의 기존 키를 사용해 `APPLE_AUTH_TEAM_ID`, `APPLE_AUTH_KEY_ID`, `APPLE_AUTH_PRIVATE_KEY_FILE`을 설정합니다. 기존 iOS API에는 `APP_APPLE_BUNDEL_ID`도 필요합니다. 키 파일은 저장소와 Expo 환경변수에 넣지 않습니다.
3. `APPLE_AUTH_TOKEN_ENCRYPTION_KEYS`에 서버에서 생성한 Fernet 키를 설정합니다. Apple 토큰 응답을 DB에 암호화해 보관하는 용도이며, `.p8` 키와는 별개입니다. 쉼표로 여러 키를 지정하면 첫 번째 키로 암호화하고 나머지 키도 복호화에 사용합니다. 기존 토큰을 읽을 수 있도록 키를 백업하고 교체 시 이전 키도 유지합니다.
4. `APPLE_AUTH_RETURN_URLS`에는 서버 검증 후 돌아갈 앱·웹 주소만 정확히 나열합니다. 로컬 웹은 `http://localhost:8081/auth/apple`, 네이티브 앱은 `reactnativerollpe://auth/apple`입니다. 실제 웹 도메인 배포 시 해당 도메인의 `/auth/apple`을 추가합니다.
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
python manage.py test user.tests.test_social_browser user.tests.test_apple_browser user.tests.test_apple_sessions user.tests.test_signin user.tests.test_logout user.tests.test_change_password user.tests.test_signup --settings=config.test_settings
python manage.py makemigrations --check --dry-run --settings=config.test_settings
```
