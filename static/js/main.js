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
    .then(html => {
       document.open();
       document.write(html);
       document.close();
       startProgressSSE();
    })
    .catch(error => console.error("プロジェクト送信エラー:", error));
}

// アウトライン送信（最終ブログ生成のトリガー）
function submitOutline() {
    const generateButton = document.getElementById("generateButton");
    const processingMessage = document.getElementById("processingMessage");

    generateButton.disabled = true;
    processingMessage.style.display = "block";

    const formData = new FormData(document.getElementById("outlineForm"));
    fetch("/generate_final_blog", {
      method: "POST",
      body: formData
    })
    .then(response => response.json())
    .then(data => {
       processingMessage.innerText = "最終ブログ生成中…しばらくお待ちください。";
    })
    .catch(error => {
      console.error("アウトライン送信エラー:", error);
      processingMessage.innerText = "エラーが発生しました。もう一度試してください。";
      generateButton.disabled = false;
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
    .then(html => {
       document.open();
       document.write(html);
       document.close();
    })
    .catch(error => console.error("ブログ送信エラー:", error));
}

// SSE を利用して進捗情報を取得
function startProgressSSE() {
    const progressElem = document.getElementById("progress");
    if (!progressElem) return;

    const evtSource = new EventSource("/progress_stream");
    evtSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.progress && data.progress !== "処理が開始されていません。") {
            progressElem.innerText = data.progress;
        }
        // アウトライン生成完了時のリロード（まだリロードしていなければ）
        if (data.progress.includes("ブログアウトラインの生成が完了しました") &&
            !sessionStorage.getItem("outlineReloadTriggered")) {
            sessionStorage.setItem("outlineReloadTriggered", "true");
            evtSource.close();
            window.location.reload();
        }
        // 最終ブログ生成完了時のリロード（まだリロードしていなければ）
        if (data.progress.includes("最終テックブログの生成が完了しました") &&
            !sessionStorage.getItem("finalReloadTriggered")) {
            sessionStorage.setItem("finalReloadTriggered", "true");
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
    if (document.getElementById("progress")) {
      startProgressSSE();
    }
});