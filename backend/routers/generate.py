from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from schemas.nippou import GenerateRequest
from services.docx_service import generate_docx

router = APIRouter()


@router.post("/generate")
async def generate_report(request: GenerateRequest):
    if request.shift_pattern not in ("normal", "late"):
        raise HTTPException(status_code=400, detail="shift_pattern は 'normal' または 'late' を指定してください")

    try:
        docx_bytes = generate_docx(
            request.date, request.shift_pattern, request.slots,
            department=request.department, name=request.name,
            notes=request.notes,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Word生成に失敗しました: {e}")

    # ファイル名: 業務日報_YYYY_MM_DD.docx
    date_parts = request.date.split("-")
    filename = f"業務日報_{date_parts[0]}_{date_parts[1]}_{date_parts[2]}.docx"

    encoded_filename = quote(filename)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
    )
