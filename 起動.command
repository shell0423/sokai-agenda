#!/bin/zsh
# 株主総会 アクティビスト実戦リスト 起動（http://localhost:8501）
# ダブルクリックで起動。閉じるときはこのウィンドウで Ctrl+C。
cd "$(dirname "$0")"
echo "==================================="
echo "  株主総会 アクティビスト実戦リスト"
echo "==================================="
echo ""
echo "起動中… ブラウザが自動で開きます（Ctrl+C で停止）"
echo "公開ページ: https://shell0423.github.io/sokai-agenda/"
echo ""
exec .venv/bin/streamlit run app.py --server.port 8501
