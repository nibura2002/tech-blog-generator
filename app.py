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

# LLM用プロンプトのインポート
from const.prompt import (
    file_role_prompt_template,
    code_detail_prompt_template,
    blog_outline_prompt_template,
    final_blog_prompt_template,
    context_blog_prompt_template
)

# Disallowed file extensionsのインポート
from const.const import DISALLOWED_EXTENSIONS, MAX_FILE_SIZE, MAX_FILE_LENGTH, IGNORED_DIRECTORIES, DEFAULT_ENCODING

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
    raise EnvironmentError(
        "OPENAI_API_KEY is not set. Please set it in the .env file.")
logger.info("OPENAI_API_KEY successfully loaded.")

###############################################################################
# Flask App Initialization
###############################################################################
app = Flask(__name__)
app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "replace_with_a_secure_random_key")
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
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    MAX_FILE_LENGTH = 20000
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRECTORIES]
        for file in filenames:
            file_path = os.path.join(dirpath, file)
            if file.lower().endswith(DISALLOWED_EXTENSIONS):
                logger.info("Skipping disallowed file: %s", file_path)
                continue
            if "__pycache__" in file_path:
                logger.info("Skipping __pycache__ file: %s", file_path)
                continue
            try:
                size = os.path.getsize(file_path)
                if size > MAX_FILE_SIZE:
                    logger.info(
                        "Skipping large file (>20MB): %s (size=%d bytes)",
                        file_path,
                        size)
                    continue
            except Exception as e:
                logger.warning(
                    "Could not determine file size for %s: %s", file_path, e)
                continue
            try:
                with open(file_path, "r", encoding=DEFAULT_ENCODING, errors="ignore") as f:
                    content = f.read()
                if len(content) > MAX_FILE_LENGTH:
                    logger.info(
                        "Skipping file due to excessive length (>20000 chars): %s (length=%d)",
                        file_path,
                        len(content))
                    continue
                relative_path = os.path.relpath(file_path, root_dir)
                header = f"\n\n### File: {relative_path}\n"
                all_text.append(header + content)
            except Exception as e:
                logger.warning("Could not read file %s: %s", file_path, e)
                continue
    combined_text = "\n".join(all_text)
    logger.info(
        "Completed reading project files. Total length: %d characters",
        len(combined_text))
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
    # Remove markdown code fences. This is necessary for the HTML conversion.
    # Remove ```markdown at the top and ``` at the bottom
    text = re.sub(r"```(?:markdown)?\n", "", text, count=1)


###############################################################################
# 共通アウトライン生成関数
###############################################################################


def generate_outline_common(
        progress_id,
        params,
        directory_tree,
        file_roles,
        detailed_code_analysis,
        project_files_content):
    update_progress(progress_id, "アウトライン生成中...\n")
    llm = ChatOpenAI(model_name="o3-mini", openai_api_key=openai_api_key)
    outline_chain = blog_outline_prompt_template | llm
    blog_outline = outline_chain.invoke({
        "directory_tree": directory_tree,
        "file_roles": file_roles,
        "detailed_code_analysis": detailed_code_analysis,
        "project_files_content": project_files_content,
        "github_url": params.get("github_url", ""),
        "target_audience": params.get("target_audience", ""),
        "blog_tone": params.get("blog_tone", ""),
        "additional_requirements": params.get("additional_requirements", ""),
        "language": params.get("language", "")
    }).content
    result_store[progress_id + "_outline"] = blog_outline
    update_progress(progress_id, "ブログアウトラインの生成が完了しました。\n")
    return blog_outline

###############################################################################
# バックグラウンド処理関数（プロジェクト解析）
###############################################################################


