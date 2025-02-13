import os
import re
import logging
import subprocess
import tempfile
import threading
import uuid
import markdown
import json

from dotenv import load_dotenv
from flask import Flask, request, render_template, redirect, url_for, flash, send_file, session, jsonify
from werkzeug.utils import secure_filename

# LangChain & OpenAI imports
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

###############################################################################
# Logging configuration
###############################################################################
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

###############################################################################
# Load environment variables & check for OpenAI key
###############################################################################
load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    logger.error("OPENAI_API_KEY is not set. Please set it in the .env file.")
    raise EnvironmentError("OPENAI_API_KEY is not set. Please set it in the .env file.")
logger.info("OPENAI_API_KEY successfully loaded.")

###############################################################################
# Flask App Initialization
###############################################################################
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace_with_a_secure_random_key")
app.config['ENV'] = 'production'
app.config['DEBUG'] = False
app.config['TESTING'] = False

# 進捗管理用のグローバル辞書
progress_store = {}
# バックグラウンドでの生成結果を格納するグローバル辞書
result_store = {}

###############################################################################
# Utility functions
###############################################################################

def read_project_files(root_dir):
    """
    指定ディレクトリ以下のファイル（.py, .md, .txt 等）を再帰的に読み込み、テキストを連結。
    """
    logger.info("Reading project files from: %s", root_dir)
    all_text = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for file in filenames:
            file_path = os.path.join(dirpath, file)
            if file.lower().endswith((".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp")):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    relative_path = os.path.relpath(file_path, root_dir)
                    header = f"\n\n### File: {relative_path}\n"
                    all_text.append(header + content)
                except Exception as e:
                    logger.warning("Could not read file %s: %s", file_path, e)
    combined_text = "\n".join(all_text)
    logger.info("Completed reading project files. Total length: %d characters", len(combined_text))
    return combined_text

def get_directory_tree(root_dir):
    """
    ディレクトリ構造をツリー形式の文字列として返す
    （例：├── project/, │   ├── app.py など）
    """
    tree_lines = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        level = dirpath.replace(root_dir, '').count(os.sep)
        indent = "│   " * level
        tree_lines.append(f"{indent}├── {os.path.basename(dirpath)}/")
        for f in filenames:
            tree_lines.append(f"{indent}│   ├── {f}")
    return "\n".join(tree_lines)

def strip_code_fences(text: str) -> str:
    """
    Markdownコードフェンス ```...``` を除去
    """
    text = re.sub(r"```[a-zA-Z]*\n", "", text)
    text = text.replace("```", "")
    return text

###############################################################################
# PromptTemplates
###############################################################################

file_role_prompt_template = PromptTemplate(
    input_variables=["directory_tree"],
    template="""
以下のディレクトリ構造を見て、各ファイルの役割を簡潔にまとめてください。

ディレクトリ構造:
{directory_tree}
"""
)

code_detail_prompt_template = PromptTemplate(
    input_variables=["file_content", "file_path"],
    template="""
以下はファイル「{file_path}」の完全なコードです。  
機能ごとにコードを解説し、コードブロックを省略せず示してください。
最後にファイル全体のコードをまとめて再掲してください。

ファイルのコード:
{file_content}
"""
)

blog_outline_prompt_template = PromptTemplate(
    input_variables=["directory_tree", "file_roles", "detailed_code_analysis", "project_files_content", "github_url", "target_audience", "blog_tone", "additional_requirements"],
    template="""
あなたは有能なソフトウェアエンジニア兼テックライターです。
以下の情報をもとに、テックブログの章立て（アウトライン）を考案してください。

【コンテキスト】
1) ディレクトリ構造:
{directory_tree}

2) ファイルの役割概要:
{file_roles}

3) 詳細なコード解説:
{detailed_code_analysis}

4) 全ファイル内容:
{project_files_content}

【追加情報】
- GitHubリポジトリURL: {github_url}
- 想定読者: {target_audience}
- トーン: {blog_tone}
- その他リクエスト: {additional_requirements}

【出力要件】
- ブログ全体をどのような章構成（見出し）にするか、
  各章でどんな話題を扱うかを箇条書きなどで示してください。
- Markdown形式で書いてください。
"""
)

