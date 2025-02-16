// プロジェクト送信（フォーム送信時）
function submitProject(event) {
    event.preventDefault();
    const projectForm = document.getElementById("projectForm");
    const formData = new FormData(projectForm);

    fetch("/", {
      method: "POST",
      body: formData
    })
    .then(response => response.text())
    .then(() => {
       window.location.reload();
    })
    .catch(error => console.error("プロジェクト送信エラー:", error));
}

// アウトライン送信（最終ブログ生成のトリガー）
function submitOutline() {
    const generateButton = document.getElementById("generateButton");
    const processingMessage = document.getElementById("processingMessage");

    if (generateButton) {
        generateButton.disabled = true;
    }
    if (processingMessage) {
        processingMessage.style.display = "block";
        processingMessage.innerText = "最終ブログ生成中…しばらくお待ちください。";
    }

    const formData = new FormData(document.getElementById("outlineForm"));
    fetch("/generate_final_blog", {
      method: "POST",
      body: formData
    })
    .then(response => response.json())
    .then(() => {
       // リロードすると index で進捗状況がチェックされ、生成中ならステータス画面へ
       window.location.reload();
    })
    .catch(error => {
      console.error("アウトライン送信エラー:", error);
      if (processingMessage) {
          processingMessage.innerText = "エラーが発生しました。もう一度試してください。";
      }
      if (generateButton) {
          generateButton.disabled = false;
      }
    });
}

// 本文再生成用の関数
function submitBlogGeneration() {
    const formData = new FormData(document.getElementById("blogForm"));
    fetch("/regenerate_blog", {
      method: "POST",
      body: formData
    })
    .then(response => response.json())
    .then(() => {
       // リロードして、生成中ならステータス画面を表示
       window.location.reload();
    })
    .catch(error => console.error("本文再生成エラー:", error));
}
// （既存のsubmitProjectやSSE関連の関数はそのまま）

// SSE を利用して進捗情報を取得（ブログ生成ステータス画面用）
function startProgressSSE() {
    const evtSource = new EventSource("/progress_stream");
    evtSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        const progressText = data.progress.trim();
        const progressElem = document.getElementById("progress");
        const historyElem = document.getElementById("progress_history");
        if (progressElem && progressText && progressText !== "処理が開始されていません。") {
            progressElem.innerText = progressText;
        }
        if (historyElem && data.history) {
            historyElem.innerText = data.history;
        }
        // 完了メッセージが含まれている場合にリロード
        if (progressText.indexOf("最終テックブログの生成が完了しました") !== -1 ||
            progressText.indexOf("ブログアウトラインの生成が完了しました") !== -1) {
            evtSource.close();
            window.location.reload();
        }
    };
    evtSource.onerror = function(err) {
        console.error("SSE エラー:", err);
    };
}

document.addEventListener("DOMContentLoaded", function () {
    const projectForm = document.getElementById("projectForm");
    if (projectForm) {
        projectForm.addEventListener("submit", submitProject);
    }
    // SSE を起動する条件を "status" または "initial" に変更
    if (typeof viewType !== "undefined" && (viewType === "status" || viewType === "initial")) {
        startProgressSSE();
    }
});

// Preview更新用関数
function updatePreview() {
    const blogForm = document.getElementById("blogForm");
    const formData = new FormData(blogForm);
    fetch("/preview_markdown", {
      method: "POST",
      body: formData
    })
    .then(response => response.json())
    .then(data => {
       // preview-container の内容を更新
       const previewContainer = document.getElementById("preview-container");
       previewContainer.innerHTML = data.preview;
    })
    .catch(error => console.error("Preview更新エラー:", error));
}