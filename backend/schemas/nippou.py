from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    date: str = Field(description="対象日付 (YYYY-MM-DD)")
    shift_pattern: str = Field(description="勤務パターン: 'normal' or 'late'")
    text: str = Field(description="業務内容の自由記述テキスト")


class ParseResponse(BaseModel):
    shift_pattern: str
    slots: dict[str, str | None]


class GenerateRequest(BaseModel):
    date: str = Field(description="対象日付 (YYYY-MM-DD)")
    shift_pattern: str = Field(description="勤務パターン: 'normal' or 'late'")
    slots: dict[str, str | None] = Field(description="時間スロットごとの業務内容")
    department: str = Field(default="", description="所属部署")
    name: str = Field(default="", description="氏名")
    notes: str = Field(default="", description="特記事項")