def process_project(
        progress_id,
        github_url,
        target_audience,
        blog_tone,
        additional_requirements,
        language,
        temp_project_dir):
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
                logger.error(
                    "GitHub clone failed: %s",
                    e.output.decode(DEFAULT_ENCODING))
                return

        update_progress(progress_id, "Step 2: ディレクトリ構造を取得中...\n")
        directory_tree = get_directory_tree(temp_project_dir)
        update_progress(progress_id, "ディレクトリ構造の取得完了。\n")
        logger.info("Directory tree obtained.")

        update_progress(progress_id, "Step 3: 各ファイルの役割を要約中...\n")
        llm = ChatOpenAI(model_name="o3-mini", openai_api_key=openai_api_key)
        file_role_chain = file_role_prompt_template | llm
        file_roles = file_role_chain.invoke(
            {"directory_tree": directory_tree}).content
        update_progress(progress_id, "各ファイルの役割要約完了。\n")
        logger.info("File roles summary obtained.")

        update_progress(progress_id, "Step 4: 各ファイルの詳細なコード解説を取得中...\n")
        detailed_code_analysis = ""
        all_files = []
        for dirpath, dirnames, filenames in os.walk(temp_project_dir):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRECTORIES]
            for file in filenames:
                if file.lower().endswith(DISALLOWED_EXTENSIONS):
                    continue
                all_files.append(os.path.join(dirpath, file))
        total_files = len(all_files)
        update_progress(progress_id, f"対象ファイル数: {total_files} 件\n")
        logger.info("Total files to analyze: %d", total_files)

        for i, file_path in enumerate(all_files, 1):
            relative_file_path = os.path.relpath(file_path, temp_project_dir)
            update_progress(
                progress_id,
                f"ファイル解析中: {i}/{total_files} -> {relative_file_path}\n")
            logger.info(
                "Processing file %d/%d: %s",
                i,
                total_files,
                relative_file_path)
            try:
                with open(file_path, "r", encoding=DEFAULT_ENCODING, errors="ignore") as f:
                    file_content = f.read()
                code_detail_chain = code_detail_prompt_template | llm
                file_detail = code_detail_chain.invoke({
                    "file_path": relative_file_path,
                    "file_content": file_content,
                    "language": language
                }).content
                detailed_code_analysis += f"\n\n## {relative_file_path}\n" + file_detail
            except Exception as e:
                update_progress(progress_id,
                                f"ファイル解析失敗: {relative_file_path} - {e}\n")
                logger.warning("Failed to analyze file %s: %s", file_path, e)
        update_progress(progress_id, "各ファイルの詳細なコード解説完了。\n")
        project_files_content = read_project_files(temp_project_dir)

        update_progress(progress_id, "一旦基本情報の抽出が完了しました。\n")

        # 取得した各種情報を result_store に保存
        result_store[progress_id + "_tree"] = directory_tree
        result_store[progress_id + "_roles"] = file_roles
        result_store[progress_id + "_analysis"] = detailed_code_analysis
        result_store[progress_id + "_files"] = project_files_content

        # Step 5: アウトライン生成（共通関数を利用）
        generate_outline_common(progress_id, {
            "github_url": github_url,
            "target_audience": target_audience,
            "blog_tone": blog_tone,
            "additional_requirements": additional_requirements,
            "language": language
        }, directory_tree, file_roles, detailed_code_analysis, project_files_content)

        logger.info("Project analysis completed.")

    except Exception as e:
        update_progress(progress_id, f"処理中にエラー発生: {e}\n")

###############################################################################
# アウトライン再生成処理（関数として切り分け）
###############################################################################


def process_outline_regeneration(progress_id, params):
    update_progress(progress_id, "アウトライン再生成中...\n")
    # 以下、必要な各種データはすでに result_store に保存されている前提
    directory_tree = result_store.get(progress_id + "_tree", "")
    file_roles = result_store.get(progress_id + "_roles", "")
    detailed_code_analysis = result_store.get(progress_id + "_analysis", "")
    project_files_content = result_store.get(progress_id + "_files", "")
    generate_outline_common(
        progress_id,
        params,
        directory_tree,
        file_roles,
        detailed_code_analysis,
        project_files_content)

###############################################################################
# バックグラウンド処理関数（最終ブログ生成）
###############################################################################


