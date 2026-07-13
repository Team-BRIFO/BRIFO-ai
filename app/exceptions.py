class BrifoAIException(Exception):
    """
    BRIFO AI 서버 공통 예외 베이스
    라우터의 exception_handler에서 이 클래스를 잡아 isSuccess/code/message 포맷으로 변환한다.
    """

    code: str = "COMMON500"
    message: str = "서버 내부 오류가 발생했습니다."
    status_code: int = 500

    def __init__(self, message: str | None = None):
        self.message = message or self.message
        super().__init__(self.message)


class Unauthorized(BrifoAIException):
    code = "AUTH401"
    message = "유효하지 않은 토큰입니다."
    status_code = 401


class UserNotFound(BrifoAIException):
    code = "USER404"
    message = "사용자를 찾을 수 없습니다."
    status_code = 404


class InvalidRequest(BrifoAIException):
    code = "COMMON400"
    message = "잘못된 요청입니다."
    status_code = 400


class InvalidAgentType(BrifoAIException):
    code = "AGENT400"
    message = "유효하지 않은 사원 유형입니다."
    status_code = 400


class NewsNotFound(BrifoAIException):
    code = "NEWS404"
    message = "카드뉴스를 찾을 수 없습니다."
    status_code = 404


class LLMTimeout(BrifoAIException):
    code = "BRIEFING502"
    message = "AI 분석 생성에 실패했습니다. (timeout)"
    status_code = 502


class RateLimit(BrifoAIException):
    code = "BRIEFING502"
    message = "AI 분석 생성에 실패했습니다. (rate limit)"
    status_code = 502


class AllModelsFailed(BrifoAIException):
    code = "BRIEFING502"
    message = "AI 분석 생성에 실패했습니다."
    status_code = 502