final_blog_prompt_template = PromptTemplate(
    input_variables=["directory_tree", "file_roles", "detailed_code_analysis", "project_files_content", "github_url", "target_audience", "blog_tone", "additional_requirements", "language", "blog_outline"],
    template="""
あなたは有能なソフトウェアエンジニア兼テックライターです。

以下の情報を踏まえて、最終的なテックブログ記事を{language}で作成してください。

【事前に確定したアウトライン】
{blog_outline}

【その他のコンテキスト】
1) ディレクトリ構造:
{directory_tree}

2) ファイルの役割概要:
{file_roles}

3) 詳細なコード解説:
{detailed_code_analysis}

4) 全ファイル内容:
{project_files_content}

【追加情報】
- GitHubリポジトリURL: {github_url}
- 想定読者: {target_audience}
- トーン: {blog_tone}
- その他リクエスト: {additional_requirements}

【出力要件】
- アウトラインを基に、読みやすいMarkdown形式の記事を作成してください。
- コードブロックは省略せず示し、各機能とコードを対応づけて解説してください。
- 最後はハッピーなトーンで締めくくってください。
"""
)

###############################################################################
# バックグラウンド処理：アウトライン生成前まで
###############################################################################

def process_project(progress_id, github_url, target_audience, blog_tone, additional_requirements, language, temp_project_dir):
    """
    バックグラウンドで:
    1. プロジェクトファイル取得
    2. ディレクトリ構造
    3. ファイル要約
    4. 詳細解説
    5. ここでは アウトライン生成までは行わず、結果を格納して終了
       （続きは /generate_outline で行う）
    """
    try:
        progress_store[progress_id] = "Step 1: プロジェクトファイルの取得を開始します。\n"
        if os.listdir(temp_project_dir):
            progress_store[progress_id] += "フォルダアップロードによる取得完了。\n"
            logger.info("Project files obtained from uploaded folder.")
        else:
            clone_cmd = ["git", "clone", github_url, temp_project_dir]
            try:
                subprocess.check_output(clone_cmd, stderr=subprocess.STDOUT)
                progress_store[progress_id] += "GitHubリポジトリからのクローンに成功。\n"
            except subprocess.CalledProcessError as e:
                progress_store[progress_id] += "GitHubリポジトリのクローンに失敗しました。\n"
                return

        progress_store[progress_id] += "Step 2: ディレクトリ構造を取得中...\n"
        directory_tree = get_directory_tree(temp_project_dir)
        progress_store[progress_id] += "ディレクトリ構造の取得完了。\n"

        progress_store[progress_id] += "Step 3: 各ファイルの役割を要約中...\n"
        llm = ChatOpenAI(model_name="gpt-4o", openai_api_key=openai_api_key)
        file_role_chain = LLMChain(llm=llm, prompt=file_role_prompt_template)
        file_roles = file_role_chain.run({"directory_tree": directory_tree})
        progress_store[progress_id] += "各ファイルの役割要約完了。\n"

        progress_store[progress_id] += "Step 4: 各ファイルの詳細なコード解説を取得中...\n"
        detailed_code_analysis = ""
        all_files = []
        for dirpath, dirnames, filenames in os.walk(temp_project_dir):
            for file in filenames:
                if file.lower().endswith((".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp")):
                    all_files.append(os.path.join(dirpath, file))
        total_files = len(all_files)
        progress_store[progress_id] += f"対象ファイル数: {total_files} 件\n"

        for i, file_path in enumerate(all_files, 1):
            relative_file_path = os.path.relpath(file_path, temp_project_dir)
            progress_store[progress_id] += f"ファイル解析中: {i}/{total_files} -> {relative_file_path}\n"
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    file_content = f.read()
                code_detail_chain = LLMChain(llm=llm, prompt=code_detail_prompt_template)
                file_detail = code_detail_chain.run({
                    "file_path": relative_file_path,
                    "file_content": file_content
                })
                detailed_code_analysis += f"\n\n## {relative_file_path}\n" + file_detail
            except Exception as e:
                progress_store[progress_id] += f"ファイル解析失敗: {relative_file_path} - {e}\n"

        progress_store[progress_id] += "各ファイルの詳細なコード解説完了。\n"
        project_files_content = read_project_files(temp_project_dir)

        # ここではまだアウトライン生成をせず、次のステップで行う
        progress_store[progress_id] += "一旦基本情報の抽出が完了しました。\n"
        
        # 取得情報を result_store に保存
        result_store[progress_id + "_tree"] = directory_tree
        result_store[progress_id + "_roles"] = file_roles
        result_store[progress_id + "_analysis"] = detailed_code_analysis
        result_store[progress_id + "_files"] = project_files_content

    except Exception as e:
        progress_store[progress_id] += f"処理中にエラー発生: {e}\n"

