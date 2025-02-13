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

# Redirect to www subdomain
@app.before_request
def redirect_to_www():
    host = request.headers.get("Host", "")
    if "localhost" in host or "127.0.0.1" in host:
        return None
    if not host.startswith("www."):
        target_url = request.url.replace(host, "www." + host, 1)
        return redirect(target_url, code=301)

# 進捗管理用のグローバル辞書
progress_store = {}
# バックグラウンドでの生成結果を格納するグローバル辞書
result_store = {}

###############################################################################
# Helper Functions for Parameter Retrieval
###############################################################################
def get_common_params_from_form():
    return {
        "github_url": request.form.get("github_url", "").strip(),
        "target_audience": request.form.get("target_audience", "エンジニア全般").strip(),
        "blog_tone": request.form.get("blog_tone", "カジュアルだけど専門性を感じるトーン").strip(),
        "additional_requirements": request.form.get("additional_requirements", "").strip(),
        "language": request.form.get("language", "ja").strip()
    }

def get_common_params_from_args():
    return {
        "github_url": request.args.get("github_url", ""),
        "target_audience": request.args.get("target_audience", "エンジニア全般"),
        "blog_tone": request.args.get("blog_tone", "カジュアルだけど専門性を感じるトーン"),
        "additional_requirements": request.args.get("additional_requirements", ""),
        "language": request.args.get("language", "ja")
    }

###############################################################################
# Utility functions
###############################################################################
def read_project_files(root_dir):
    logger.info("Reading project files from: %s", root_dir)
    all_text = []
    max_size = 20 * 1024 * 1024  # 20MB
    max_chars = 20000
    disallowed_extensions = (
        ".lock",
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".tiff", ".ico",
        ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv",
        ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a",
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
        ".exe", ".dll", ".so", ".bin", ".app", ".msi", ".deb", ".rpm",
        ".ttf", ".otf", ".woff", ".woff2",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"
    )
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if "__pycache__" not in d]
        for file in filenames:
            file_path = os.path.join(dirpath, file)
            if file.lower().endswith(disallowed_extensions):
                logger.info("Skipping disallowed file: %s", file_path)
                continue
            if "__pycache__" in file_path:
                logger.info("Skipping __pycache__ file: %s", file_path)
                continue
            try:
                size = os.path.getsize(file_path)
                if size > max_size:
                    logger.info("Skipping large file (>20MB): %s (size=%d bytes)", file_path, size)
                    continue
            except Exception as e:
                logger.warning("Could not determine file size for %s: %s", file_path, e)
                continue
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if len(content) > max_chars:
                    logger.info("Skipping file due to excessive length (>20000 chars): %s (length=%d)", file_path, len(content))
                    continue
                relative_path = os.path.relpath(file_path, root_dir)
                header = f"\n\n### File: {relative_path}\n"
                all_text.append(header + content)
            except Exception as e:
                logger.warning("Could not read file %s: %s", file_path, e)
                continue
    combined_text = "\n".join(all_text)
    logger.info("Completed reading project files. Total length: %d characters", len(combined_text))
    return combined_text

def get_directory_tree(root_dir):
    tree_lines = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        level = dirpath.replace(root_dir, '').count(os.sep)
        indent = "│   " * level
        tree_lines.append(f"{indent}├── {os.path.basename(dirpath)}/")
        for f in filenames:
            tree_lines.append(f"{indent}│   ├── {f}")
    return "\n".join(tree_lines)

def strip_code_fences(text: str) -> str:
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
    input_variables=["file_content", "file_path", "language"],
    template="""
# ファイル名: {file_path}

以下はファイル「{file_path}」の完全なコードです。  
解説は {language} で行ってください。  
出力は以下の2部構成に従い、Markdown形式で記述してください.

----------------------------------------
【セクション 1: 機能概要とコードブロックのペア】

各主要な機能について、**章**（大項目）、**節**（中項目）、**項**（小項目）に分け、それぞれに対して以下の形式で出力してください。

- **機能名/セクション名**: [ここに機能の名前またはセクションのタイトル]
  - **機能概要**:  
    この機能の目的、処理の流れ、設計意図、エラーハンドリングの実装について記載してください。
  - **対応するコードブロック**:  
    この機能に対応するコードを完全な形で記載してください。（省略せず、全行を示すこと）

----------------------------------------
【セクション 2: ファイル全体のコード】

- **ファイル名**: {file_path}
- **コード全文**:
```python
{file_content}
```
----------------------------------------

【出力要件】
- 決められた形式のアウトプット以外の出力は禁止です。それ以外の補足説明等は禁止です。

以下、対象ファイルのコードです:
{file_content}
"""
)

