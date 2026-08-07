from pydantic import BaseModel, Field, model_validator


class CardNewsGenerateRequest(BaseModel):
    news_id: str = Field(alias="newsId")
    stock_name: str = Field(alias="stockName")
    news_content: str = Field(alias="newsContent")
    exclude_terms: list[str] = Field(default_factory=list, alias="excludeTerms")

    model_config = {"populate_by_name": True}


class Term(BaseModel):
    surface: str
    term: str
    definition: str


class CardNewsItem(BaseModel):
    headline: str
    points: list[str]
    keywords: list[str] = Field(max_length=3)
    terms: list[Term] = Field(max_length=3)

    @model_validator(mode="after")
    def _check_lengths(self):
        if len(self.points) != 3:
            raise ValueError("points는 정확히 3개여야 합니다.")
        if len(self.keywords) != len(self.terms):
            raise ValueError("keywords와 terms의 길이가 일치해야 합니다.")
        if not self.keywords:
            raise ValueError("keywords는 비어 있을 수 없습니다.")

        mismatched = [
            (i, kw, t.surface)
            for i, (kw, t) in enumerate(zip(self.keywords, self.terms))
            if kw != t.surface
        ]
        if mismatched:
            details = ", ".join(
                f"index {i}: keywords={kw!r} terms.surface={surface!r}"
                for i, kw, surface in mismatched
            )
            raise ValueError(
                f"keywords[i]는 terms[i].surface와 일치해야 합니다 ({details})."
            )
        return self


class CardNewsResult(BaseModel):
    news_id: str = Field(serialization_alias="newsId")
    card_news: list[CardNewsItem] = Field(
        serialization_alias="cardNews", min_length=1, max_length=1
    )

    model_config = {"populate_by_name": True}


class CardNewsGenerateResponse(BaseModel):
    is_success: bool = Field(serialization_alias="isSuccess", default=True)
    code: str = "COMMON200"
    message: str = "카드뉴스 생성에 성공했습니다."
    result: CardNewsResult

    model_config = {"populate_by_name": True}
