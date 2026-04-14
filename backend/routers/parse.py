from fastapi import APIRouter, HTTPException

from schemas.nippou import ParseRequest, ParseResponse
from services.bedrock_service import parse_work_content

router = APIRouter()


@router.post("/parse", response_model=ParseResponse)
async def parse_text(request: ParseRequest):
    if request.shift_pattern not in ("normal", "late"):
        raise HTTPException(status_code=400, detail="shift_pattern は 'normal' または 'late' を指定してください")

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="業務内容を入力してください")

    try:
        result = parse_work_content(request.date, request.shift_pattern, request.text)
        return ParseResponse(
            shift_pattern=request.shift_pattern,
            slots=result["slots"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI解析に失敗しました: {e}")
