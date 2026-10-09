import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mcp_server


class MCPServerFeatureTests(unittest.TestCase):
    def setUp(self):
        mcp_server.conversation.clear()

    def tearDown(self):
        mcp_server.conversation.clear()

    def test_list_available_tools_contains_required_items(self):
        text = mcp_server.list_available_tools()

        self.assertIn("利用可能な機能:", text)
        self.assertIn("- 現在時刻取得", text)
        self.assertIn("- 四則演算", text)
        self.assertIn("- 会話履歴取得", text)
        self.assertIn("- 会話履歴クリア", text)
        self.assertIn("- ルート検索", text)

    def test_capability_question_returns_feature_list(self):
        with patch.object(mcp_server, "update_profile_from_text"), \
            patch.object(mcp_server, "handle_explicit_note_command", return_value=None), \
            patch.object(mcp_server, "is_local_only_request", return_value=False), \
            patch.object(mcp_server, "ask_local_llm") as mocked_local_llm, \
            patch.object(mcp_server, "ask_cloud_ai") as mocked_cloud_ai:
            result = mcp_server._generate_response_with_meta("有名なクラウドAIって何ができるの？")

        self.assertIn("利用可能な機能:", str(result["response"]))
        self.assertEqual(result["decision"], "ローカル処理")
        self.assertIn("evaluation", result)
        mocked_local_llm.assert_not_called()
        mocked_cloud_ai.assert_not_called()

    def test_evaluate_processing_speed_format(self):
        with patch.object(
            mcp_server,
            "_generate_response_with_meta",
            return_value={
                "response": "テスト応答",
                "decision": "ローカル処理",
                "reason": "内部関数で処理可能",
                "elapsed_ms": 18.4,
            },
        ):
            output = mcp_server.evaluate_processing_speed("今何時？")

        self.assertIn("入力内容: 今何時？", output)
        self.assertIn("判定: ローカル処理", output)
        self.assertIn("理由: 内部関数で処理可能", output)
        self.assertIn("処理時間: 18.4ms", output)

    def test_routing_log_written_for_cloud_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "cloud_routing_log.txt"
            csv_log_path = Path(tmpdir) / "cloud_routing_log.csv"
            with patch.object(mcp_server, "ROUTING_LOG_PATH", log_path), \
                patch.object(mcp_server, "ROUTING_LOG_CSV_PATH", csv_log_path), \
                patch.object(mcp_server, "update_profile_from_text"), \
                patch.object(mcp_server, "handle_explicit_note_command", return_value=None), \
                patch.object(mcp_server, "build_profile_context", return_value=""), \
                patch.object(mcp_server, "is_local_only_request", return_value=False), \
                patch.object(mcp_server, "build_local_prompt", return_value="prompt"), \
                patch.object(mcp_server, "ask_local_llm", return_value="（ローカルLLMエラー: timeout）"), \
                patch.object(mcp_server, "ask_cloud_ai", return_value="クラウド回答"):
                result = mcp_server._generate_response_with_meta("人生とは？")

            self.assertEqual(result["decision"], "クラウド処理候補")
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("入力内容: 人生とは？", log_text)
            self.assertIn("判定: クラウド処理候補", log_text)

            self.assertTrue(csv_log_path.exists())
            with csv_log_path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))

            self.assertGreaterEqual(len(rows), 2)
            self.assertEqual(rows[0], ["日時", "入力内容", "判定", "理由", "処理時間ms"])
            self.assertEqual(rows[1][1], "人生とは？")
            self.assertEqual(rows[1][2], "クラウド処理候補")


if __name__ == "__main__":
    unittest.main()