blog_outline_prompt_template = PromptTemplate(
    input_variables=["directory_tree", "file_roles", "detailed_code_analysis", "project_files_content", "github_url", "target_audience", "blog_tone", "additional_requirements", "language"],
    template="""
あなたは有能なソフトウェアエンジニア兼テックライターです。  
以下のコンテキスト情報を基に、テックブログの章立て（アウトライン）を考案してください。

【コンテキスト】
1) **ディレクトリ構造**:  
{directory_tree}

2) **ファイルの役割概要**:  
{file_roles}

3) **詳細なコード解説**  
   (各機能と対応するコードブロックのペアを、コードの流れに沿ってまとめる):  
{detailed_code_analysis}

4) **全ファイル内容** (参考用):  
{project_files_content}

【追加情報】
- GitHubリポジトリURL: {github_url}
- 想定読者: {target_audience}
- トーン: {blog_tone}
- その他リクエスト: {additional_requirements}
- 解説言語: {language}

【出力要件】
- ブログ全体のアウトラインを、**章**（大項目）、**節**（中項目）、**項**（小項目）に分けた形式で箇条書きしてください。
- 各章・節には、取り上げる話題および対応するコードブロック（対象ファイルのコードブロックそのもの）のリストを示してください。
- テックブログの読者は処理の流れにへの興味が強いため、処理の流れと対応するコードブロックに関する章、節、項は細かく記述した上で、機能全体を網羅できるようにしてください。
- Markdown形式で出力してください。
"""
)

final_blog_prompt_template = PromptTemplate(
    input_variables=["directory_tree", "file_roles", "detailed_code_analysis", "project_files_content", "github_url", "target_audience", "blog_tone", "additional_requirements", "language", "blog_outline"],
    template="""
あなたは有能なソフトウェアエンジニア兼テックライターです。

以下の情報と、事前に確定したアウトラインを基に、最終的なテックブログ記事を{language}で作成してください。

【事前に確定したアウトライン】
{blog_outline}

【その他のコンテキスト】
1) **ディレクトリ構造**:  
{directory_tree}

2) **ファイルの役割概要**:  
{file_roles}

3) **詳細なコード解説**:  
{detailed_code_analysis}

4) **全ファイル内容**:  
{project_files_content}

【追加情報】
- GitHubリポジトリURL: {github_url}
- 想定読者: {target_audience}
- トーン: {blog_tone}
- その他リクエスト: {additional_requirements}

【出力要件】
- アウトラインに沿って、読みやすいMarkdown形式の記事を作成してください。
- 記事は、**章**（大項目）、**節**（中項目）、**項**（小項目）に分けた構成で、各章には取り上げる話題と対応するコードブロック（対象ファイルのコードブロックそのもの）のリストが含まれていること。
- コードブロックは省略せず、完全な内容を示してください。
- テックブログの読者は処理の流れにへの興味が強いため、処理の流れと対応するコードブロックの説明のボリュームを多くしてください。
- 各項の文字数は、コードを除いて100文字以上必要です。100-500文字程度にしてください
- アウトプットが長くなった場合、分割して出力してください。省略は禁止です。   
"""
)

