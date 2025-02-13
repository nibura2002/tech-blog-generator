document.addEventListener("DOMContentLoaded", function() {
    // 進捗表示エリアが存在する場合のみ
    const progressElem = document.getElementById("progress");
    if (progressElem) {
      // 進捗情報を取得する関数
      function fetchProgress() {
        fetch("/progress")
          .then(response => response.json())
          .then(data => {
            progressElem.innerText = data.progress;
            // 例: アウトライン生成完了のタイミングで自動遷移
            if (data.progress.includes("一旦基本情報の抽出が完了しました")) {
              window.location.href = "/generate_outline";
            }
          })
          .catch(err => console.error("進捗情報の取得に失敗:", err));
      }
      // 3秒ごとに進捗を取得
      setInterval(fetchProgress, 3000);
    }
  });