###############################################################################
# アウトライン生成
###############################################################################
@app.route("/generate_outline", methods=["GET"])
def generate_outline():
    """
    process_projectの後、ユーザが「アウトライン生成」ボタンを押すなどで呼ばれ、
    ブログの章立てを生成する。
    """
    progress_id = session.get("progress_id", None)
    if not progress_id:
        flash("progress_idがありません。", "error")
        return redirect(url_for("index"))

    directory_tree = result_store.get(progress_id + "_tree", "")
    file_roles = result_store.get(progress_id + "_roles", "")
    detailed_code_analysis = result_store.get(progress_id + "_analysis", "")
    project_files_content = result_store.get(progress_id + "_files", "")

    # パラメータを取得（フロントで指定された場合に備えて）
    github_url = request.args.get("github_url", "")
    target_audience = request.args.get("target_audience", "エンジニア全般")
    blog_tone = request.args.get("blog_tone", "カジュアルだけど専門性を感じるトーン")
    additional_requirements = request.args.get("additional_requirements", "")

    # LLM呼び出し
    try:
        llm = ChatOpenAI(model_name="gpt-4o", openai_api_key=openai_api_key)
        outline_chain = LLMChain(llm=llm, prompt=blog_outline_prompt_template)
        blog_outline = outline_chain.run({
            "directory_tree": directory_tree,
            "file_roles": file_roles,
            "detailed_code_analysis": detailed_code_analysis,
            "project_files_content": project_files_content,
            "github_url": github_url,
            "target_audience": target_audience,
            "blog_tone": blog_tone,
            "additional_requirements": additional_requirements
        })
        # 結果を保存
        result_store[progress_id + "_outline"] = blog_outline
        progress_store[progress_id] += "\nブログアウトラインの生成が完了しました。\n"
        flash("ブログアウトラインを生成しました。", "info")
        return redirect(url_for("preview_outline"))

    except Exception as e:
        flash(f"アウトライン生成中にエラーが発生しました: {e}", "error")
        return redirect(url_for("index"))

###############################################################################
# アウトラインのプレビュー＆編集
###############################################################################
@app.route("/preview_outline", methods=["GET", "POST"])
def preview_outline():
    progress_id = session.get("progress_id", None)
    if not progress_id:
        flash("progress_idがありません。", "error")
        return redirect(url_for("index"))

    outline_key = progress_id + "_outline"

    if request.method == "POST":
        # ユーザが修正したアウトラインを保存し、次へ
        edited_outline = request.form.get("edited_outline", "")
        result_store[outline_key] = edited_outline
        return redirect(url_for("generate_final_blog"))

    # 現在のアウトラインを取得
    blog_outline = result_store.get(outline_key, "まだアウトラインが生成されていません。")
    return render_template("preview_outline.html", blog_outline=blog_outline)

###############################################################################
# 最終ブログ生成
###############################################################################
@app.route("/generate_final_blog", methods=["GET"])
def generate_final_blog():
    progress_id = session.get("progress_id", None)
    if not progress_id:
        flash("progress_idがありません。", "error")
        return redirect(url_for("index"))

    # 前段階で保存していた各種情報
    directory_tree = result_store.get(progress_id + "_tree", "")
    file_roles = result_store.get(progress_id + "_roles", "")
    detailed_code_analysis = result_store.get(progress_id + "_analysis", "")
    project_files_content = result_store.get(progress_id + "_files", "")
    blog_outline = result_store.get(progress_id + "_outline", "")

    # ユーザ指定の設定(本来はセッション等に保存しておく想定)
    github_url = request.args.get("github_url", "")
    target_audience = request.args.get("target_audience", "エンジニア全般")
    blog_tone = request.args.get("blog_tone", "カジュアルだけど専門性を感じるトーン")
    additional_requirements = request.args.get("additional_requirements", "")
    language = request.args.get("language", "ja")

    # LLM呼び出し
    try:
        llm = ChatOpenAI(model_name="gpt-4o", openai_api_key=openai_api_key)
        final_chain = LLMChain(llm=llm, prompt=final_blog_prompt_template)
        generated_blog = final_chain.run({
            "directory_tree": directory_tree,
            "file_roles": file_roles,
            "detailed_code_analysis": detailed_code_analysis,
            "project_files_content": project_files_content,
            "github_url": github_url,
            "target_audience": target_audience,
            "blog_tone": blog_tone,
            "additional_requirements": additional_requirements,
            "language": language,
            "blog_outline": blog_outline
        })
        result_store[progress_id] = generated_blog
        flash("最終テックブログを生成しました。", "info")
        return redirect(url_for("preview_blog"))

    except Exception as e:
        flash(f"ブログ生成中にエラーが発生しました: {e}", "error")
        return redirect(url_for("index"))

