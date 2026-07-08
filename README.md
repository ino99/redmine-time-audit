# Redmine Time Audit

Redmine の `/time_entries.json` から作業時間を読み取り、四半期ごとの作業効率を棚卸するローカル Web アプリです。Redmine 側への更新は行いません。

## セットアップ

```bash
cd redmine-time-audit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` に Redmine の接続情報を設定します。

```env
REDMINE_URL=https://redmine.example.com
REDMINE_API_KEY=your_redmine_api_key_here
DEFAULT_PROJECT_ID=your_project_identifier_or_id
```

## 実行

```bash
source .venv/bin/activate
python -m flask --app app run --debug
```

ブラウザで `http://127.0.0.1:5000` を開きます。

## pandas が見つからない場合

`ModuleNotFoundError: No module named 'pandas'` が出る場合は、仮想環境ではなくシステム側の Flask が実行されています。まず以下を確認してください。

```bash
cd redmine-time-audit
source .venv/bin/activate
which python
which flask
python -m pip show pandas
```

`.venv` 内に `pip` が無い、または `python -m venv .venv` で `ensurepip is not available` が出た場合は、Ubuntu/Debian 側に venv/pip を入れてから仮想環境を作り直します。

```bash
sudo apt update
sudo apt install python3-venv python3-pip
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m flask --app app run --debug
```

## 使い方

- 開始日、終了日、四半期プリセット、任意のプロジェクトIDを指定して分析できます。
- 分析後に「対象バージョン」を複数選択すると、収集済みデータを再取得せずに絞り込み再集計できます。
- バージョン未設定のIssueやIssue未紐づけの作業は `バージョン未設定` として選択できます。
- 重いIssueやIssue別Top10の「詳細」から、別画面でステータス遷移フローとステータス別の作業時間を確認できます。
- 右上の「ダーク」/「ライト」ボタンで表示テーマを切り替えできます。選択はブラウザに保存されます。
- Redmine に接続できない場合は「サンプルモード」をオンにすると `sample_data/sample_time_entries.json` を使って画面を確認できます。
- CSV ボタンから以下を出力できます。
  - `raw_time_entries.csv`
  - `user_ranking.csv`
  - `user_issue_top10.csv`
  - `activity_summary.csv`
  - `project_summary.csv`
- 「Excel出力」ボタンから、報告書や追加分析に使える `redmine_time_audit_report.xlsx` を出力できます。
  - サマリー
  - 棚卸アラート
  - ユーザーランキング
  - ユーザーIssueTop10
  - 作業分類別
  - プロジェクト別
  - Raw
  - Issue番号はRedmineチケットへのハイパーリンクになります。

## 依存関係を更新した場合

Excel出力には `openpyxl` を使います。既にセットアップ済みの環境では、以下で依存関係を更新してください。

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## GitHub 登録前の注意

- `.env` は Git 管理対象外です。APIキーをコミットしないでください。
- GitHub には `.env.example` のみ登録してください。
- `output/` と `*.csv` も Git 管理対象外です。
- APIキーは画面、ログ、CSVには出力しません。

## Redmine API

取得先は `GET /time_entries.json` です。

主なパラメータ:

- `from`: 開始日
- `to`: 終了日
- `limit`: 100
- `offset`: ページング
- `project_id`: 任意

認証は `X-Redmine-API-Key` ヘッダーで行います。
