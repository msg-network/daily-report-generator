from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    date: str = Field(description="対象日付 (YYYY-MM-DD)")
    shift_pattern: str = Field(description="勤務パターン: 'normal' or 'late'")
    text: str = Field(description="業務内容の自由記述テキスト")


class ParseResponse(BaseModel):
    shift_pattern: str
    slots: dict[str, str | None]


class FromCommitsRequest(BaseModel):
    date: str = Field(description="対象日付 (YYYY-MM-DD)")
    shift_pattern: str = Field(description="勤務パターン: 'normal' or 'late'")
    repos: list[str] | None = Field(
        default=None, description="対象リポジトリ owner/name のリスト（未指定なら backend デフォルト）"
    )


class CalendarEvent(BaseModel):
    title: str
    start: str = Field(description="開始時刻 (ISO 8601, JST)")
    end: str = Field(description="終了時刻 (ISO 8601, JST)")


class FromCommitsResponse(BaseModel):
    shift_pattern: str
    slots: dict[str, str | None]
    commits_summary: str = Field(description="Bedrock に投げたコミット整形テキスト（デバッグ用）")
    calendar_events: list[CalendarEvent] = Field(default_factory=list, description="対象日のカレンダー予定")


class GenerateRequest(BaseModel):
    date: str = Field(description="対象日付 (YYYY-MM-DD)")
    shift_pattern: str = Field(description="勤務パターン: 'normal' or 'late'")
    slots: dict[str, str | None] = Field(description="時間スロットごとの業務内容")
    department: str = Field(default="", description="所属部署")
    name: str = Field(default="", description="氏名")
    notes: str = Field(default="", description="特記事項")
