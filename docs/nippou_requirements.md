# 業務日報自動生成システム 要件定義・設計書

## 1. 概要

### 1.1 背景と目的

リモートワーク下における業務日報（Word形式）の作成を自動化する。
現状は手動で所定テンプレートに記入しており、毎日の作成コストが高い。
音声またはテキストで業務内容をざっくり入力するだけで、定型Wordファイルを生成・ダウンロードできる仕組みを構築する。

### 1.2 スコープ

| 対象 | 内容 |
|------|------|
| 対象ユーザー | 社内リモートワーカー（当面は1名、将来的に数名規模で共有の可能性あり） |
| 対象業務 | 業務日報（業務日報_YYYY_MM_DD.docx）の作成 |
| 対象外 | 日報の提出・送付・承認フロー |

---

## 2. 現状の業務フロー

```
毎日業務終了時
  └─ 既存テンプレート(.docx)を開く
  └─ 日付を手入力
  └─ 各時間スロット（9〜17時）に業務内容を手入力
  └─ ファイル名を付けて保存・提出
```

**課題：**
- 毎日の入力が面倒で忘れやすい
- 記憶を遡っての入力はミスが多い
- Notion・GitHub・メールなど複数ソースから情報を集める必要がある

---

## 3. 要件

### 3.1 機能要件

#### FR-01 勤務パターン選択

業務開始・終了時刻が日によって異なるため、入力前に勤務パターンを選択できる。

| パターン | 時間スロット | 休憩デフォルト | 備考 |
|----------|-------------|----------------|------|
| 通常勤務 | 9〜17時 | 12時「休　憩」 | 標準パターン |
| 遅番勤務 | 13〜21時 | 17時「休　憩」 | 遅番パターン |

- UI上でトグルまたはセレクトボックスで切り替える
- 選択したパターンに応じて、AIへ渡すスロット範囲・デフォルト休憩スロットが変わる
- 選択したパターンに応じて、Wordの時間ラベル（9時〜17時 or 13時〜21時）も自動で切り替わる

#### FR-02 業務内容の入力受付

- テキスト入力による業務内容の自由記述を受け付ける
- ブラウザの Web Speech API を利用した音声入力を受け付ける（フロントエンド機能）
- 入力フォーマットは自然言語で、時刻が曖昧でも可

**入力例（通常勤務）：**
```
9時からメールを確認して、10時からMSGアプリの認証機能の開発してた。
12時に昼休憩とって、13時から引き続き開発。
16時ごろから新機能の仕様書を書き始めた。
```

**入力例（遅番勤務）：**
```
13時からメール確認して、14時からMSGアプリの開発。
17時に休憩とって、18時から引き続き開発。20時ごろに切り上げた。
```

#### FR-03 AI によるスケジュール解析

- 自由記述テキストと勤務パターンを AWS Bedrock（Claude Sonnet 系）に送信する
- AIが選択パターンに応じた時間スロット（1時間単位）ごとの業務内容に変換する
- 出力形式はJSON（後述のスキーマ参照）
- ユーザーが変換結果を画面上で確認・修正できる

**AIへの指示方針（通常勤務 9〜17時）：**
- 9時スロット：特記なければ「メールチェック・対応」をデフォルト補完
- 12時スロット：昼休憩の言及があれば「休　憩」を設定
- 全スロット（9〜17）のキーを必ず出力する

**AIへの指示方針（遅番勤務 13〜21時）：**
- 13時スロット：特記なければ「メールチェック・対応」をデフォルト補完
- 17時スロット：昼休憩の言及があれば「休　憩」を設定
- 全スロット（13〜21）のキーを必ず出力する

**共通ルール：**
- 業務内容の文字列は20文字以内
- 継続中のタスク・記載なしスロットは `null`

**出力JSONスキーマ（通常勤務）：**
```json
{
  "slots": {
    "9":  "メールチェック・対応",
    "10": "MSG App 認証機能開発",
    "11": null,
    "12": "休　憩",
    "13": "MSG App 認証機能開発",
    "14": null,
    "15": null,
    "16": "新機能 初期設計",
    "17": null
  }
}
```

