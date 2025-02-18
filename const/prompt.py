# const/prompt.py

from langchain.prompts import PromptTemplate

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
    input_variables=[
        "directory_tree",
        "file_roles",
        "detailed_code_analysis",
        "project_files_content",
        "github_url",
        "target_audience",
        "blog_tone",
        "additional_requirements",
        "language"
    ],
    template="""
あなたは有能なソフトウェアエンジニア兼テックライターです。
以下のコンテキスト情報をもとに、テックブログの記事構成のアウトラインを、以下のJSONスキーマに厳密に従って出力してください。

【JSONスキーマ】
{{
  "chapters": [
    {{
      "id": "chapter_1",
      "title": "1章: 章のタイトル",
      "sections": [
        {{
          "id": "section_1",
          "title": "1-1: 節のタイトル",
          "items": [
            {{
              "id": "item_1",
              "title": "1-1-1: 項のタイトル",
              "summary": "項の内容の概要",
              "code_ref": "対応する詳細コード解説の識別子（コードブロックが存在しない場合は空文字列またはnull）"
            }},
            {{
              "id": "item_2",
              "title": "1-1-2: 項のタイトル",
              "summary": "別の項の概要",
              "code_ref": "対応する詳細コード解説の識別子（コードブロックが存在しない場合は空文字列またはnull）"
            }}
          ]
        }},
        {{
          "id": "section_2",
          "title": "1-2: 別の節のタイトル",
          "items": [
          ...
          ]
        }}
      ]
    }},
    {{
      "id": "chapter_2",
      "title": "2章: 別の章のタイトル",
      "sections": [
      ...
      ]
    }}
    ...
  ]
}}

【コンテキスト】
1) **ディレクトリ構造**:
{directory_tree}

2) **ファイルの役割概要**:
{file_roles}

3) **詳細なコード解説**:
{detailed_code_analysis}
※ 「詳細なコード解説」は、各機能ごとに一意の識別子を付与したJSON形式です。アウトライン作成時は、対応するコードブロックを参照する場合、必ずその識別子（例: section_1, section_2, …）を含めてください。

4) **全ファイル内容** (参考用):
{project_files_content}

【追加情報】
- GitHubリポジトリURL: {github_url}
- 想定読者: {target_audience}
- トーン: {blog_tone}
- その他リクエスト: {additional_requirements}
- 解説言語: {language}

【出力要件】
- ブログとして載せるべきすべての情報を網羅するアウトラインを作成してください。
- 最初の章に「はじめに」、最後の章に「おわりに」を含めること。
- chapters, sections, items の数に制限はありません。必要なだけ追加してください。
- 上記JSONスキーマに厳密に従い、余計なテキストや補足説明を一切含めず、JSON形式のみでアウトラインを出力してください。
- 各 "item" には、項目のタイトル、内容の概要を示す "summary"、および対応するコードブロックの識別子 "code_ref" を必ず含めてください。コードブロックが存在しない場合は、"code_ref" に空文字列またはnullを設定してください。
"""
)