def get_full_blog(
        llm,
        initial_response,
        params,
        progress_id,
        max_iterations=10):
    directory_tree = result_store.get(progress_id + "_tree", "")
    file_roles = result_store.get(progress_id + "_roles", "")
    detailed_code_analysis = result_store.get(progress_id + "_analysis", "")
    project_files_content = result_store.get(progress_id + "_files", "")
    blog_outline = result_store.get(progress_id + "_outline", "")

    full_blog = initial_response
    marker_pattern = re.compile(
        r"<{1,4}CONTINUE>{1,4}(?:\s*```)?(?:\n```)?\s*$",
        re.IGNORECASE)

    for _ in range(max_iterations):
        if not marker_pattern.search(full_blog):
            break

        update_progress(progress_id, "分割された出力を生成中...\n")

        # context_blog_prompt_template を利用して、プロンプトの内容を生成
        context_prompt = context_blog_prompt_template.format(
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
        next_chunk = llm.invoke(context_prompt).content
        full_blog = marker_pattern.sub("", full_blog) + next_chunk

    return full_blog


def process_final_blog(progress_id, params):
    try:
        logger.info("process_final_blog 開始: progress_id=%s", progress_id)
        update_progress(progress_id, "Step 6: 最終テックブログ生成中...\n")
        llm = ChatOpenAI(model_name="gpt-4o", openai_api_key=openai_api_key)
        final_chain = final_blog_prompt_template | llm

        initial_response = final_chain.invoke({
            "directory_tree": result_store.get(progress_id + "_tree", ""),
            "file_roles": result_store.get(progress_id + "_roles", ""),
            "detailed_code_analysis": result_store.get(progress_id + "_analysis", ""),
            "project_files_content": result_store.get(progress_id + "_files", ""),
            "github_url": params["github_url"],
            "target_audience": params["target_audience"],
            "blog_tone": params["blog_tone"],
            "additional_requirements": params["additional_requirements"],
            "language": params["language"],
            "blog_outline": result_store.get(progress_id + "_outline", ""),
            "existing_blog": result_store.get(progress_id, "")
        }).content

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
        return Response(
            "data: {\"progress\": \"進捗情報がありません。\", \"history\": \"\"}\n\n",
            mimetype="text/event-stream")

    def event_stream():
        while True:
            current_status = progress_status.get(progress_id, "処理が開始されていません。")
            current_history = progress_history.get(progress_id, "進捗情報はありません。")
            data = json.dumps({"progress": current_status,
                              "history": current_history})
            yield f"data: {data}\n\n".encode(DEFAULT_ENCODING)
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
        tmp_file.write(blog_markdown.encode(DEFAULT_ENCODING))
        tmp_file_name = tmp_file.name
    return send_file(
        tmp_file_name,
        as_attachment=True,
        download_name="tech_blog.md",
        mimetype="text/markdown")

###############################################################################
# メインフロー: index.html で実装（POST送信で処理の種類を判別）
###############################################################################


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # 新規プロジェクト送信の場合のみセッション初期化
        if "project_folder" in request.files or request.form.get(
                "github_url", ""):
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
        # アウトライン更新（ユーザーによる修正・ただし再生成フラグがなければ）
        elif "edited_outline" in request.form and not request.form.get("regenerate_outline"):
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
                args=(
                    progress_id,
                    github_url,
                    target_audience,
                    blog_tone,
                    additional_requirements,
                    language,
                    temp_project_dir),
                daemon=True).start()

            flash("プロジェクト解析を開始しました。しばらくお待ちください。", "info")
            return render_template(
                "index.html",
                progress_id=progress_id,
                progress_log=progress_history.get(
                    progress_id,
                    ""))
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
            converted_html = markdown.markdown(
                blog_markdown, extensions=[
                    'fenced_code', 'codehilite'])

            if progress_status.get(progress_id, "").find("生成中") != -1:
                viewType = "status"
            elif blog_markdown:
                viewType = "final"
            elif blog_outline:
                viewType = "outline"
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
# 最終ブログ生成（POSTのみ）およびアウトライン再生成処理
###############################################################################


@app.route("/generate_final_blog", methods=["POST"])
def generate_final_blog():
    progress_id = session.get("progress_id", None)
    if not progress_id:
        return jsonify({"error": "progress_idがありません。"}), 400

    params = session.get("params", {})

    # アウトライン再生成フラグがある場合は、アウトライン再生成処理を呼び出す
    if request.form.get("regenerate_outline") == "true":
        update_progress(progress_id, "アウトライン再生成処理を開始します...\n")
        process_outline_regeneration(progress_id, params)
    else:
        # ユーザーによるアウトライン編集がある場合はその内容を反映
        if "edited_outline" in request.form:
            edited_outline = request.form.get("edited_outline", "")
            result_store[progress_id + "_outline"] = edited_outline

    # 最終ブログ生成処理を開始する
    session["final_blog_started"] = True
    update_progress(progress_id, "最終テックブログ生成中...\n")
    threading.Thread(
        target=process_final_blog,
        args=(progress_id, params),
        daemon=True
    ).start()
    return jsonify({"status": "最終テックブログ生成開始"}), 200

###############################################################################
# ブログ本文再生成（POSTのみ）
###############################################################################


@app.route("/regenerate_blog", methods=["POST"])
def regenerate_blog():
    progress_id = session.get("progress_id", None)
    if not progress_id:
        return jsonify({"error": "progress_idがありません。"}), 400
    params = session.get("params", {})

    # 編集された本文を更新
    edited_markdown = request.form.get("edited_markdown", "")
    result_store[progress_id] = edited_markdown

    session["final_blog_started"] = True
    update_progress(progress_id, "本文による再生成生成中...\n")
    threading.Thread(
        target=process_final_blog,
        args=(progress_id, params),
        daemon=True
    ).start()
    return jsonify({"status": "本文再生成開始"}), 200

###############################################################################
# プレビューMarkdown（POSTのみ）
###############################################################################


@app.route("/preview_markdown", methods=["POST"])
def preview_markdown():
    # 編集された本文を取得
    edited_markdown = request.form.get("edited_markdown", "")
    # MarkdownをHTMLに変換
    converted_html = strip_code_fences(edited_markdown)
    converted_html = markdown.markdown(
        edited_markdown, extensions=[
            'fenced_code', 'codehilite'])
    # JSONで返す
    return jsonify({"preview": converted_html})


###############################################################################
# Run the Flask App
###############################################################################
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        debug=False
    )