**出力JSONスキーマ（遅番勤務）：**
```json
{
  "slots": {
    "13": "メールチェック・対応",
    "14": "MSG App 認証機能開発",
    "15": null,
    "16": null,
    "17": "休　憩",
    "18": "MSG App 認証機能開発",
    "19": null,
    "20": "新機能 初期設計",
    "21": null
  }
}
```

#### FR-04 Word ファイル生成

- 既存テンプレート（`業務日報テンプレート.docx`）をベースに生成する
- 差し替え対象：日付・時間ラベル（9時〜17時 or 13時〜21時）・各スロットの業務内容
- ファイル名：`業務日報_YYYY_MM_DD.docx`
- 生成後、ブラウザからダウンロードさせる

**テンプレート構造（docx内テーブル）：**

| Row | 内容 |
|-----|------|
| 0 | 所属（固定）、氏名（固定） |
| 1 | ヘッダー行「本日の業務 / 時間 / 業務内容」 |
| 2〜10 | 時間スロット行 × 9行（時間ラベル＋業務内容セルを差し替え） |
| 11 | 特記事項（今フェーズは空欄のまま） |
| 12 | 業務場所「自宅」（固定） |
| 13 | 受理年月日・所属長欄（固定） |

**差し替え対象フィールド：**
- 日付テキスト（`　　YYYY年M月D日(曜)`形式）
- 各スロット行の時間ラベルセル（`9時`〜`17時` → 勤務パターンに応じて変更）
- 各スロット行の業務内容セル（`w:w="8323"` のセル）

**勤務パターン別スロット対応：**

| パターン | Row2 | Row3 | Row4 | Row5 | Row6 | Row7 | Row8 | Row9 | Row10 |
|----------|------|------|------|------|------|------|------|------|-------|
| 通常勤務 | 9時 | 10時 | 11時 | 12時 | 13時 | 14時 | 15時 | 16時 | 17時 |
| 遅番勤務 | 13時 | 14時 | 15時 | 16時 | 17時 | 18時 | 19時 | 20時 | 21時 |

#### FR-05 UI

- Web アプリとして提供（Next.js）
- 勤務パターン選択（トグル or セレクト：通常勤務 9〜17時 / 遅番勤務 13〜21時）
- 日付セレクター（デフォルト：当日）
- テキストエリア（業務内容の自由記述）
- 音声入力ボタン（Web Speech API / Chrome 推奨）
- 「AIで変換」ボタン → 選択パターンに応じたスロット一覧表示
- 各スロットのインライン編集（確認・修正用）
- 「Word ファイルを生成」ボタン → ダウンロード

### 3.2 非機能要件

| 項目 | 要件 |
|------|------|
| レスポンス | AI解析：5秒以内（通常時） |
| 可用性 | 業務時間内に利用可能であれば十分 |
| セキュリティ | IAMロールによるBedrock認証。APIキーの管理不要 |
| スケーラビリティ | 当面1ユーザー。将来的に仲間うち数名で共有する可能性あり |
| 対応ブラウザ | Chrome（音声入力）/ その他主要ブラウザ（テキスト入力） |

---

## 4. システム構成

### 4.1 全体アーキテクチャ

```
[ユーザー]
    │  ブラウザ（Chrome推奨）
    ▼
[フロントエンド]  Next.js（静的エクスポート）
    │              S3 + CloudFront でホスティング
    │
    │  POST /api/parse   → 業務テキスト送信
    │  POST /api/generate → スロットJSON + 日付送信
    ▼
[API Gateway (REST API)]
    ▼
[Lambda]  Python（FastAPI + Mangum）
    ├─ /api/parse     → Bedrock (Claude) 呼び出し → スロットJSON返却
    └─ /api/generate  → docxテンプレート操作 → docxファイル返却
    │
    ├─ [AWS Bedrock]     Claude Sonnet（claude-sonnet-4 系）
    └─ [S3]              テンプレートdocx保管

[IaC]  AWS CDK（TypeScript）
```

