"""
LLM 응답 파싱 공용 헬퍼
"""


def strip_markdown_fence(content: str) -> str:
    """
    LLM 응답이 ```json ... ``` 형태의 Markdown 코드블록으로 감싸진 경우
    바깥쪽 코드블록 표시를 제거하고 JSON 문자열만 반환한다.

    코드블록 형식이 아니면 앞뒤 공백만 제거한 원문을 반환한다.
    """
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        lines = lines[1:]
        text = "\n".join(lines).strip()
    return text