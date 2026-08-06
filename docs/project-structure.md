# Project Structure

BRIFO AI 서비스(FastAPI)의 디렉토리 구조 및 각 모듈의 역할을 정리한 문서입니다.

---

## 디렉토리 트리

```
.
├── .github/
├── docs/
├── tests/
├── logs/
│   └── llm_usage.jsonl
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── deps.py
│   │   ├── health.py
│   │   ├── briefing.py
│   │   └── news.py
│   ├── schemas/
│   │   ├── briefing.py
│   │   └── news.py
│   ├── core/
│   │   ├── agents/
│   │   │   ├── agent_profiles.py
│   │   │   ├── llm_router.py
│   │   │   ├── prompt_builder.py
│   │   │   ├── briefing_api.py
│   │   │   └── llm_response.py
│   │   └── services/
│   │       ├── briefing_service.py
│   │       └── summary_service.py
│   ├── infra/
│   │   ├── http_client.py
│   │   ├── redis_client.py
│   │   ├── openrouter_client.py
│   │   ├── cache.py
│   │   └── usage_tracker.py
│   ├── exceptions.py
│   └── config/
│       └── settings.py
├── pyproject.toml
├── uv.lock
├── .env
├── .gitignore
├── .dockerignore
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

---

### `schemas/` — DTO 정의

백엔드(Spring Boot)와 주고받는 Request/Response 모델을 Pydantic `BaseModel` 기반으로 관리합니다.

| 파일 | 설명 |
|------|------|
| `briefing.py` | 브리핑 요청/응답 스키마 |
| `news.py` | 카드뉴스 요약 요청/응답 스키마 |

---

### `core/` — 핵심 비즈니스 로직

#### `core/agents/` — AI 사원 및 모델 정책

| 파일 | 설명 |
|------|------|
| `agent_profiles.py` | ROOKIE, TANKER, PRO의 성향·분석 프레임·용도별 작성 규칙(`summary_rules`/`content_rules`/`one_liner_rules`)·레벨 효과 관리 |
| `llm_router.py` | 브리핑(사원별)/개인화/카드뉴스 요약용 primary·fallback 모델 정책표 관리 및 선택 함수 제공 |
| `prompt_builder.py` | `agent_profiles` 설정을 기반으로 브리핑·개인화 코멘트 최종 프롬프트 생성 |
| `briefing_api.py` | 프롬프트 생성 → 모델 선택 → LLM 호출 → 응답 파싱·검증까지 브리핑/개인화 생성의 외부 연동 인터페이스 |
| `llm_response.py` | LLM 응답에서 Markdown 코드펜스를 제거하는 등 응답 파싱 공용 헬퍼 |

#### `core/services/` — Use-case 흐름

| 파일 | 설명 |
|------|------|
| `briefing_service.py` | Redis 캐시 확인 후 ROOKIE·TANKER·PRO를 `asyncio.gather`로 동시 호출하여 브리핑 취합 |
| `summary_service.py` | 카드뉴스 요약 로직 |

---

### `infra/` — 외부 I/O 전용 모듈

외부 시스템(OpenRouter, Redis, HTTP)과의 통신을 전담합니다.

| 파일 | 설명 |
|------|------|
| `http_client.py` | OpenRouter 전용 공유 `httpx.AsyncClient` 관리 (lifespan에서 생성·종료) |
| `redis_client.py` | 공유 `redis.asyncio.Redis` 클라이언트 관리 (lifespan에서 생성·종료) |
| `openrouter_client.py` | `http_client`의 공유 클라이언트로 OpenRouter LLM 호출, primary 실패 시 fallback 1회 재시도 |
| `cache.py` | `redis_client`를 이용한 Redis 캐싱 담당 (공통 분석 24h, 카드뉴스 요약 24h, 개인화 코멘트는 다음 정산 시각까지) |
| `usage_tracker.py` | LLM 사용량·비용·지연시간 등을 `logs/llm_usage.jsonl`에 기록 |

---

### 기타

| 파일/디렉토리 | 설명                                                                   |
|--------------|----------------------------------------------------------------------|
| `exceptions.py` | 공통 커스텀 예외 정의 (`LLMTimeout`, `RateLimit`, `AllModelsFailed`, `InvalidLLMResponse` 등)   |
| `config/settings.py` | `pydantic-settings` 기반 환경변수 관리 (`AI_INTERNAL_API_KEY`, `OPENROUTER_API_KEY`, `REDIS_URL` 등) |
| `pyproject.toml` / `uv.lock` | uv 기반 패키지 관리 설정 및 락파일                                                      |
| `.env` | 환경변수 실제 값 (커밋 금지)                                                    |
| `.gitignore` / `.dockerignore` | Git / Docker 빌드 컨텍스트 추적 제외 파일 설정                                                      |
| `Dockerfile` | 배포용 컨테이너 빌드 설정 (uv 기반 멀티스테이지 빌드, `PORT` 환경변수로 리스닝 포트 지정, 기본값 8000)                                         |
| `logs/` | `usage_tracker.py`가 기록하는 LLM 사용량 로그(`llm_usage.jsonl`) 저장 위치                                                           |
| `tests/` | 테스트 코드 모음                                                           |
| `docs/` | 프로젝트 문서 모음                                                           |
| `.github/` | GitHub PR, ISSUE 템플릿                                                 |