import json
import os

import boto3

BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0"
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


def parse_work_content(date: str, shift_pattern: str, text: str) -> dict:
    session_kwargs = {"region_name": AWS_REGION}
    if AWS_PROFILE:
        session_kwargs["profile_name"] = AWS_PROFILE
    session = boto3.Session(**session_kwargs)
    bedrock = session.client("bedrock-runtime")

    system_prompt = build_system_prompt(shift_pattern)
    user_prompt = f"日付: {date}\n業務内容:\n{text}"

    response = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
        ),
    )

    result = json.loads(response["body"].read())
    content_text = result["content"][0]["text"]
    return json.loads(content_text)