### 4.2 技術スタック

| レイヤー | 技術 |
|----------|------|
| フロントエンド | Next.js（App Router / 静的エクスポート）, TypeScript |
| バックエンド | Python 3.13+, FastAPI, Mangum（Lambda アダプタ） |
| AI | AWS Bedrock — Claude Sonnet（claude-sonnet-4 系） |
| Word生成 | zipfile + XML直接操作 |
| ホスティング | S3 + CloudFront（フロントエンド） |
| コンピュート | Lambda + API Gateway（バックエンド） |
| IaC | AWS CDK（TypeScript） |
| CI/CD | GitHub Actions |

### 4.3 ディレクトリ構成（案）

```
daily-report-generator/
├── frontend/                   # Next.js（静的エクスポート）
│   ├── app/
│   │   └── page.tsx            # メインUI
│   ├── components/
│   │   ├── ShiftSelector.tsx   # 勤務パターン選択（通常 / 遅番）
│   │   ├── DatePicker.tsx
│   │   ├── TextInput.tsx       # 音声入力含む
│   │   ├── SlotEditor.tsx      # スロット確認・編集
│   │   └── DownloadButton.tsx
│   └── lib/
│       └── api.ts              # バックエンドAPI呼び出し
│
├── backend/                    # FastAPI + Mangum（Lambda用）
│   ├── main.py                 # FastAPI app + Mangum handler
│   ├── routers/
│   │   ├── parse.py            # /api/parse
│   │   └── generate.py         # /api/generate
│   ├── services/
│   │   ├── bedrock_service.py  # Bedrock (Claude) 呼び出し・プロンプト生成
│   │   └── docx_service.py     # Word生成（パターン対応）
│   ├── schemas/
│   │   └── nippou.py           # Pydanticモデル定義
│   ├── templates/
│   │   └── 業務日報テンプレート.docx
│   └── pyproject.toml          # Poetry
│
├── infra/                      # AWS CDK（TypeScript）
│   ├── bin/
│   │   └── app.ts
│   ├── lib/
│   │   └── daily-report-stack.ts  # Lambda, API GW, S3, CloudFront, IAM
│   ├── package.json
│   └── tsconfig.json
│
├── docs/
│   ├── nippou_requirements.md
│   └── templates/              # 参考用の既存日報ファイル
│
└── docker-compose.yml          # ローカル開発用
```

---

## 5. API 設計

### POST /api/parse

業務内容テキストと勤務パターンを受け取り、スロットJSONを返す。

**Request:**
```json
{
  "date": "2026-04-10",
  "shift_pattern": "normal",
  "text": "9時からメールして、10時からMSGアプリの開発。12時昼休み。13時から開発続き。16時から仕様書。"
}
```

| フィールド | 型 | 値 | 説明 |
|-----------|----|----|------|
| `date` | string | `YYYY-MM-DD` | 対象日付 |
| `shift_pattern` | string | `"normal"` / `"late"` | 勤務パターン |
| `text` | string | 自由記述 | 業務内容 |

**Response 200（通常勤務）：**
```json
{
  "shift_pattern": "normal",
  "slots": {
    "9":  "メールチェック・対応",
    "10": "MSG App 認証機能開発",
    "11": null,
    "12": "休　憩",
    "13": "MSG App 認証機能開発",
    "14": null,
    "15": null,
    "16": "新機能 初期設計",
    "17": null
  }
}
```

**Response 200（遅番勤務）：**
```json
{
  "shift_pattern": "late",
  "slots": {
    "13": "メールチェック・対応",
    "14": "MSG App 認証機能開発",
    "15": null,
    "16": null,
    "17": "休　憩",
    "18": "MSG App 認証機能開発",
    "19": null,
    "20": "新機能 初期設計",
    "21": null
  }
}
```

**Response 4xx/5xx:**
```json
{
  "error": "エラーメッセージ"
}
```

---

### POST /api/generate

