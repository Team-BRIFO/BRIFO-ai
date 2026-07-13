# BRIFO AI Service API 명세서
 
FastAPI AI 서비스는 외부에 노출되지 않는 내부 서비스입니다. Spring Boot 백엔드가 `X-Internal-API-Key` 헤더 인증을 통해서만 호출합니다.
 
- Base URL: (Cloud Run 배포 URL, 추후 확정)
- 인증: 모든 요청에 `AI_INTERNAL_API_KEY` 헤더 필수
- Content-Type: `application/json`
- 요청 바디: camelCase / 응답 바디: camelCase (Pydantic `alias`, `serialization_alias`로 매핑)
---
 
## 공통 응답 포맷
 
```json
{
  "isSuccess": true,
  "code": "COMMON200",
  "message": "string",
  "result": { }
}
```
 
에러 시 `isSuccess: false`, `result` 없이 `code`/`message`만 반환.
 
---
## 공통 에러 코드

| code | HTTP Status | 상황 | message |
| --- | --- | --- | --- |
| AUTH401 | 401 | Access Token 없음 또는 만료 | 유효하지 않은 토큰입니다. |
| USER404 | 404 | 사용자를 찾을 수 없음 | 사용자를 찾을 수 없습니다. |
| NEWS404 | 404 | 카드뉴스를 찾을 수 없음 | 카드뉴스를 찾을 수 없습니다. |
| AGENT400 | 400 | 유효하지 않은 사원 유형 | 유효하지 않은 사원 유형입니다. |
| BRIEFING502 | 502 | AI 분석 실패 | AI 분석 생성에 실패했습니다. |
| COMMON400 | 400 | 필수 필드 누락 | 잘못된 요청입니다. |

---
 
## 1. 카드뉴스 요약 생성
 
뉴스 원문을 받아 카드뉴스(헤드라인 + 포인트 + 키워드 + 용어 설명) 리스트를 생성합니다. `news_id` 기준 24h 캐시.
 
**`POST /ai/card-news`**
 
### Request
 
```json
{
  "newsId": "string",
  "stockName": "string",
  "newsContent": "string",
  "excludeTerms": ["string"]
}
```
 
| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| newsId | string | ✅ | 원본 뉴스 식별자 |
| stockName | string | ✅ | 관련 종목명 |
| newsContent | string | ✅ | 뉴스 원문 |
| excludeTerms | string[] | - | 이미 설명된 용어 목록 (중복 설명 방지) |
 
### Response `200`
 
```json
{
  "isSuccess": true,
  "code": "COMMON200",
  "message": "카드뉴스 생성에 성공했습니다.",
  "result": {
    "newsId": "string",
    "cardNews": [
      {
        "headline": "string",
        "points": ["string"],
        "keywords": ["string"],
        "terms": [
          { "surface": "string", "term": "string", "definition": "string" }
        ]
      }
    ]
  }
}
```
 
- `keywords.length`는 `points.length`와 같아야 하며, `keywords`는 빈 배열 불가 (`CardNewsItem` validator에서 검증, 위반 시 `ValidationError` → 서비스 레이어에서 `InvalidRequest` 등으로 매핑 필요)
---
 
## 2. 사원 브리핑 생성
 
카드뉴스 1건에 대해 여러 AI 사원(ROOKIE/TANKER/PRO)의 분석 브리핑과, 유저별 개인화 코멘트를 함께 생성합니다. 공통 분석은 `(newsId, agentType, levelRange)` 기준, 개인화 코멘트는 `(userId, briefingId)` 기준으로 각각 24h 캐시.
 
**`POST /ai/briefing/generate`**
 
### Request
 
```json
{
  "news": {
    "newsId": "string",
    "headline": "string",
    "point": ["string"]
  },
  "userId": "string",
  "agentTypes": ["ROOKIE", "TANKER", "PRO"],
  "levelRange": "string",
  "recentDecisions": [
    {
      "stockName": "string",
      "direction": "UP",
      "confidence": 1,
      "isCorrect": true,
      "actualChange": 0.0
    }
  ]
}
```
 
| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| news.newsId | string | ✅ | 카드뉴스 식별자 |
| news.headline | string | ✅ | 카드뉴스 헤드라인 |
| news.point | string[] | ✅ | 카드뉴스 핵심 포인트 |
| userId | string | ✅ | 요청 유저 식별자 |
| agentTypes | `("ROOKIE"\|"TANKER"\|"PRO")[]` | ✅ | 요청할 사원 목록 |
| levelRange | string | ✅ | 유저 레벨 구간 (예: `"1-3"`) |
| recentDecisions | RecentDecision[] | ✅ | 개인화 코멘트 생성용 최근 결정 이력. **Spring Boot가 조회해서 전달** — FastAPI가 DB에서 직접 조회하지 않음 (deprecated 방식) |
 
`recentDecisions[].direction`: `"UP" \| "DOWN" \| "NEUTRAL"`
`recentDecisions[].confidence`: 1~5
`recentDecisions[].isCorrect`, `actualChange`: 정산 완료된 결정만 전달되므로 필수(non-nullable)
 
### Response `200`
 
```json
{
  "isSuccess": true,
  "code": "COMMON200",
  "message": "사원 브리핑 생성에 성공했습니다.",
  "result": {
    "newsId": "string",
    "briefings": [
      {
        "agentType": "ROOKIE",
        "direction": "UP",
        "probability": 0.0,
        "headline": "string",
        "summary": "string",
        "commonAnalysis": "string",
        "closingComment": "string",
        "modelName": "string",
        "cached": false,
        "personalIntro": "string",
        "personalOutro": "string",
        "personalCached": false
      }
    ]
  }
}
```
 
| 필드 | 타입 | 설명 |
|---|---|---|
| agentType | `"ROOKIE"\|"TANKER"\|"PRO"` | 사원 유형 |
| direction | `"UP"\|"DOWN"\|"NEUTRAL"` | 예측 방향 |
| probability | float | 예측 확률 |
| headline / summary / commonAnalysis / closingComment | string | 사원의 공통 분석 텍스트 |
| modelName | string | 실제 응답 생성에 사용된 모델 |
| cached | boolean | 공통 분석 캐시 히트 여부 |
| personalIntro | string \| null | 개인화 도입부 코멘트 |
| personalOutro | string \| null | 개인화 마무리 코멘트 |
| personalCached | boolean | 개인화 코멘트 캐시 히트 여부 |

---
 
## 3. Health check
 
**`GET /internal/health`**
 
### Response `200`
 
```json
{
  "isSuccess": true,
  "code": "COMMON200",
  "message": "OK",
  "result": null
}
```