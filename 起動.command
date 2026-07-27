#!/bin/zsh
# 株主総会 アクティビスト実戦リスト 起動（http://localhost:8701）
# ダブルクリックで起動。閉じるときはこのウィンドウで Ctrl+C。
#
# ポート 8701 の理由: 8501 は kabusoku が使用中（~/Desktop/株関係/kabusoku.app）。
# kabusoku.app は「:8501 が応答したらブラウザを開くだけ」の作りなので、
# ここが 8501 を掴んでいると kabusoku を開いたつもりで本アプリが出てしまう。
# 8501/8502 は streamlit の自動採番範囲でもあるため、離れた 8701 を使う。
# （既存の割り当て: 8000=maps, 8088=x-archive, 8099=ニュース収集,
#   8501=kabusoku, 8601=kensho, 8701=本アプリ）
cd "$(dirname "$0")"
echo "==================================="
echo "  株主総会 アクティビスト実戦リスト"
echo "==================================="
echo ""
echo "起動中… ブラウザが自動で開きます（Ctrl+C で停止）"
echo "  ローカル : http://localhost:8701"
echo "  公開ページ: https://shell0423.github.io/sokai-agenda/"
echo ""
exec .venv/bin/streamlit run app.py --server.port 8701
