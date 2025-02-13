// main.js

// 進捗情報のポーリング
document.addEventListener("DOMContentLoaded", function() {
  const progressElem = document.getElementById("progress");
  let pollingInterval = null;

  if (progressElem) {
      function fetchProgress() {
          fetch("/progress")
              .then(response => response.json())
              .then(data => {
                  progressElem.innerText = data.progress;

                  // アウトライン作成が完了したらポーリングを停止して遷移
                  if (data.progress.includes("ブログアウトラインの生成が完了しました")) {
                      clearInterval(pollingInterval); // ポーリング停止
                      pollingInterval = null; // 明示的にnullに設定
                      window.location.href = "/preview_outline";
                  }
              })
              .catch(err => console.error("進捗情報の取得に失敗:", err));
      }

      pollingInterval = setInterval(fetchProgress, 3000); // ポーリング開始
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