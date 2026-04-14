# 業務日報自動生成システム

リモートワーク下における業務日報（Word形式）の作成を自動化する Web アプリケーション。
テキストまたは音声で業務内容をざっくり入力するだけで、AI が時間スロット単位に整形し、定型 Word ファイルを生成・ダウンロードできる。

## 主な機能

- 勤務パターン選択（通常勤務 9〜17時 / 遅番勤務 13〜21時）
- テキスト入力 & Web Speech API による音声入力
- AWS Bedrock（Claude Sonnet 4）による自然言語 → 時間スロット別業務内容への変換
- 変換結果の画面確認・手動編集
- 既存テンプレート（`業務日報テンプレート.docx`）をベースにした Word ファイル生成・ダウンロード

## 技術スタック

### フロントエンド
- Next.js 16 (App Router) / React 19
- TypeScript
- Tailwind CSS v4 + shadcn/ui
- Biome（Linter / Formatter）
- Yarn（パッケージマネージャ）

### バックエンド
- Python 3.14 / FastAPI
- Mangum（Lambda 互換アダプタ）
- Poetry（パッケージマネージャ）
- AWS Bedrock Runtime（Claude Sonnet 4）
- python-docx（Word 生成）

### インフラ
- AWS CDK (TypeScript)
- AWS Lambda（バックエンド API ホスティング）
- Amazon CloudFront + ACM（カスタムドメイン配信）
- Amazon S3（静的フロントエンドホスティング）

## ディレクトリ構成

```
daily-report-generator/
├── backend/          # FastAPI バックエンド
│   ├── routers/      # API エンドポイント（parse / generate）
│   ├── services/     # Bedrock 連携 / docx 生成ロジック
│   ├── schemas/      # Pydantic スキーマ
│   └── templates/    # Word テンプレート（gitignore 対象）
├── frontend/         # Next.js フロントエンド
│   └── src/
│       ├── app/
│       ├── components/ui/
│       └── lib/
├── infra/            # AWS CDK インフラ定義
│   ├── bin/
│   └── lib/
├── docs/             # 要件定義・設計書
└── docker-compose.yml  # ローカル開発環境
```

## セットアップ

### 前提条件

- Node.js 20+
- Python 3.14
- Poetry
- Yarn
- Docker（任意・ローカル開発用）
- AWS アカウント & AWS CLI プロファイル設定

### バックエンド

```bash
cd backend
poetry install
poetry run uvicorn main:app --reload --port 8000
```

必要な環境変数（`.env`）:

```
AWS_REGION=ap-northeast-1
AWS_PROFILE=<your-profile>
BEDROCK_MODEL_ID=apac.anthropic.claude-sonnet-4-20250514-v1:0
```

### フロントエンド

```bash
cd frontend
yarn install
yarn dev
```

必要な環境変数（`.env.local`）:

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

### Docker Compose（一括起動）

```bash
docker compose up --build
```

- バックエンド: `http://localhost:8000`
- フロントエンド: `http://localhost:3000`

## デプロイ

```bash
cd infra
yarn install
npx cdk deploy --all
```

デプロイ対象:
- `DailyReportCertStack`（us-east-1）: CloudFront 用 ACM 証明書
- `DailyReportStack`（ap-northeast-1）: Lambda / CloudFront / S3

## API エンドポイント

| メソッド | パス | 用途 |
|----------|------|------|
| GET | `/api/health` | ヘルスチェック |
| POST | `/api/parse` | 自由記述 → 時間スロット JSON 変換 |
| POST | `/api/generate` | スロット JSON → Word ファイル生成 |

## ライセンス

Proprietary（社内利用）