スロットJSON・日付・勤務パターンを受け取り、docxファイルを返す。

**Request:**
```json
{
  "date": "2026-04-10",
  "shift_pattern": "normal",
  "slots": {
    "9":  "メールチェック・対応",
    "10": "MSG App 認証機能開発",
    "11": null,
    "12": "休　憩",
    "13": "MSG App 認証機能開発",
    "14": null,
    "15": null,
    "16": "新機能 初期設計",
    "17": null
  }
}
```

**Response 200:**
- `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `Content-Disposition: attachment; filename="業務日報_2026_04_10.docx"`
- Body: バイナリ（docxファイル）

---

## 6. Word 生成ロジック詳細

### 6.1 方針

docx-jsによる1から生成ではなく、**既存テンプレートのXMLを直接操作**する方針をとる。
理由：テンプレートは縦書きセル・セル結合・独自スタイルが含まれており、1から再現するコストが高い。

### 6.2 勤務パターン定義

```python
SHIFT_PATTERNS = {
    "normal": {
        "hours": [9, 10, 11, 12, 13, 14, 15, 16, 17],
        "default_mail_slot": 9,
        "default_break_slot": 12,
    },
    "late": {
        "hours": [13, 14, 15, 16, 17, 18, 19, 20, 21],
        "default_mail_slot": 13,
        "default_break_slot": 17,
    },
}
```

### 6.3 処理手順

```python
# 1. テンプレートをzipとして読み込み
with zipfile.ZipFile("template.docx") as zin:
    xml = zin.read("word/document.xml").decode("utf-8")

# 2. 日付を差し替え
# ">　　202" を目印に直前の <w:p> を特定し、日付文字列を置換

# 3. 各スロット行を差し替え
# テンプレートの時間ラベルは「9時」〜「17時」で固定されているため、
# 遅番パターンの場合は時間ラベルセルも合わせて書き換える
#
# 処理方針：
#   - テンプレートの Row2〜Row10 を順番に取得する
#   - shift_patternのhoursリストと1対1で対応させる
#   - 各行について：
#       a) 時間ラベルセル（w:w="831"）のテキストを対応する時刻に書き換え
#       b) 業務内容セル（w:w="8323"）をスロットの業務内容で書き換え
#          （vMerge属性は除去して単独セルとして扱う）

# 4. 修正したXMLをzipに書き戻してdocxを生成
with zipfile.ZipFile(output_buffer, "w") as zout:
    for item in zin.infolist():
        if item.filename == "word/document.xml":
            zout.writestr(item, modified_xml)
        else:
            zout.writestr(item, zin.read(item.filename))
```

### 6.4 業務内容セルのXML構造

テンプレートの各スロット行における業務内容セル（置換対象）：

```xml
<w:tc>
  <w:tcPr>
    <w:tcW w:w="8323" w:type="dxa"/>
    <w:gridSpan w:val="3"/>
    <!-- vMerge がある行は除去して単独セルとして扱う -->
    <w:vAlign w:val="center"/>
  </w:tcPr>
  <!-- ここに業務内容テキストの <w:p> を挿入 -->
  <w:p>
    <w:pPr>
      <w:rPr>
        <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック"/>
      </w:rPr>
    </w:pPr>
    <w:r>
      <w:rPr>
        <w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック" w:hAnsi="ＭＳ ゴシック" w:hint="eastAsia"/>
      </w:rPr>
      <w:t>MSG App 認証機能開発</w:t>
    </w:r>
  </w:p>
</w:tc>
```

---

## 7. Bedrock (Claude) プロンプト設計

### 7.1 Bedrock 呼び出し

```python
import boto3
import json

bedrock = boto3.client("bedrock-runtime", region_name="ap-northeast-1")

def invoke_claude(system_prompt: str, user_prompt: str) -> dict:
    response = bedrock.invoke_model(
        modelId="apac.anthropic.claude-sonnet-4-20250514-v1:0",
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
        }),
    )
    result = json.loads(response["body"].read())
    return json.loads(result["content"][0]["text"])