###############################################################################
# バックグラウンド処理関数
###############################################################################
def process_project(progress_id, github_url, target_audience, blog_tone, additional_requirements, language, temp_project_dir):
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
                logger.info("Project files obtained from GitHub clone.")
            except subprocess.CalledProcessError as e:
                progress_store[progress_id] += "GitHubリポジトリのクローンに失敗しました。\n"
                logger.error("GitHub clone failed: %s", e.output.decode("utf-8"))
                return

        progress_store[progress_id] += "Step 2: ディレクトリ構造を取得中...\n"
        directory_tree = get_directory_tree(temp_project_dir)
        progress_store[progress_id] += "ディレクトリ構造の取得完了。\n"
        logger.info("Directory tree obtained.")

        progress_store[progress_id] += "Step 3: 各ファイルの役割を要約中...\n"
        llm = ChatOpenAI(model_name="o3-mini", openai_api_key=openai_api_key)
        file_role_chain = LLMChain(llm=llm, prompt=file_role_prompt_template)
        file_roles = file_role_chain.run({"directory_tree": directory_tree})
        progress_store[progress_id] += "各ファイルの役割要約完了。\n"
        logger.info("File roles summary obtained.")

        progress_store[progress_id] += "Step 4: 各ファイルの詳細なコード解説を取得中...\n"
        detailed_code_analysis = ""
        all_files = []
        disallowed_extensions = (
            ".lock",
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".tiff", ".ico",
            ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv",
            ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a",
            ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
            ".exe", ".dll", ".so", ".bin", ".app", ".msi", ".deb", ".rpm",
            ".ttf", ".otf", ".woff", ".woff2",
            ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"
        )
        for dirpath, dirnames, filenames in os.walk(temp_project_dir):
            dirnames[:] = [d for d in dirnames if "__pycache__" not in d]
            for file in filenames:
                if file.lower().endswith(disallowed_extensions):
                    continue
                if "__pycache__" in dirpath:
                    continue
                all_files.append(os.path.join(dirpath, file))
        total_files = len(all_files)
        progress_store[progress_id] += f"対象ファイル数: {total_files} 件\n"
        logger.info("Total files to analyze: %d", total_files)

        for i, file_path in enumerate(all_files, 1):
            relative_file_path = os.path.relpath(file_path, temp_project_dir)
            progress_store[progress_id] += f"ファイル解析中: {i}/{total_files} -> {relative_file_path}\n"
            logger.info("Processing file %d/%d: %s", i, total_files, relative_file_path)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    file_content = f.read()
                code_detail_chain = LLMChain(llm=llm, prompt=code_detail_prompt_template)
                file_detail = code_detail_chain.run({
                    "file_path": relative_file_path,
                    "file_content": file_content,
                    "language": language
                })
                detailed_code_analysis += f"\n\n## {relative_file_path}\n" + file_detail
            except Exception as e:
                progress_store[progress_id] += f"ファイル解析失敗: {relative_file_path} - {e}\n"
                logger.warning("Failed to analyze file %s: %s", file_path, e)
        progress_store[progress_id] += "各ファイルの詳細なコード解説完了。\n"
        project_files_content = read_project_files(temp_project_dir)

        progress_store[progress_id] += "一旦基本情報の抽出が完了しました。\n"
        
        result_store[progress_id + "_tree"] = directory_tree
        result_store[progress_id + "_roles"] = file_roles
        result_store[progress_id + "_analysis"] = detailed_code_analysis
        result_store[progress_id + "_files"] = project_files_content

        # **アウトライン生成をここで実行**
        progress_store[progress_id] += "Step 5: ブログアウトラインを生成中...\n"
        outline_chain = LLMChain(llm=llm, prompt=blog_outline_prompt_template)
        blog_outline = outline_chain.run({
            "directory_tree": directory_tree,
            "file_roles": file_roles,
            "detailed_code_analysis": detailed_code_analysis,
            "project_files_content": project_files_content,
            "github_url": github_url,
            "target_audience": target_audience,
            "blog_tone": blog_tone,
            "additional_requirements": additional_requirements,
            "language": language
        })
        result_store[progress_id + "_outline"] = blog_outline
        progress_store[progress_id] += "ブログアウトラインの生成が完了しました。\n"

        # 解析データを保存
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
    progress_id = session.get("progress_id", None)
    if not progress_id:
        flash("progress_idがありません。", "error")
        return redirect(url_for("index"))

    directory_tree = result_store.get(progress_id + "_tree", "")
    file_roles = result_store.get(progress_id + "_roles", "")
    detailed_code_analysis = result_store.get(progress_id + "_analysis", "")
    project_files_content = result_store.get(progress_id + "_files", "")
    params = get_common_params_from_args()
    try:
        llm = ChatOpenAI(model_name="gpt-4o", openai_api_key=openai_api_key)
        outline_chain = LLMChain(llm=llm, prompt=blog_outline_prompt_template)
        blog_outline = outline_chain.run({
            "directory_tree": directory_tree,
            "file_roles": file_roles,
            "detailed_code_analysis": detailed_code_analysis,
            "project_files_content": project_files_content,
            "github_url": params["github_url"],
            "target_audience": params["target_audience"],
            "blog_tone": params["blog_tone"],
            "additional_requirements": params["additional_requirements"],
            "language": params["language"]
        })
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
        edited_outline = request.form.get("edited_outline", "")
        result_store[outline_key] = edited_outline
        return redirect(url_for("generate_final_blog"))

    blog_outline = result_store.get(outline_key, "まだアウトラインが生成されていません。")
    return render_template("preview_outline.html", blog_outline=blog_outline)

