# Tech Blog Generator

## 概要

**Tech Blog Generator** は、指定した GitHub リポジトリまたはアップロードされたプロジェクトフォルダを解析し、各ファイルの役割や詳細なコード解説を自動生成する Web アプリケーションです。解析結果を元に、章・節・項に分かれたテックブログのアウトラインおよび最終的な Markdown 形式の記事を作成します。

## デモ

実際に動作しているデプロイ済みのウェブアプリは、[こちら](https://www.techblog-generator.igtcons.com/)からアクセスできます。こちらのデモサイトでは、GitHub リポジトリの解析からブログ記事の自動生成まで、Tech Blog Generator の全機能を体験いただけますので、ぜひご利用ください。

---

## 特徴

- **プロジェクト解析**  
  - GitHub リポジトリのクローンまたはアップロードされたフォルダから対象ファイルを再帰的に取得・解析します。
- **ディレクトリ構造の表示**  
  - プロジェクトのディレクトリツリーをツリー記号で可視化します。
- **ファイルの役割要約**  
  - 各ファイルの役割を、LLM (GPT-4o) を用いて自動要約します。
- **詳細なコード解説**  
  - 各ファイルのコードを解析し、コードブロックごとに詳細な解説を生成します。
- **ブログアウトライン・最終記事生成**  
  - 解析結果をもとに、章・節・項に分けたブログ記事のアウトラインと最終記事を Markdown 形式で生成します。
- **プレビュー＆編集機能**  
  - ブラウザ上でアウトラインや記事のプレビュー・編集が可能です。
- **Markdown ダウンロード**  
  - 生成された記事を Markdown ファイルとしてダウンロードできます。

---

## 技術スタック

- **Python 3.12**
- **Flask** – 軽量な Web フレームワーク
- **LangChain** & **OpenAI GPT-4** – 自然言語処理・文章生成
- **Markdown** – ブログ記事生成用
- **Poetry** – 依存関係管理ツール
- **Docker** – コンテナ化して簡単に環境構築

---

## インストール & 実行方法

### 1. ローカル環境で実行
#### 1.1 リポジトリをクローン
```bash
git clone https://github.com/your_username/tech-blog-generator.git
cd tech-blog-generator
```

#### 1.2 Poetry で依存パッケージをインストール
```bash
poetry install
```

#### 1.3 環境変数を設定
プロジェクトルートに `.env` ファイルを作成し、以下の環境変数を設定してください。

```env
OPENAI_API_KEY=your_openai_api_key
GOOGLE_API_KEY=your_gemini_api_key
FLASK_SECRET_KEY=your_secret_key
```

#### 1.4 アプリケーションを起動
```bash
poetry run python app.py
```

#### 1.5 アクセス
ブラウザで `http://localhost:8080` にアクセスしてください。

---

### 2. Docker で実行
このアプリは **Docker** で実行可能です。

#### 2.1 Docker イメージをビルド
`Dockerfile` があるプロジェクトルートで以下のコマンドを実行してください。

```bash
docker build -t tech-blog-generator .
```

#### 2.2 Docker コンテナを起動
環境変数を `.env` ファイルで管理する場合：
```bash
docker run --env-file .env -p 8501:8080 tech-blog-generator
```

または、環境変数をコマンドラインで指定する場合：
```bash
docker run -e OPENAI_API_KEY=your_api_key_here -p 8501:8080 tech-blog-generator
```

#### 2.3 アクセス
ブラウザで `http://localhost:8501` にアクセスしてください。

---

## ディレクトリ構成
```bash
.
├── Dockerfile
├── README.md
├── app.py
├── const
│   ├── __init__.py
│   ├── __pycache__
│   ├── const.py
│   └── prompt.py
├── poetry.lock
├── pyproject.toml
├── static
│   ├── css
│   │   ├── pygments.css
│   │   └── style.css
│   └── js
│       └── main.js
└── templates
    └── index.html
```

<!-- 以降はテンプレだが不使用のためコメントアウト -->
<!--
---

## 貢献方法
バグ報告や機能改善の Pull Request を歓迎します。Issue や Pull Request を通じてご意見・ご要望をお寄せください。

---

## ライセンス
このプロジェクトは [MIT License](LICENSE) の下で公開されています。

---

## お問い合わせ
ご質問やご意見がありましたら、[your_email@example.com](mailto:your_email@example.com) までご連絡ください。
-->

<!-- autopep8実行コマンドメモ -->
<!-- poetry run autopep8 --in-place --aggressive --aggressive --recursive . -->