```

### 7.2 System Prompt（勤務パターンに応じて動的生成）

```python
def build_system_prompt(shift_pattern: str) -> str:
    if shift_pattern == "normal":
        hours_range = "9〜17時"
        keys = '{"9":"...","10":"...","11":null,"12":"休　憩","13":null,...,"17":null}'
        default_mail = '9時は特記がなければ"メールチェック・対応"をデフォルトで入れる'
        default_break = '12時に昼休憩の言及があれば"休　憩"（全角スペース）を入れる'
        all_keys = "9〜17の全スロットのキーを必ず出力する"
    else:  # late
        hours_range = "13〜21時"
        keys = '{"13":"...","14":"...","15":null,...,"17":"休　憩","18":null,...,"21":null}'
        default_mail = '13時は特記がなければ"メールチェック・対応"をデフォルトで入れる'
        default_break = '17時に昼休憩の言及があれば"休　憩"（全角スペース）を入れる'
        all_keys = "13〜21の全スロットのキーを必ず出力する"

    return f"""あなたは日本の業務日報アシスタントです。
ユーザーが1日の業務内容を自然言語で説明するので、
{hours_range}の1時間単位のスロットに変換してください。

出力はJSON形式のみで返答してください（前後のテキスト・コードブロック不要）。

{{"slots":{keys}}}

【ルール】
- 業務内容の文字列は20文字以内
- {default_mail}
- {default_break}
- 継続中・記載なしのスロットはnull
- {all_keys}
"""
```

### 7.3 User Prompt

```
日付: 2026年4月10日(金)
業務内容:
{ユーザーの自由記述テキスト}
```

---

## 8. 開発フェーズ

### Phase 1（MVP — ローカル動作）

- [ ] バックエンド: FastAPI + Poetry セットアップ
- [ ] バックエンド: `/api/parse` 実装（Bedrock Claude 連携）
- [ ] バックエンド: `/api/generate` 実装（docx XML 操作）
- [ ] フロントエンド: Next.js 基本UI（日付・勤務パターン・テキスト入力・変換・ダウンロード）
- [ ] Docker Compose でローカル動作確認

### Phase 2（AWS デプロイ）

- [ ] CDK スタック構築（Lambda, API Gateway, S3, CloudFront）
- [ ] Lambda 用パッケージング（Mangum アダプタ統合）
- [ ] フロントエンド静的エクスポート → S3 + CloudFront デプロイ
- [ ] CI/CD（GitHub Actions → CDK deploy）

### Phase 3（UI 強化）

- [ ] 音声入力（Web Speech API）統合
- [ ] スロット確認・インライン編集UI
- [ ] レスポンシブ対応

### Phase 4（オプション）

- [ ] Notion API 連携（タスクログの自動取得）
- [ ] GitHub API 連携（コミット履歴からの自動補完）
- [ ] Cognito による認証（複数ユーザー対応時）

---

## 9. 環境変数

| 変数名 | 説明 | 設定箇所 |
|--------|------|----------|
| `AWS_REGION` | AWSリージョン（デフォルト: `ap-northeast-1`） | Lambda 環境変数 |
| `BEDROCK_MODEL_ID` | Bedrock モデルID（デフォルト: `apac.anthropic.claude-sonnet-4-20250514-v1:0`） | Lambda 環境変数 |
| `TEMPLATE_BUCKET` | テンプレートdocx保管用 S3 バケット名 | Lambda 環境変数 |
| `TEMPLATE_KEY` | S3 上のテンプレートファイルキー | Lambda 環境変数 |
| `NEXT_PUBLIC_API_BASE_URL` | API Gateway のエンドポイントURL | フロントエンドビルド時 |

※ Bedrock の認証は Lambda 実行ロール（IAM）で行うため、APIキーは不要。

---

## 10. 添付物

- `業務日報テンプレート.docx` — Word生成の元となるテンプレートファイル
- 本ドキュメント（`nippou_requirements.md`）

---

*作成日: 2026-04-10*