###############################################################################
# メインフロー: index → process_project → ...
###############################################################################
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # 進捗管理用IDの生成
        progress_id = str(uuid.uuid4())
        session["progress_id"] = progress_id
        progress_store[progress_id] = ""

        github_url = request.form.get("github_url", "").strip()
        uploaded_files = request.files.getlist("project_folder")

        if not ((uploaded_files and len(uploaded_files) > 0) or github_url):
            flash("GithubリポジトリのURLまたはフォルダを指定してください。", "error")
            return redirect(url_for("index"))

        target_audience = request.form.get("target_audience", "エンジニア全般").strip()
        blog_tone = request.form.get("blog_tone", "カジュアルだけど専門性を感じるトーン").strip()
        additional_requirements = request.form.get("additional_requirements", "").strip()
        language = request.form.get("language", "ja")

        # 一時ディレクトリにアップロードファイルを保存
        temp_project_dir = tempfile.mkdtemp()
        if uploaded_files and len(uploaded_files) > 0:
            for file in uploaded_files:
                filename = file.filename
                if not filename:
                    continue
                dest_path = os.path.join(temp_project_dir, filename)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                file.save(dest_path)

        # バックグラウンドで process_project 開始
        threading.Thread(
            target=process_project,
            args=(progress_id, github_url, target_audience, blog_tone, additional_requirements, language, temp_project_dir),
            daemon=True
        ).start()

        flash("プロジェクト解析を開始しました。しばらくお待ちください。", "info")
        return render_template("index.html", progress_id=progress_id)

    return render_template("index.html")

@app.route("/progress", methods=["GET"])
def progress():
    """進捗状況を返すエンドポイント。index.htmlがポーリングして使用する。"""
    progress_id = session.get("progress_id", None)
    if progress_id and progress_id in progress_store:
        return jsonify({"progress": progress_store[progress_id]})
    return jsonify({"progress": "進捗情報がありません。"}), 404

@app.route("/preview_blog", methods=["GET", "POST"])
def preview_blog():
    """
    最終ブログ記事のプレビュー画面
    """
    if request.method == "POST":
        edited_markdown = request.form.get("edited_markdown", "")
        result_store[session.get("progress_id")] = edited_markdown
        return redirect(url_for("preview_blog"))

    progress_id = session.get("progress_id", None)
    blog_markdown = result_store.get(progress_id, "")
    converted_html = markdown.markdown(blog_markdown)
    progress_log = progress_store.get(progress_id, "進捗情報はありません。")

    return render_template("preview.html",
                           blog_markdown=blog_markdown,
                           converted_html=converted_html,
                           progress_log=progress_log)

@app.route("/download_markdown", methods=["GET"])
def download_markdown():
    """
    最終的なMarkdownをダウンロード
    """
    progress_id = session.get("progress_id", None)
    blog_markdown = result_store.get(progress_id, "")
    if not blog_markdown:
        flash("ダウンロードするMarkdownがありません。", "error")
        return redirect(url_for("index"))
    with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp_file:
        tmp_file.write(blog_markdown.encode("utf-8"))
        tmp_file_name = tmp_file.name
    return send_file(tmp_file_name, as_attachment=True, download_name="tech_blog.md", mimetype="text/markdown")


###############################################################################
# Run the Flask App
###############################################################################
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)