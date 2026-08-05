import json
import os

import boto3

BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-5"
)
AWS_REGION = os.environ.get("AWS_REGION_NAME", os.environ.get("AWS_REGION", "ap-northeast-1"))
AWS_PROFILE = os.environ.get("AWS_PROFILE")


SHIFT_CONFIG = {
    "normal": {
        "hours_range": "9〜17時",
        "keys_example": '{"9":"...","10":"...","11":null,"12":"休　憩","13":null,...,"17":null}',
        "default_mail": '9時は特記がなければ"メールチェック・対応"をデフォルトで入れる',
        "default_break": '12時に昼休憩の言及があれば"休　憩"（全角スペース）を入れる',
        "all_keys": "9〜17の全スロットのキーを必ず出力する",
    },
    "late": {
        "hours_range": "13〜21時",
        "keys_example": '{"13":"...","14":"...","15":null,...,"17":"休　憩","18":null,...,"21":null}',
        "default_mail": '13時は特記がなければ"メールチェック・対応"をデフォルトで入れる',
        "default_break": '17時に昼休憩の言及があれば"休　憩"（全角スペース）を入れる',
        "all_keys": "13〜21の全スロットのキーを必ず出力する",
    },
}


def build_system_prompt(shift_pattern: str) -> str:
    config = SHIFT_CONFIG[shift_pattern]
    return f"""あなたは日本の業務日報アシスタントです。
ユーザーが1日の業務内容を自然言語で説明するので、
{config["hours_range"]}の1時間単位のスロットに変換してください。

出力はJSON形式のみで返答してください（前後のテキスト・コードブロック不要）。

{{"slots":{config["keys_example"]}}}

【ルール】
- 業務内容の文字列は20文字以内
- {config["default_mail"]}
- {config["default_break"]}
- 継続中・記載なしのスロットはnull
- {config["all_keys"]}
"""


def _invoke(system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> dict:
    session_kwargs = {"region_name": AWS_REGION}
    if AWS_PROFILE:
        session_kwargs["profile_name"] = AWS_PROFILE
    session = boto3.Session(**session_kwargs)
    bedrock = session.client("bedrock-runtime")

    response = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
        ),
    )

    result = json.loads(response["body"].read())
    # Claude Sonnet 5 は thinking ブロックが content 先頭に入ることがあるため text ブロックを探す
    content_text = next(
        (b["text"] for b in result["content"] if b.get("type") == "text"), None
    )
    if content_text is None:
        raise ValueError(f"モデル応答に text ブロックが無い (stop_reason={result.get('stop_reason')})")
    # コードフェンス付きで返ってきた場合を除去
    content_text = content_text.strip()
    if content_text.startswith("```"):
        content_text = content_text.strip("`").removeprefix("json").strip()
    return json.loads(content_text)


def parse_work_content(date: str, shift_pattern: str, text: str) -> dict:
    system_prompt = build_system_prompt(shift_pattern)
    user_prompt = f"日付: {date}\n業務内容:\n{text}"
    return _invoke(system_prompt, user_prompt)


BREAK_HOUR = {"normal": "12", "late": "17"}


def build_commits_system_prompt(shift_pattern: str, occupied_slots: dict[str, str]) -> str:
    """コミット履歴 → スロット変換用の system prompt。

    - コミット時刻は無視して、業務量を勤務時間帯に按分する
    - カレンダー予定で埋まっているスロット (occupied_slots) には業務を入れない
    - 昼休憩スロットが予定で埋まっていなければ "休　憩" を固定で入れる
    """
    config = SHIFT_CONFIG[shift_pattern]
    break_hour = BREAK_HOUR[shift_pattern]

    if occupied_slots:
        occupied_lines = "\n".join(
            f'  - スロット "{hour}" は "{title}" で確定済み'
            for hour, title in sorted(occupied_slots.items(), key=lambda kv: int(kv[0]))
        )
        occupied_rule = (
            "- 【重要】以下のスロットはカレンダー予定で確定済み。"
            "出力にはこの値をそのまま入れ、コミット由来の業務を割り当てないこと\n"
            f"{occupied_lines}"
        )
    else:
        occupied_rule = "- 本日はカレンダー予定なし"

    if break_hour in occupied_slots:
        break_rule = f'- スロット "{break_hour}" は予定で埋まっているため休憩は入れない'
    else:
        break_rule = f'- スロット "{break_hour}" は "休　憩"（全角スペース）を固定で入れる'

    return f"""あなたは日本の業務日報アシスタントです。
GitHub のコミット履歴を渡すので、それを {config["hours_range"]} の1時間単位スロットに按分してください。

出力はJSON形式のみで返答してください（前後のテキスト・コードブロック不要）。

{{"slots":{config["keys_example"]}}}

【変換ルール】
- **コミットの実時刻は無視すること**（深夜帯のコミットも勤務時間内に行ったものとして扱う）
- 同じ issue 番号 (#NNN) や repo でまとまっている作業は1つのタスクとして扱い、連続スロットに配置する
- コミット件数・粒度（fix/feat/refactor/update）からタスクごとの所要時間を推定して按分
- 各スロットの業務内容は日本語で **20文字以内**
- {config["default_mail"]}
{occupied_rule}
{break_rule}
- 該当作業が無いスロットは null
- {config["all_keys"]}
"""


def parse_from_commits(
    date: str,
    shift_pattern: str,
    commits_text: str,
    occupied_slots: dict[str, str] | None = None,
) -> dict:
    """コミット履歴テキスト → スロット JSON を返す。"""
    occupied_slots = occupied_slots or {}
    system_prompt = build_commits_system_prompt(shift_pattern, occupied_slots)
    return _invoke(system_prompt, commits_text)
