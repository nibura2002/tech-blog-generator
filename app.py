import os
import re
import logging
import subprocess
import tempfile
import threading
import uuid
import markdown
import json
import time

from dotenv import load_dotenv
from flask import Flask, request, render_template, redirect, url_for, flash, send_file, session, jsonify, Response, stream_with_context
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

###############################################################################
# 進捗管理（履歴と最新状態）
###############################################################################
progress_history = {}  # 全進捗履歴
progress_status = {}   # 最新の進捗状態

def update_progress(progress_id, message):
    """進捗履歴と最新状態を更新する"""
    global progress_history, progress_status
    if progress_id not in progress_history:
        progress_history[progress_id] = ""
    progress_history[progress_id] += message
    progress_status[progress_id] = message

###############################################################################
# バックグラウンド処理用結果保管
###############################################################################
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

【出力フォーマット】  
以下の JSON 形式に従って出力してください。  
出力例:  
{{
  "sections": [
    {{
      "id": "section_1",
      "title": "ここに機能の名前またはセクションのタイトル",
      "description": "この機能の目的、処理の流れ、設計意図、エラーハンドリングについて記述してください。",
      "code_block": "この機能に対応するコード全体"
    }},
    {{
      "id": "section_2",
      "title": "別の機能やセクションのタイトル",
      "description": "その機能の詳細な解説を記述してください。",
      "code_block": "該当するコード全体"
    }}
  ]
}}

【注意事項】  
- 出力は必ず上記の JSON 形式に従ってください。  
- 各セクションには一意の識別子（例: section_1, section_2, ...）を付与してください。  
- code_block には、そのセクションに対応するコードブロック全体を記述してください。省略は禁止です。
- JSON 形式以外の出力は一切行わないでください。

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

3) **詳細なコード解説**:  
{detailed_code_analysis}

※ 注意: 上記「詳細なコード解説」は、各機能ごとに一意の識別子を付与した JSON 形式で出力されています。  
アウトライン作成時は、対応するコードブロックを参照する際に、各セクションの識別子（例: section_1, section_2, …）を必ず記載してください。

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
- 各章・節には、取り上げる話題および対応するコードブロック（上記「詳細なコード解説」で出力された JSON の識別子を参照する形）を必ず示してください。
- Markdown 形式で出力してください。
- 補足的な説明等は記述しないでください。
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
- ブログ記事以外の出力は禁止です。補足的な説明等も処理の邪魔になるため、記述しないでください。
- アウトプットが長くなった場合、分割して出力してください。省略は禁止です。
- 分割する場合、最後に<<<CONTINUE>>>というマーカーで終了する必要があります。
"""
)

###############################################################################
# バックグラウンド処理関数（プロジェクト解析）
###############################################################################
def process_project(progress_id, github_url, target_audience, blog_tone, additional_requirements, language, temp_project_dir):
    try:
        update_progress(progress_id, "Step 1: プロジェクトファイルの取得を開始します...\n")
        if os.listdir(temp_project_dir):
            update_progress(progress_id, "フォルダアップロードによる取得完了。\n")
            logger.info("Project files obtained from uploaded folder.")
        else:
            clone_cmd = ["git", "clone", github_url, temp_project_dir]
            try:
                subprocess.check_output(clone_cmd, stderr=subprocess.STDOUT)
                update_progress(progress_id, "GitHubリポジトリからのクローンに成功。\n")
                logger.info("Project files obtained from GitHub clone.")
            except subprocess.CalledProcessError as e:
                update_progress(progress_id, "GitHubリポジトリのクローンに失敗しました。\n")
                logger.error("GitHub clone failed: %s", e.output.decode("utf-8"))
                return

        update_progress(progress_id, "Step 2: ディレクトリ構造を取得中...\n")
        directory_tree = get_directory_tree(temp_project_dir)
        update_progress(progress_id, "ディレクトリ構造の取得完了。\n")
        logger.info("Directory tree obtained.")

        update_progress(progress_id, "Step 3: 各ファイルの役割を要約中...\n")
        llm = ChatOpenAI(model_name="o3-mini", openai_api_key=openai_api_key)
        file_role_chain = LLMChain(llm=llm, prompt=file_role_prompt_template)
        file_roles = file_role_chain.run({"directory_tree": directory_tree})
        update_progress(progress_id, "各ファイルの役割要約完了。\n")
        logger.info("File roles summary obtained.")

        update_progress(progress_id, "Step 4: 各ファイルの詳細なコード解説を取得中...\n")
        detailed_code_analysis = ""
        all_files = []
        disallowed_extensions = (
            ".lock", ".gitignore", ".dockerignore", ".npmignore", ".yarnignore",
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".tiff", ".ico",
            ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv",
            ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a",
            ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
            ".exe", ".dll", ".so", ".bin", ".app", ".msi", ".deb", ".rpm",
            ".ttf", ".otf", ".woff", ".woff2",
            ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"
        )
        for dirpath, dirnames, filenames in os.walk(temp_project_dir):
            dirnames[:] = [d for d in dirnames if "__pycache__" not in d and ".git" not in d and ".vscode" not in d]
            for file in filenames:
                if file.lower().endswith(disallowed_extensions):
                    continue
                if "__pycache__" in dirpath:
                    continue
                all_files.append(os.path.join(dirpath, file))
        total_files = len(all_files)
        update_progress(progress_id, f"対象ファイル数: {total_files} 件\n")
        logger.info("Total files to analyze: %d", total_files)

        for i, file_path in enumerate(all_files, 1):
            relative_file_path = os.path.relpath(file_path, temp_project_dir)
            update_progress(progress_id, f"ファイル解析中: {i}/{total_files} -> {relative_file_path}\n")
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
                update_progress(progress_id, f"ファイル解析失敗: {relative_file_path} - {e}\n")
                logger.warning("Failed to analyze file %s: %s", file_path, e)
        update_progress(progress_id, "各ファイルの詳細なコード解説完了。\n")
        project_files_content = read_project_files(temp_project_dir)

        update_progress(progress_id, "一旦基本情報の抽出が完了しました。\n")
        
        # 結果保存
        result_store[progress_id + "_tree"] = directory_tree
        result_store[progress_id + "_roles"] = file_roles
        result_store[progress_id + "_analysis"] = detailed_code_analysis
        result_store[progress_id + "_files"] = project_files_content

        # Step 5: アウトライン生成
        update_progress(progress_id, "Step 5: ブログアウトラインを生成中...\n")
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
        logger.info("Blog outline generated.")
        result_store[progress_id + "_outline"] = blog_outline
        update_progress(progress_id, "ブログアウトラインの生成が完了しました。\n")

        logger.info("Project analysis completed.")

    except Exception as e:
        update_progress(progress_id, f"処理中にエラー発生: {e}\n")


###############################################################################
# バックグラウンド処理関数（最終ブログ生成）
###############################################################################
def get_full_blog(llm, initial_response, params, progress_id, max_iterations=10):
    directory_tree = result_store.get(progress_id + "_tree", "")
    file_roles = result_store.get(progress_id + "_roles", "")
    detailed_code_analysis = result_store.get(progress_id + "_analysis", "")
    project_files_content = result_store.get(progress_id + "_files", "")
    blog_outline = result_store.get(progress_id + "_outline", "")
    
    full_blog = initial_response
    marker_pattern = re.compile(r"<{1,4}CONTINUE>{1,4}(?:\s*```)?(?:\n```)?\s*$", re.IGNORECASE)
    
    for _ in range(max_iterations):
        if not marker_pattern.search(full_blog):
            break

        update_progress(progress_id, "分割された出力を生成中...\n")

        context_prompt = PromptTemplate(
            input_variables=["directory_tree", "file_roles", "detailed_code_analysis", "project_files_content", "github_url", "target_audience", "blog_tone", "additional_requirements", "language", "blog_outline", "full_blog"],
            template="""
