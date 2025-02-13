// main.js

// タブ切り替え
function showTab(tabId) {
  document.querySelectorAll(".tab-content").forEach(tab => {
      tab.classList.remove("active");
  });
  document.getElementById(tabId).classList.add("active");
}

// 進捗情報のポーリング
document.addEventListener("DOMContentLoaded", function() {
  const progressElem = document.getElementById("progress");
  if (progressElem) {
      function fetchProgress() {
          fetch("/progress")
              .then(response => response.json())
              .then(data => {
                  progressElem.innerText = data.progress;
                  // 「ブログアウトラインの生成が完了しました。」が含まれている場合、アウトライン確認画面へ遷移
                  if (data.progress.includes("ブログアウトラインの生成が完了しました")) {
                      window.location.href = "/preview_outline";
                  }
              })
              .catch(err => console.error("進捗情報の取得に失敗:", err));
      }
      setInterval(fetchProgress, 3000);
  }
});

// アウトライン送信
function submitOutline() {
  const generateButton = document.getElementById("generateButton");
  const processingMessage = document.getElementById("processingMessage");

  // ボタン無効化＆処理中メッセージ表示
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
      generateButton.disabled = false; // エラー時にボタンを再有効化
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