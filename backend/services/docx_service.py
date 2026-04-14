import io
import os
import re
import zipfile
from datetime import datetime

import boto3

TEMPLATE_PATH = os.environ.get(
    "TEMPLATE_PATH",
    os.path.join(os.path.dirname(__file__), "..", "templates", "業務日報テンプレート.docx"),
)
TEMPLATE_BUCKET = os.environ.get("TEMPLATE_BUCKET")
TEMPLATE_KEY = os.environ.get("TEMPLATE_KEY")


def _get_template_bytes() -> bytes:
    """テンプレート docx のバイト列を取得（S3 or ローカル）"""
    if TEMPLATE_BUCKET and TEMPLATE_KEY:
        s3 = boto3.client("s3")
        response = s3.get_object(Bucket=TEMPLATE_BUCKET, Key=TEMPLATE_KEY)
        return response["Body"].read()
    with open(TEMPLATE_PATH, "rb") as f:
        return f.read()

SHIFT_PATTERNS = {
    "normal": {
        "hours": [9, 10, 11, 12, 13, 14, 15, 16, 17],
    },
    "late": {
        "hours": [13, 14, 15, 16, 17, 18, 19, 20, 21],
    },
}

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]

# XML namespace
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _format_date(date_str: str) -> str:
    """YYYY-MM-DD を 'YYYY年M月D日(曜)' 形式に変換"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAY_JA[dt.weekday()]
    return f"{dt.year}年{dt.month}月{dt.day}日({weekday})"


def _build_date_paragraph_xml(date_str: str) -> str:
    """日付部分の <w:p> を丸ごと生成"""
    formatted = f"\u3000\u3000{_format_date(date_str)}"
    return f"""<w:p xmlns:w="{W_NS}" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" w14:paraId="7E29C18F" w14:textId="0F4D235C" w:rsidR="00967BF9" w:rsidRDefault="00686ED5" w:rsidP="00DC119F">
      <w:pPr>
        <w:jc w:val="right"/>
        <w:rPr>
          <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック"/>
          <w:sz w:val="24"/>
        </w:rPr>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック" w:hint="eastAsia"/>
          <w:sz w:val="24"/>
        </w:rPr>
        <w:t xml:space="preserve">{formatted}</w:t>
      </w:r>
    </w:p>"""


def _build_time_cell_xml(hour: int) -> str:
    """時間ラベルセルの内容を生成"""
    hour_str = str(hour)
    return f"""<w:tcPr>
            <w:tcW w:w="831" w:type="dxa"/>
            <w:vAlign w:val="center"/>
          </w:tcPr>
          <w:p xmlns:w="{W_NS}">
            <w:pPr>
              <w:jc w:val="center"/>
              <w:rPr>
                <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック"/>
              </w:rPr>
            </w:pPr>
            <w:r>
              <w:rPr>
                <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック" w:hint="eastAsia"/>
              </w:rPr>
              <w:t>{hour_str}時</w:t>
            </w:r>
          </w:p>"""


def _build_content_cell_xml(content: str | None, merge: str = "none") -> str:
    """業務内容セルの内容を生成
    merge: "none" = 結合なし, "restart" = 結合開始, "continue" = 結合の続き
    """
    merge_xml = ""
    if merge == "restart":
        merge_xml = '\n            <w:vMerge w:val="restart"/>'
    elif merge == "continue":
        merge_xml = "\n            <w:vMerge/>"

    text = content or ""
    # 結合の続き行はテキスト空にする
    if merge == "continue":
        text = ""

    return f"""<w:tcPr>
            <w:tcW w:w="8323" w:type="dxa"/>
            <w:gridSpan w:val="3"/>{merge_xml}
            <w:vAlign w:val="center"/>
          </w:tcPr>
          <w:p xmlns:w="{W_NS}">
            <w:pPr>
              <w:rPr>
                <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック"/>
              </w:rPr>
            </w:pPr>
            <w:r>
              <w:rPr>
                <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック" w:hint="eastAsia"/>
              </w:rPr>
              <w:t>{text}</w:t>
            </w:r>
          </w:p>"""


def _compute_merge_types(hours: list[int], slots: dict[str, str | None]) -> list[str]:
    """各スロットの結合タイプを計算する"""
    contents = [slots.get(str(h)) for h in hours]
    merge_types: list[str] = []

    for i, content in enumerate(contents):
        if content is None:
            # null スロットは前のスロットと同じ内容なら結合の続き
            if i > 0 and merge_types[i - 1] in ("restart", "continue"):
                merge_types.append("continue")
            else:
                merge_types.append("none")
        elif i > 0 and contents[i - 1] == content:
            # 前と同じ内容 → 結合の続き
            merge_types.append("continue")
        else:
            # 新しい内容 → 次のスロットを先読みして結合が必要か判定
            needs_merge = False
            for j in range(i + 1, len(contents)):
                if contents[j] is None:
                    needs_merge = True
                    continue
                if contents[j] == content:
                    needs_merge = True
                break
            merge_types.append("restart" if needs_merge else "none")

    return merge_types


def generate_docx(
    date: str,
    shift_pattern: str,
    slots: dict[str, str | None],
    department: str = "",
    name: str = "",
    notes: str = "",
) -> bytes:
    """テンプレートを元にdocxを生成して bytes で返す"""
    hours = SHIFT_PATTERNS[shift_pattern]["hours"]

    template_bytes = _get_template_bytes()
    with zipfile.ZipFile(io.BytesIO(template_bytes), "r") as zin:
        xml_bytes = zin.read("word/document.xml")
        xml = xml_bytes.decode("utf-8")

        # 0. 所属・氏名を差し替え
        if department:
            xml = re.sub(r"デジタルマーケティング部", department, xml)
        if name:
            # 氏名セルの中央揃えを左揃えに変更してからテキストを差し替え
            # 名前を含む段落を特定して jc=center を除去
            name_pos = xml.find("久保　翔央")
            if name_pos != -1:
                # 名前より前で最も近い <w:p を探す（= 名前を含む段落の開始位置）
                para_start = xml.rfind("<w:p ", 0, name_pos)
                # その段落内の jc=center を除去
                para_end = xml.find("</w:p>", name_pos)
                para_xml = xml[para_start:para_end]
                para_xml = para_xml.replace('<w:jc w:val="center"/>', "")
                xml = xml[:para_start] + para_xml + xml[para_end:]
            xml = re.sub(r"久保　翔央", name, xml)

        # 1. 日付を差し替え
        # 個々の <w:p>...</w:p> ブロックを取得し、jc=right かつ "202" を含むものを特定
        para_pattern = re.compile(r"<w:p [^>]*>.*?</w:p>", re.DOTALL)
        for match in para_pattern.finditer(xml):
            para_xml = match.group()
            if 'w:val="right"' in para_xml and "202" in para_xml:
                new_date_para = _build_date_paragraph_xml(date)
                xml = xml[: match.start()] + new_date_para + xml[match.end() :]
                break

        # 2. 各スロット行を差し替え
        # テーブル行 (w:tr) を全て抽出
        tr_pattern = re.compile(r"<w:tr [^>]*>[\s\S]*?</w:tr>")
        all_rows = list(tr_pattern.finditer(xml))

        # スロット行を特定: w:tcW w:w="831" を含む行（時間ラベルセルがある行）
        # ヘッダー行（「時間」「業務内容」のラベル行）を除外するため、
        # 「時間」という文字を含む行は除外
        slot_rows = []
        for m in all_rows:
            row_xml = m.group()
            if 'w:w="831"' in row_xml and ">時間<" not in row_xml:
                slot_rows.append(m)

        # スロット行は9行あるはず
        if len(slot_rows) != 9:
            raise ValueError(
                f"テンプレートのスロット行数が想定と異なります: {len(slot_rows)}行"
            )

        # 結合タイプを計算
        merge_types = _compute_merge_types(hours, slots)

        # 後ろから差し替え（前から差し替えるとオフセットがずれる）
        for i in range(8, -1, -1):
            row_match = slot_rows[i]
            hour = hours[i]
            content = slots.get(str(hour))
            merge = merge_types[i]

            # 行の中のセルを差し替え
            row_xml = row_match.group()

            # 時間ラベルセル (w:w="831") の内容を差し替え
            time_cell_pattern = re.compile(
                r"(<w:tc>\s*)<w:tcPr>\s*<w:tcW[^/]*w:w=\"831\"[^/]*/>"
                r"[\s\S]*?(</w:tc>)"
            )
            time_cell_match = time_cell_pattern.search(row_xml)
            if time_cell_match:
                new_time_cell = (
                    time_cell_match.group(1)
                    + _build_time_cell_xml(hour)
                    + time_cell_match.group(2)
                )
                row_xml = (
                    row_xml[: time_cell_match.start()]
                    + new_time_cell
                    + row_xml[time_cell_match.end() :]
                )

            # 業務内容セル (w:w="8323") の内容を差し替え
            content_cell_pattern = re.compile(
                r"(<w:tc>\s*)<w:tcPr>\s*<w:tcW[^/]*w:w=\"8323\"[^/]*/>"
                r"[\s\S]*?(</w:tc>)"
            )
            content_cell_match = content_cell_pattern.search(row_xml)
            if content_cell_match:
                new_content_cell = (
                    content_cell_match.group(1)
                    + _build_content_cell_xml(content, merge)
                    + content_cell_match.group(2)
                )
                row_xml = (
                    row_xml[: content_cell_match.start()]
                    + new_content_cell
                    + row_xml[content_cell_match.end() :]
                )

            # 元のXMLに差し替え
            xml = xml[: row_match.start()] + row_xml + xml[row_match.end() :]

        # 3. 特記事項を差し替え
        # 「特記事項」テキストの後の空段落にテキストを挿入
        if notes:
            notes_para = f"""<w:p xmlns:w="{W_NS}">
            <w:pPr>
              <w:spacing w:line="240" w:lineRule="atLeast"/>
              <w:rPr>
                <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック"/>
              </w:rPr>
            </w:pPr>
            <w:r>
              <w:rPr>
                <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック" w:hint="eastAsia"/>
              </w:rPr>
              <w:t>{notes}</w:t>
            </w:r>
          </w:p>"""
            # 「特記事項」を含む段落の直後の空段落を特記事項テキストに差し替え
            notes_pattern = re.compile(
                r"(>特記事項</w:t>.*?</w:p>)\s*(<w:p [^>]*>.*?</w:p>)",
                re.DOTALL,
            )
            xml = notes_pattern.sub(r"\1" + notes_para, xml, count=1)

        # 4. 修正したXMLをzipに書き戻し
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "word/document.xml":
                    zout.writestr(item, xml.encode("utf-8"))
                else:
                    zout.writestr(item, zin.read(item.filename))

    return output.getvalue()