途中まで生成されたブログ記事と、そのブログ生成に使用したプロンプト情報を提供します。
ブログ記事とプロンプト情報を基に、続きを生成してください。

ブログ記事:
{full_blog}

プロンプト:
####################################################################################################
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
- ブログ記事以外の出力は禁止です。補足的な説明等も処理の邪魔になるため、記述しないでください。
- アウトプットが長くなった場合、分割して出力してください。省略は禁止です。
- 分割する場合、最後に<<<CONTINUE>>>というマーカーで終了する必要があります。
####################################################################################################
"""
        ).format(
            directory_tree=directory_tree,
            file_roles=file_roles,
            detailed_code_analysis=detailed_code_analysis,
            project_files_content=project_files_content,
            github_url=params.get("github_url", ""),
            target_audience=params.get("target_audience", ""),
            blog_tone=params.get("blog_tone", ""),
            additional_requirements=params.get("additional_requirements", ""),
            language=params.get("language", ""),
            blog_outline=blog_outline,
            full_blog=full_blog
        )
        next_chunk = llm.predict(context_prompt)
        full_blog = marker_pattern.sub("", full_blog) + next_chunk

    return full_blog

def process_final_blog(progress_id, params):
    try:
        logger.info("process_final_blog 開始: progress_id=%s", progress_id)
        update_progress(progress_id, "Step 6: 最終テックブログ生成中...\n")
        llm = ChatOpenAI(model_name="gpt-4o", openai_api_key=openai_api_key)
        final_chain = LLMChain(llm=llm, prompt=final_blog_prompt_template)
        
        initial_response = final_chain.run({
            "directory_tree": result_store.get(progress_id + "_tree", ""),
            "file_roles": result_store.get(progress_id + "_roles", ""),
            "detailed_code_analysis": result_store.get(progress_id + "_analysis", ""),
            "project_files_content": result_store.get(progress_id + "_files", ""),
            "github_url": params["github_url"],
            "target_audience": params["target_audience"],
            "blog_tone": params["blog_tone"],
            "additional_requirements": params["additional_requirements"],
            "language": params["language"],
            "blog_outline": result_store.get(progress_id + "_outline", "")
        })
        
        full_blog = get_full_blog(llm, initial_response, params, progress_id)
        
        result_store[progress_id] = full_blog
        update_progress(progress_id, "最終テックブログの生成が完了しました。\n")
        logger.info("process_final_blog 完了: progress_id=%s", progress_id)
    except Exception as e:
        update_progress(progress_id, f"最終テックブログ生成中にエラーが発生しました: {e}\n")
        logger.error("process_final_blog エラー: %s", e)

###############################################################################
# SSE 用の進捗更新エンドポイント
###############################################################################
@app.route('/progress_stream')
def progress_stream():
    progress_id = session.get("progress_id", None)
    if not progress_id:
        return Response("data: {\"progress\": \"進捗情報がありません。\", \"history\": \"\"}\n\n", mimetype="text/event-stream")

    def event_stream():
        while True:
            current_status = progress_status.get(progress_id, "処理が開始されていません。")
            current_history = progress_history.get(progress_id, "進捗情報はありません。")
            data = json.dumps({"progress": current_status, "history": current_history})
            yield f"data: {data}\n\n".encode("utf-8")
            if (current_status.find("最終テックブログの生成が完了しました") != -1 or
                current_status.find("ブログアウトラインの生成が完了しました") != -1):
                break
            time.sleep(3)
    return Response(stream_with_context(event_stream()),
                mimetype="text/event-stream", direct_passthrough=True)

###############################################################################
# Markdownダウンロード
###############################################################################
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
# メインフロー: index.html で実装（POST送信で処理の種類を判別）
###############################################################################
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # 新規プロジェクト送信の場合のみセッション初期化
        if "project_folder" in request.files or request.form.get("github_url", ""):
            session.pop("progress_id", None)
            session.pop("params", None)
            session.pop("final_blog_started", None)

        # ブログ本文更新（アウトプット編集）
        if "edited_markdown" in request.form:
            progress_id = session.get("progress_id", None)
            if not progress_id:
                flash("進捗IDがありません。", "error")
                return redirect(url_for("index"))
            edited_markdown = request.form.get("edited_markdown", "")
            result_store[progress_id] = edited_markdown
            flash("ブログが更新されました。", "info")
            return redirect(url_for("index"))
        # アウトライン更新（ユーザーによる修正）
        elif "edited_outline" in request.form:
            progress_id = session.get("progress_id", None)
            if not progress_id:
                flash("進捗IDがありません。", "error")
                return redirect(url_for("index"))
            edited_outline = request.form.get("edited_outline", "")
            result_store[progress_id + "_outline"] = edited_outline
            flash("アウトラインが更新されました。", "info")
            return redirect(url_for("index"))
        else:
            # プロジェクト送信の場合
            params = get_common_params_from_form()
            progress_id = str(uuid.uuid4())
            session["progress_id"] = progress_id
            session["params"] = params  # 後で最終ブログ生成に利用
            update_progress(progress_id, "処理を開始します...\n")

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
            return render_template("index.html", progress_id=progress_id, progress_log=progress_history.get(progress_id, ""))
    else:
        progress_id = session.get("progress_id", None)
        blog_markdown = ""
        blog_outline = ""
        converted_html = ""
        progress_log = ""
        # viewType の判定：初期、アウトライン、ステータス、最終
        if progress_id:
            blog_markdown = result_store.get(progress_id, "")
            blog_outline = result_store.get(progress_id + "_outline", "")
            progress_log = progress_history.get(progress_id, "進捗情報はありません。")
            converted_html = markdown.markdown(blog_markdown, extensions=['fenced_code', 'codehilite'])
        if blog_markdown:
            viewType = "final"
        elif blog_outline and (progress_status.get(progress_id, "")).find("生成中") == -1:
            viewType = "outline"
        elif progress_status.get(progress_id, "").find("生成中") != -1:
            viewType = "status"
        else:
            viewType = "initial"
        return render_template("index.html",
                               progress_id=progress_id,
                               blog_markdown=blog_markdown,
                               blog_outline=blog_outline,
                               converted_html=converted_html,
                               progress_log=progress_log,
                               viewType=viewType)

###############################################################################
# 最終ブログ生成（POSTのみ）
###############################################################################
@app.route("/generate_final_blog", methods=["POST"])
def generate_final_blog():
    progress_id = session.get("progress_id", None)
    if not progress_id:
        return jsonify({"error": "progress_idがありません。"}), 400
    params = session.get("params", {})
    if not session.get("final_blog_started", False):
        session["final_blog_started"] = True
        update_progress(progress_id, "最終テックブログの生成が開始しました。\n")
        threading.Thread(
            target=process_final_blog,
            args=(progress_id, params),
            daemon=True
        ).start()
    return jsonify({"status": "最終テックブログ生成開始"}), 200

###############################################################################
# Run the Flask App
###############################################################################
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)