###############################################################################
# 最終ブログ生成
###############################################################################
@app.route("/generate_final_blog", methods=["GET", "POST"])
def generate_final_blog():
    progress_id = session.get("progress_id", None)
    if not progress_id:
        flash("progress_idがありません。", "error")
        return redirect(url_for("index"))

    directory_tree = result_store.get(progress_id + "_tree", "")
    file_roles = result_store.get(progress_id + "_roles", "")
    detailed_code_analysis = result_store.get(progress_id + "_analysis", "")
    project_files_content = result_store.get(progress_id + "_files", "")
    blog_outline = result_store.get(progress_id + "_outline", "")
    params = get_common_params_from_args()
    try:
        llm = ChatOpenAI(model_name="gpt-4o", openai_api_key=openai_api_key)
        final_chain = LLMChain(llm=llm, prompt=final_blog_prompt_template)
        generated_blog = final_chain.run({
            "directory_tree": directory_tree,
            "file_roles": file_roles,
            "detailed_code_analysis": detailed_code_analysis,
            "project_files_content": project_files_content,
            "github_url": params["github_url"],
            "target_audience": params["target_audience"],
            "blog_tone": params["blog_tone"],
            "additional_requirements": params["additional_requirements"],
            "language": params["language"],
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
        params = get_common_params_from_form()
        progress_id = str(uuid.uuid4())
        session["progress_id"] = progress_id
        progress_store[progress_id] = "処理を開始します...\n"

        github_url = params["github_url"]
        uploaded_files = request.files.getlist("project_folder")
        if not ((uploaded_files and len(uploaded_files) > 0) or github_url):
            flash("GithubリポジトリのURLまたはフォルダを指定してください。", "error")
            return redirect(url_for("index"))

        target_audience = params["target_audience"]
        blog_tone = params["blog_tone"]
        additional_requirements = params["additional_requirements"]
        language = params["language"]

        temp_project_dir = tempfile.mkdtemp()
        if uploaded_files and len(uploaded_files) > 0:
            for file in uploaded_files:
                filename = file.filename
                if not filename:
                    continue
                dest_path = os.path.join(temp_project_dir, filename)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                file.save(dest_path)

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
    """
    現在の進捗状況を返すエンドポイント
    """
    progress_id = session.get("progress_id", None)
    
    if not progress_id:
        return jsonify({"progress": "進捗情報がありません。"}), 404

    # progress_store に progress_id がない場合も 404 を返さず、適切な初期値を返す
    progress_info = progress_store.get(progress_id, "処理が開始されていません。")
    
    return jsonify({"progress": progress_info})

@app.route("/preview_blog", methods=["GET", "POST"])
def preview_blog():
    if request.method == "POST":
        edited_markdown = request.form.get("edited_markdown", "")
        result_store[session.get("progress_id")] = edited_markdown
        return redirect(url_for("preview_blog"))
    progress_id = session.get("progress_id", None)
    blog_markdown = result_store.get(progress_id, "")
    converted_html = markdown.markdown(blog_markdown, extensions=['fenced_code', 'codehilite'])
    progress_log = progress_store.get(progress_id, "進捗情報はありません。")
    return render_template("preview.html",
                           blog_markdown=blog_markdown,
                           converted_html=converted_html,
                           progress_log=progress_log)

@app.route("/download_markdown", methods=["GET"])
def download_markdown():
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)