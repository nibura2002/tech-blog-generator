// 進捗情報のポーリング
let pollingInterval = null; // ポーリングのインターバルID

// ポーリング開始関数
function startPolling() {
    // すでにポーリングが実行中なら何もしない
    if (pollingInterval !== null) return;

    const progressElem = document.getElementById("progress");
    if (!progressElem) return;

    function fetchProgress() {
        fetch("/progress")
            .then(response => {
                if (!response.ok) {
                    throw new Error("進捗情報がまだ存在しません");
                }
                return response.json();
            })
            .then(data => {
                progressElem.innerText = data.progress;

                // 「ブログアウトラインの生成が完了しました」でポーリング停止＆遷移
                if (data.progress.includes("ブログアウトラインの生成が完了しました")) {
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    window.location.href = "/preview_outline";
                }
            })
            .catch(err => console.error("進捗情報の取得に失敗:", err));
    }

    pollingInterval = setInterval(fetchProgress, 3000);
}

// プロジェクト送信（ボタンを押したら submitProject() が実行される）
function submitProject(event) {
    event.preventDefault(); // フォームのデフォルト送信を防止
    const projectForm = document.getElementById("projectForm");
    const formData = new FormData(projectForm);
    
    fetch("/", {
        method: "POST",
        body: formData
    })
    .then(response => {
        if (response.ok) {
            // ボタン押下後にポーリングを開始する
            startPolling();
        }
    })
    .catch(error => console.error("プロジェクト送信エラー:", error));
}

// ページ読み込み時にフォームの送信イベントを登録する（ポーリングはここでは開始しない）
document.addEventListener("DOMContentLoaded", function () {
    const projectForm = document.getElementById("projectForm");
    if (projectForm) {
        projectForm.addEventListener("submit", submitProject);
    }
});

// アウトライン送信
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
  .then(response => {
      if (response.ok) {
          processingMessage.innerText = "最終ブログが完成しました。プレビュー画面に移動します…";
          window.location.href = "/preview_blog";
      }
  })
  .catch(error => {
      console.error("アウトライン送信エラー:", error);
      processingMessage.innerText = "エラーが発生しました。もう一度試してください。";
      generateButton.disabled = false;
  });
}

// ブログ送信
function submitBlog() {
  const formData = new FormData(document.getElementById("blogForm"));
  fetch("/preview_blog", {
      method: "POST",
      body: formData
  })
  .then(response => {
      if (response.ok) {
          location.reload();
      }
  })
  .catch(error => console.error("ブログ送信エラー:", error));
}

// 最終ブログ生成の進捗ポーリング（preview_blog 用）
function startFinalBlogPolling() {
    const processingMessage = document.getElementById("processingMessage");
    if (!processingMessage) return;
    
    const finalPollingInterval = setInterval(() => {
        fetch("/progress")
            .then(response => {
                if (!response.ok) {
                    throw new Error("進捗情報がまだ存在しません");
                }
                return response.json();
            })
            .then(data => {
                processingMessage.innerHTML = 
                    "<h1>ブログ生成中...</h1>" +
                    "<p>現在、最終テックブログの生成処理が進行中です。しばらくお待ちください。</p>" +
                    "<p>進捗情報: " + data.progress + "</p>";
                // 最終ブログ生成完了のメッセージを確認して自動リロード
                if (data.progress.includes("最終テックブログの生成が完了しました")) {
                    clearInterval(finalPollingInterval);
                    window.location.reload();
                }
            })
            .catch(err => console.error("進捗情報の取得に失敗:", err));
    }, 3000);
}

// preview_blog ページの場合、processingMessage 要素があればポーリング開始
document.addEventListener("DOMContentLoaded", function () {
    if (document.getElementById("processingMessage")) {
        startFinalBlogPolling();
    }
});