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
# バックグラウンド処理の結果（最終記事）を格納するグローバル辞書
result_store = {}

###############################################################################
# Utility functions
###############################################################################

def read_project_files(root_dir):
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
    tree_lines = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        level = dirpath.replace(root_dir, '').count(os.sep)
        indent = ' ' * 4 * level
        tree_lines.append(f"{indent}{os.path.basename(dirpath)}/")
        for f in filenames:
            tree_lines.append(f"{indent}    {f}")
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
以下はプロジェクトのディレクトリ構造です。各ファイルの役割を、簡潔かつ具体的に要約してください。

ディレクトリ構造:
{directory_tree}

例:
- app.py: Flaskアプリの初期化とルーティングを行うバックエンドファイル
- index.html: ユーザー入力フォームやUIを構築するHTMLテンプレート
- README.md: プロジェクトの概要と設定方法を説明するドキュメント
"""
)

code_detail_prompt_template = PromptTemplate(
    input_variables=["file_content", "file_path"],
    template="""
以下はファイル「{file_path}」のコードです。  
このコードの主要な処理の流れ、設計意図、エラーハンドリングなどを詳細に解説してください。  
コードブロックは完全な内容を示し、必要に応じて重要な部分を引用して解説してください。

ファイルのコード:
{file_content}
"""
)

final_blog_prompt_template = PromptTemplate(
    input_variables=["directory_tree", "file_roles", "detailed_code_analysis", "target_audience", "blog_tone", "additional_requirements", "language", "github_url"],
    template="""
あなたは有能なソフトウェアエンジニア兼テックライターです。以下の情報をもとに、詳細で具体的なテックブログ記事を{language}で作成してください。

【ディレクトリ構造】
{directory_tree}

【各ファイルの役割の要約】
{file_roles}

【各ファイルの詳細なコード解説】
{detailed_code_analysis}

【その他】
- ブログのターゲット: {target_audience}
- トーン（文体）: {blog_tone}
- その他リクエスト: {additional_requirements}
- GithubリポジトリのURL: {github_url}

上記の情報をもとに、以下の構成で記事を出力してください。

1. **イントロダクション**  
   技術トレンド、背景、プロジェクトが解決しようとしている課題・ユースケース、及びGithubリポジトリの概要を紹介。

2. **機能詳細とチュートリアル**  
   各ファイルの役割と、コードの動作、設計意図、エラーハンドリングの詳細を解説。

3. **結論と今後の展望**  
   プロジェクトの意義と実装内容の総括、及び今後の展望についてハッピーなトーンで締めくくる。

