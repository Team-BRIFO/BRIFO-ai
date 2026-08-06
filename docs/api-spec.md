# BRIFO AI Service API 명세서
 
FastAPI AI 서비스는 외부에 노출되지 않는 내부 서비스입니다. Spring Boot 백엔드가 `AI_INTERNAL_API_KEY` 헤더 인증을 통해서만 호출합니다.

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
| AUTH401 | 401 | 내부 API 키 누락 또는 불일치 | 유효하지 않은 내부 API 키입니다. |
| USER404 | 404 | 사용자를 찾을 수 없음 | 사용자를 찾을 수 없습니다. |
| NEWS404 | 404 | 카드뉴스를 찾을 수 없음 | 카드뉴스를 찾을 수 없습니다. |
| AGENT400 | 400 | 유효하지 않은 사원 유형 | 유효하지 않은 사원 유형입니다. |
| BRIEFING502 | 502 | AI 분석 실패 | AI 분석 생성에 실패했습니다. |
| COMMON400 | 400 | 필수 필드 누락 | 잘못된 요청입니다. |

---
 
## 1. 카드뉴스 요약 생성
 
뉴스 원문을 받아 카드뉴스(헤드라인 + 포인트 + 키워드 + 용어 설명) 1건을 생성합니다. `(newsId, excludeTerms)` 기준 24h Redis 캐시 적용.
 
**`POST /ai/news/summarize`**
 
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
 
- `points.length`는 정확히 3
- `keywords.length`는 `terms.length`와 같아야 하며, 2~3개 범위(빈 배열 불가, 최대 3개 - `CardNewsItem` validator에서 검증)
- `cardNews` 배열은 정확히 1개 원소만 허용 (`CardNewsResult`의 `min_length`/`max_length` 제약)
- 위 제약을 위반하면 `ValidationError` → `InvalidLLMResponse`(`BRIEFING502`)로 매핑
---
 
## 2. 사원 브리핑 생성
 
카드뉴스 1건 이상(`newsCard`)에 대해 여러 AI 사원(ROOKIE/TANKER/PRO)의 분석 브리핑과, 유저별 개인화 코멘트를 함께 생성합니다.

- 캐시 키는 요청 바디에 없는 서버 내부 파생값인 `cache_id`(정렬된 `newsCard` 배열을 직렬화해 만든 SHA256 해시)를 기준으로 합니다. `briefingId`는 `{cache_id}:{agentType}:{levelRange}` 형식입니다.
- 공통 분석: `briefing:{cache_id}:{agentType}:{levelRange}` 키로 24h 캐시.
- 개인화 코멘트: `briefing:personal:{userId}:{briefingId}` (= `briefing:personal:{userId}:{cache_id}:{agentType}:{levelRange}`) 키로 다음 정산 시각(15:30 KST)까지 캐시.
 
**`POST /ai/briefing/generate`**
 
### Request
 
```json
{
  "newsCard": [
    {
      "cardId": "string",
      "newsId": "string",
      "headline": "string",
      "points": ["string"]
    }
  ],
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
| newsCard | NewsCard[] | ✅ | 브리핑 대상 카드뉴스 목록 (1개 이상). 카드가 여러 장이면 공통된 흐름 하나로 종합 분석 |
| newsCard[].cardId | string | ✅ | 카드뉴스 카드 식별자 |
| newsCard[].newsId | string | ✅ | 원본 뉴스 식별자. 서버가 이 값으로 카드뉴스 요약 캐시를 조회해 최신 headline/points로 치환한 뒤 분석한다(캐시 미스 시 요청값 그대로 사용) |
| newsCard[].headline | string | ✅ | 카드뉴스 헤드라인 |
| newsCard[].points | string[] | ✅ | 카드뉴스 핵심 포인트 |
| userId | string | ✅ | 요청 유저 식별자 |
| agentTypes | `("ROOKIE"\|"TANKER"\|"PRO")[]` | ✅ | 요청할 사원 목록 (1개 이상) |
| levelRange | string | ✅ | 유저 레벨 구간. `"1-3"` / `"4-6"` / `"7-10"` 중 하나만 허용 |
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
    "briefings": [
      {
        "agentType": "ROOKIE",
        "direction": "UP",
        "confidenceRate": 72,
        "headline": "string",
        "summary": "string",
        "contentText": "string",
        "oneLiner": "string",
        "modelName": "string",
        "cached": false,
        "personalComment": "string",
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
| confidenceRate | int (0~100) | direction 판단에 대한 확신도 (예상 수익률 아님) |
| headline | string | 한 줄 결론 |
| summary | string | 짧은 요약 (1~2문장, 60자 이내) |
| contentText | string | 긴 분석 본문 (사원별 글자수 제한 상이) |
| oneLiner | string | 사원 페르소나의 마지막 한마디 |
| modelName | string | 실제 응답 생성에 사용된 모델 (primary 실패 시 fallback 모델명) |
| cached | boolean | 공통 분석 캐시 히트 여부 |
| personalComment | string \| null | 개인화 코멘트 (최근 결정 이력 기반 1~2문장) |
| personalCached | boolean | 개인화 코멘트 캐시 히트 여부 |

---
 
## 3. Health check
 
**`GET /ai/health`**
 
### Response `200`
 
```json
{
  "isSuccess": true,
  "code": "COMMON200",
  "message": "OK",
  "result": null
}
```