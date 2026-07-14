# BRIFO AI

> **B**riefing **R**oom for **I**nvestment & **F**inancial **O**perations
>
> "모든 투자 결정은 브리포에서 시작된다"

BRIFO는 사용자가 투자 회사의 **사장(CEO)** 이 되어 개성 있는 AI 사원 3명(루키·프로·탱커)을 고용하고, 이들의 분석 보고서를 바탕으로 투자 의사결정을 내리는 **게이미피케이션 기반 AI 투자 교육 플랫폼**입니다.

이 저장소는 BRIFO의 **AI 서비스(FastAPI)** 입니다. 카드뉴스 요약, AI 사원 3종의 페르소나 브리핑 생성 등 **LLM 프롬프팅·호출·캐싱**을 담당하는 별도 파이썬 서버로, 백엔드 API 서버([BRIFO-server](https://github.com/Team-BRIFO/BRIFO-server), Spring Boot)의 요청을 받아 결과 JSON을 반환합니다.

## 📖 프로젝트 소개

| 항목 | 내용 |
| ---- | ---- |
| 한 줄 정의 | "나는 사장, AI는 사원. 우리 팀이 분석하고, 내가 결정한다." |
| 분류 | 게이미피케이션 기반 AI 투자 교육 플랫폼 |
| 핵심 컨셉 | 사장(CEO)이 된 사용자가 AI 사원 3명을 고용하고, 분석 보고서로 투자를 결정 |
| 타겟 사용자 | 2030 주식 입문자~중급(1차), 투자 교육에 관심 있는 대학생/사회초년생(2차) |
| 개발 기간 | 2026.06.22 ~ 2026.08.21 (약 9주) |

### 핵심 게임 루프

```
[출근 / 카드뉴스 확인]
        ↓
[사원에게 분석 업무 할당]
        ↓
[AI 사원 보고서 열람 (3명)]
        ↓
[방향 + 확신도 선택]
        ↓
[15:30 장 마감 자동 정산]
        ↓
[AP 획득 + 사원 EXP 증가]
        ↓
[결정 일기 자동 기록]
        ↓
[다음 날 다시 출근]
```

> 자세한 기획·프롬프트·데이터 스펙은 팀 Notion과 기능명세서(BRIFO_MVP_기능명세서)를 기준으로 합니다.

---

## 👥 팀원 및 AI 역할 분담

| 이름 | GitHub | 담당 역할 |
| ---- | ------ | --------- |
|      |        |           |
|      |        |           |

---

## 🎯 담당 범위

| 기능 | 엔드포인트 | 설명 |
| ---- | ---------- | ---- |
| 카드뉴스 요약 | `POST /ai/news/summarize` | 뉴스 원문을 5W1H 객관 사실 카드로 요약(+주식 용어 추출). 원문은 메모리에서만 처리 |
| AI 사원 브리핑 | `POST /ai/briefing/generate` | 루키·프로·탱커 3종을 병렬 호출해 사원별 분석 보고서 생성 |
| 헬스 체크 | `GET /ai/health` | 서버 상태 확인 |

- LLM은 **사원별 차등**으로 사용합니다: 루키 `Claude Haiku 4.5` · 탱커 `Claude Sonnet 4.6` · 프로 `Claude Opus 4.x`, 카드뉴스 요약·개인화는 `Gemini 3 Flash`. 라우팅은 **OpenRouter** 를 통합니다(primary/fallback 정책).
- 동일 입력(뉴스 × 사원타입 × 레벨대)은 Redis 캐싱으로 LLM 호출을 1회로 묶어 비용을 통제합니다.

---

## 🛠 기술 스택

| 분류 | 기술 |
| ---- | ---- |
| 언어 / 런타임 | `Python 3.11+` |
| 프레임워크 | `FastAPI` + `Uvicorn`(standard) |
| HTTP 클라이언트 | `httpx` (공유 AsyncClient) |
| LLM 라우팅 | `OpenRouter` (primary/fallback 모델 정책) |
| 설정 | `pydantic-settings` (환경 변수 관리) |
| 캐시 | `Redis` |
| 패키지 관리 | `uv` (`pyproject.toml`) |
| 배포 | `Dockerfile` · `GCP Cloud Run` · `GitHub Actions` |

---

## 📁 폴더 구조

```
app/
├── main.py             # FastAPI 진입점 (lifespan: HTTP/Redis 클라이언트, 라우터·예외 핸들러 등록)
├── api/                # HTTP 입구 (health · briefing · news · deps) — 로직 없음
├── schemas/            # 백엔드와 주고받는 Pydantic Request/Response 모델
├── core/
│   ├── agents/         # agent_profiles · model_policy · prompt_builder · llm_router
│   └── services/       # briefing_service · summary_service (use-case 흐름)
├── infra/              # 외부 I/O — http_client · openrouter_client · cache · usage_tracker
├── config/settings.py  # pydantic-settings 기반 환경 변수
└── exceptions.py       # 공통 커스텀 예외
```

- **레이어 규칙**: `api → core/services → core/agents · infra`. 라우터에는 로직을 두지 않고 요청/응답 검증만, LLM 호출·프롬프트 조립은 `core`에, 외부 통신은 `infra`에 둡니다.
- **출력 규칙**: LLM 응답은 정해진 JSON 스키마로만 파싱하며 Pydantic 모델로 검증합니다.
- 각 모듈의 상세 역할은 저장소 내 [`docs/project-structure.md`](docs/project-structure.md)를 기준으로 합니다.

---

## 🌿 컨벤션

- **브랜치**: Git Flow — `main`(배포) / `dev`(개발 통합), 작업 브랜치는 `dev`에서 분기해 `dev`로 병합. 브랜치명 `{type}/{issue-number}-{summary}`.
- **이슈 / 커밋 / PR**: `[Type] 제목` 이슈, `{type}: {subject}` 커밋(`feat`/`fix`/`refactor`/`docs`/`chore`/`test` 등), PR은 `.github` 템플릿 사용 후 리뷰어·라벨 설정.

---

## 🚀 실행 방법

```bash
# 1. 저장소 클론
git clone https://github.com/Team-BRIFO/BRIFO-ai.git
cd BRIFO-ai

# 2. 의존성 설치 (uv)
uv sync

# 3. 환경 변수 설정 (.env — OPENROUTER_API_KEY, REDIS_URL 등, 커밋 금지)

# 4. 개발 서버 실행
uv run uvicorn app.main:app --reload
```

- 실행 후 API 문서(Swagger UI): `http://localhost:8000/docs`
- 배포는 `Dockerfile`로 컨테이너 빌드 후 GCP Cloud Run에 올립니다.
- LLM API 키(OpenRouter), Redis 접속 정보 등 민감 정보는 커밋 금지 — `.env`로 관리합니다.