記事はMarkdown形式で記述し、各コードブロックは完全な内容を示すこと。
"""
)

###############################################################################
# バックグラウンド処理関数
###############################################################################

def process_project(progress_id, github_url, target_audience, blog_tone, additional_requirements, language, temp_project_dir):
    try:
        progress_store[progress_id] = "Step 1: プロジェクトファイルの取得を開始します。\n"
        # アップロードされたファイルはすでに temp_project_dir に保存済み
        if os.listdir(temp_project_dir):
            progress_store[progress_id] += "フォルダアップロードによる取得完了。\n"
            logger.info("Project files obtained from uploaded folder.")
        else:
            # アップロードがなければ GitHub URL を利用してクローン
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
        llm = ChatOpenAI(model_name="gpt-4o", openai_api_key=openai_api_key)
        file_role_chain = LLMChain(llm=llm, prompt=file_role_prompt_template)
        file_roles = file_role_chain.run({"directory_tree": directory_tree})
        progress_store[progress_id] += "各ファイルの役割要約完了。\n"
        logger.info("File roles summary obtained.")

        progress_store[progress_id] += "Step 4: 各ファイルの詳細なコード解説を取得中...\n"
        detailed_code_analysis = ""
        all_files = []
        for dirpath, dirnames, filenames in os.walk(temp_project_dir):
            for file in filenames:
                if file.lower().endswith((".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp")):
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
                    "file_content": file_content
                })
                detailed_code_analysis += f"\n\n## {relative_file_path}\n" + file_detail
            except Exception as e:
                progress_store[progress_id] += f"ファイル解析失敗: {relative_file_path} - {e}\n"
                logger.warning("Failed to analyze file %s: %s", file_path, e)
        progress_store[progress_id] += "各ファイルの詳細なコード解説完了。\n"
        logger.info("Detailed code analysis obtained.")

        progress_store[progress_id] += "Step 5: 全情報を統合して最終記事生成中...\n"
        final_blog_chain = LLMChain(llm=llm, prompt=final_blog_prompt_template)
        generated_blog_raw = final_blog_chain.run({
            "directory_tree": directory_tree,
            "file_roles": file_roles,
            "detailed_code_analysis": detailed_code_analysis,
            "target_audience": target_audience,
            "blog_tone": blog_tone,
            "additional_requirements": additional_requirements,
            "language": language,
            "github_url": github_url
        })
        progress_store[progress_id] += "最終記事生成完了。\n"
        logger.info("Final tech blog generated.")

        # 結果はグローバルな result_store に保存
        result_store[progress_id] = generated_blog_raw
    except Exception as e:
        progress_store[progress_id] += f"処理中にエラー発生: {e}\n"
        logger.error("Error in processing: %s", e)

###############################################################################
# Flask Routes
###############################################################################

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        progress_id = str(uuid.uuid4())
        session["progress_id"] = progress_id
        progress_store[progress_id] = ""
        
        github_url = request.form.get("github_url", "").strip()
        uploaded_files = request.files.getlist("project_folder")
        
        if not ((uploaded_files and len(uploaded_files) > 0) or github_url):
            flash("GithubリポジトリのURLまたはプロジェクトのフォルダを選択してください。", "error")
            return redirect(url_for("index"))
        
        target_audience = request.form.get("target_audience", "エンジニア全般").strip()
        blog_tone = request.form.get("blog_tone", "カジュアルだけど専門性を感じるトーン").strip()
        additional_requirements = request.form.get("additional_requirements", "").strip()
        language = request.form.get("language", "ja")
        
        # 一時ディレクトリを作成し、アップロードされたファイルを保存（メインスレッドで実施）
        temp_project_dir = tempfile.mkdtemp()
        if uploaded_files and len(uploaded_files) > 0:
            for file in uploaded_files:
                filename = file.filename
                if not filename:
                    continue
                dest_path = os.path.join(temp_project_dir, filename)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                file.save(dest_path)
        # バックグラウンド処理開始（GitHubクローンは process_project 内で実施）
        threading.Thread(target=process_project, args=(
            progress_id, github_url, target_audience, blog_tone, additional_requirements, language, temp_project_dir
        ), daemon=True).start()

        return render_template("index.html", progress_id=progress_id)
    return render_template("index.html")

@app.route("/progress", methods=["GET"])
def progress():
    progress_id = session.get("progress_id", None)
    if progress_id and progress_id in progress_store:
        return jsonify({"progress": progress_store[progress_id]})
    return jsonify({"progress": "進捗情報がありません。"}), 404

@app.route("/preview_blog", methods=["GET", "POST"])
def preview_blog():
    if request.method == "POST":
        edited_markdown = request.form.get("edited_markdown", "")
        # ユーザーの編集結果は result_store を更新するか、別途保存してください。
        result_store[session.get("progress_id")] = edited_markdown
        return redirect(url_for("preview_blog"))

    progress_id = session.get("progress_id", None)
    blog_markdown = result_store.get(progress_id, "")
    converted_html = markdown.markdown(blog_markdown)
    progress_log = progress_store.get(progress_id, "進捗情報はありません。")
    return render_template("preview.html", blog_markdown=blog_markdown, converted_html=converted_html, progress_log=progress_log)

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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)