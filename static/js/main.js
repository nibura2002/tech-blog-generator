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

// ブログ編集（プレビュー更新）
function submitBlog() {
    const formData = new FormData(document.getElementById("blogForm"));
    fetch("/", {
      method: "POST",
      body: formData
    })
    .then(response => response.text())
    .then(() => {
       window.location.reload();
    })
    .catch(error => console.error("ブログ送信エラー:", error));
}

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