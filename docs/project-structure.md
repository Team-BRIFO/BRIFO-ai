# Project Structure

BRIFO AI 서비스(FastAPI)의 디렉토리 구조 및 각 모듈의 역할을 정리한 문서입니다.

---

## 디렉토리 트리

```
app/
├── .github/
├── docs/
├── main.py
├── api/
│   ├── deps.py
│   ├── health.py
│   ├── briefing.py
│   ├── news.py
│   └── feedback.py
├── schemas/
│   ├── briefing.py
│   ├── news.py
│   └── feedback.py
├── core/
│   ├── agents/
│   │   ├── agent_profiles.py
│   │   ├── model_policy.py
│   │   ├── prompt_builder.py
│   │   └── llm_router.py
│   └── services/
│       ├── briefing_service.py
│       ├── summary_service.py
│       └── feedback_service.py
├── infra/
│   ├── http_client.py
│   ├── openrouter_client.py
│   ├── cache.py
│   └── usage_tracker.py
├── exceptions.py
├── config/
│   └── settings.py
├── pyproject.toml
├── .env
├── .gitignore
└── Dockerfile
```

---

## 모듈별 역할

### `main.py`
FastAPI 앱 진입점.
- lifespan에서 공유 HTTP 클라이언트와 Redis 클라이언트를 생성하고 종료
- 라우터 등록 및 전역 예외 핸들러 등록

---

### `api/` — HTTP 입구 레이어

HTTP 요청을 받아 `core/services`로 위임하는 레이어. 비즈니스 로직은 포함하지 않습니다.

| 파일 | 엔드포인트 | 설명 |
|------|-----------|------|
| `deps.py` | - | `settings`, HTTP 클라이언트, 캐시 등 공유 의존성 주입 |
| `health.py` | `GET /ai/health` | 서버 상태 확인 |
| `briefing.py` | `POST /ai/briefing/generate` | ROOKIE, TANKER, PRO 브리핑 생성 요청 처리 |
| `news.py` | `POST /ai/news/summarize` | 카드뉴스 요약 요청 처리 |
| `feedback.py` | `POST /ai/personal-feedback/generate` | 사용자 최근 결정 기반 개인화 피드백 요청 처리 |

---

### `schemas/` — DTO 정의

백엔드(Spring Boot)와 주고받는 Request/Response 모델을 Pydantic `BaseModel` 기반으로 관리합니다.

| 파일 | 설명 |
|------|------|
| `briefing.py` | 브리핑 요청/응답 스키마 |
| `news.py` | 카드뉴스 요약 요청/응답 스키마 |
| `feedback.py` | 피드백 요청/응답 스키마 |

---

### `core/` — 핵심 비즈니스 로직

#### `core/agents/` — AI 사원 및 모델 정책

| 파일 | 설명 |
|------|------|
| `agent_profiles.py` | ROOKIE, TANKER, PRO의 성향·분석 프레임·말투·`prompt_version` 관리 |
| `model_policy.py` | primary/fallback 모델 정책 관리 |
| `prompt_builder.py` | `agent_profiles` 설정을 기반으로 최종 프롬프트 생성 (고정 프롬프트 + 동적 입력) |
| `llm_router.py` | `model_policy.py`의 정책표를 읽어 primary/fallback 모델을 반환 |

#### `core/services/` — Use-case 흐름

| 파일 | 설명 |
|------|------|
| `briefing_service.py` | Redis 캐시 확인 후 ROOKIE·TANKER·PRO를 `asyncio.gather`로 동시 호출하여 브리핑 취합 |
| `summary_service.py` | 카드뉴스 요약 로직 |
| `feedback_service.py` | 최근 결정 3건과 현재 브리핑 결과를 반영한 개인화 피드백 생성 |

---

### `infra/` — 외부 I/O 전용 모듈

외부 시스템(OpenRouter, Redis, HTTP)과의 통신을 전담합니다.

| 파일 | 설명 |
|------|------|
| `http_client.py` | 공유 `httpx.AsyncClient` 관리 (lifespan에서 생성·종료) |
| `openrouter_client.py` | OpenRouter API 호출 담당 |
| `cache.py` | Redis 캐싱 담당 |
| `usage_tracker.py` | LLM 사용량 및 성능 기록 담당 |

---

### 기타

| 파일/디렉토리 | 설명                                                                   |
|--------------|----------------------------------------------------------------------|
| `exceptions.py` | 공통 커스텀 예외 정의 (`LLMTimeout`, `RateLimitError`, `AllModelsFailed` 등)   |
| `config/settings.py` | `pydantic-settings` 기반 환경변수 관리 (`OPENROUTER_API_KEY`, `REDIS_URL` 등) |
| `pyproject.toml` | uv 기반 패키지 관리 설정                                                      |
| `.env` | 환경변수 실제 값 (커밋 금지)                                                    |
| `.gitignore` | Git 추적 제외 파일 설정                                                      |
| `Dockerfile` | 배포용 컨테이너 빌드 설정                                         |
| `docs/` | 프로젝트 문서 모음                                                           |
| `.github/` | GitHub PR, ISSUE 템플릿                                                 |