final_blog_prompt_template = PromptTemplate(
    input_variables=[
        "directory_tree",
        "file_roles",
        "detailed_code_analysis",
        "project_files_content",
        "github_url",
        "target_audience",
        "blog_tone",
        "additional_requirements",
        "language",
        "blog_outline"],
    template="""
あなたは有能なソフトウェアエンジニア兼テックライターです。

以下の情報と、事前に確定したJSON形式のアウトラインを基に、最終的なテックブログ記事を{language}で作成してください。

【事前に確定したJSON形式のアウトライン】
{blog_outline}

【その他のコンテキスト】
1) **ディレクトリ構造**:
{directory_tree}

2) **ファイルの役割概要**:
{file_roles}

3) **詳細なコード解説**:
{detailed_code_analysis}

※ 注意: 上記「詳細なコード解説」は、各機能ごとに一意の識別子を付与した JSON 形式で出力されています。
各セクションの識別子（例: section_1, section_2, …）を参照して、対応するコードブロックを記事に追加してください。

4) **全ファイル内容**:
{project_files_content}

【追加情報】
- GitHubリポジトリURL: {github_url}
- 想定読者: {target_audience}
- トーン: {blog_tone}
- その他リクエスト: {additional_requirements}

【出力要件】
- 事前に確定したアウトラインの全項目を網羅して、読みやすいMarkdown形式の記事を作成してください。
- 記事は、**章**（大項目）、**節**（中項目）、**項**（小項目）に分けた構成で、各章には取り上げる話題と対応するコードブロック（対象ファイルのコードブロックそのもの）のリストが含まれていること。
- コードブロックは省略せず、完全な内容を示してください。
- テックブログの読者は処理の流れにへの興味が強いため、処理の流れと対応するコードブロックの説明のボリュームを多くしてください。
- ブログ記事以外の出力は禁止です。補足的な説明等も処理の邪魔になるため、記述しないでください。
- アウトプットが長い場合、分割して出力してください。
- 分割する場合、最後に<<<CONTINUE>>>というマーカーで終了する必要があります。
""")

# -------------------------------
# get_full_blog で使用する context_prompt の定義
# final_blog_prompt_template の内容を再利用してテンプレートの一部として組み込みます。
# -------------------------------
context_blog_prompt_template = PromptTemplate(
    input_variables=[
        "directory_tree", "file_roles", "detailed_code_analysis",
        "project_files_content", "github_url", "target_audience", "blog_tone",
        "additional_requirements", "language", "blog_outline", "full_blog"
    ],
    template=f"""
途中まで生成されたブログ記事と、そのブログ生成に使用したプロンプト情報を提供します。
ブログ記事とプロンプト情報を基に、続きを生成してください。

ブログ記事:
{{full_blog}}

プロンプト:
####################################################################################################
{final_blog_prompt_template.template}
####################################################################################################
"""
)

chapter_generation_prompt_template = PromptTemplate(
    input_variables=[
        "chapter_json",            # 1章分のアウトライン(JSON形式)
        "directory_tree",          # ディレクトリ構造 (必要なら)
        "file_roles",              # ファイル役割概要 (必要なら)
        "detailed_code_analysis",  # コード解説 (必要なら)
        "project_files_content",   # 全ファイル内容 (必要なら)
        "github_url",
        "target_audience",
        "blog_tone",
        "additional_requirements",
        "language",
        "previous_text"            # これまでの生成内容の要約や最後数行など
    ],
    template="""
あなたは有能なソフトウェアエンジニア兼テックライターです。

以下の「1章分のアウトライン」とコンテキスト情報を基に、該当章のブログ本文(Markdown形式)を{language}で作成してください。
すでに生成済みの内容（previous_text）との整合性も取りつつ、重複がないように留意してください。

【この章のアウトライン(JSON)】
{chapter_json}

【注意】
- 章タイトル、節、項の順に大項目・中項目・小項目として見出しを付け、見やすいMarkdownを生成すること。
- code_refが指定されている場合、そのIDに該当するコードブロック(詳細なコード解説)を引用してください。
- コードブロックは省略せず、完全な内容を示してください。出力が長くなる場合はMarkdownを分割出力し、末尾に<<<CONTINUE>>>を付けてください。
- ブログ記事以外の説明は不要です。

【すでに生成済みの内容】
{previous_text}

【参考情報】
- ディレクトリ構造: {directory_tree}
- ファイルの役割概要: {file_roles}
- 詳細なコード解説: {detailed_code_analysis}
- 全ファイル内容: {project_files_content}
- GitHubリポジトリURL: {github_url}
- 想定読者: {target_audience}
- トーン: {blog_tone}
- その他リクエスト: {additional_requirements}

【出力形式】
- 章の冒頭に章タイトル(# 見出し)を記載。
- 節は##、項は###などで見やすい構造を意識する。
- コードブロックはMarkdownのフェンスコードブロックを使う。
- 出力が長い場合、末尾に<<<CONTINUE>>>とだけ書いて終了し、後続の出力で続きから書くこと。
"""
)
