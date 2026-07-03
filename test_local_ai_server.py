import unittest
import os
import tempfile
from unittest.mock import patch

import local_ai_server
import models.user_profile_memory as user_profile_memory


class LocalAIServerTests(unittest.TestCase):
    def setUp(self):
        local_ai_server._clear_all_sessions()

    def tearDown(self):
        local_ai_server._clear_all_sessions()

    def test_session_lifecycle(self):
        session_id = "session-a"
        local_ai_server._append_turn(session_id, "user", "こんにちは")
        local_ai_server._append_turn(session_id, "assistant", "こんにちは。")

        sessions = local_ai_server._list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], session_id)
        self.assertEqual(sessions[0]["turns"], 2)

        snapshot = local_ai_server._snapshot_session(session_id)
        self.assertEqual(len(snapshot), 2)
        self.assertEqual(snapshot[0]["role"], "user")

        self.assertTrue(local_ai_server._clear_session(session_id))
        self.assertEqual(local_ai_server._list_sessions(), [])

    def test_generate_llm_response_retries_once(self):
        calls = []

        def fake_ask(prompt, temperature=0.7, timeout=None):
            calls.append((prompt, temperature, timeout))
            if len(calls) == 1:
                return "（Ollama接続失敗: refused）"
            return "短く答えます。"

        with patch.object(local_ai_server, "ask_local_llm", side_effect=fake_ask):
            result = local_ai_server._generate_llm_response("テスト用プロンプト")

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempt"], 2)
        self.assertTrue(result["fallback_used"])
        self.assertEqual(len(calls), 2)

    def test_quality_check_rejects_gibberish(self):
        with patch.object(local_ai_server, "ask_local_llm", return_value="？？？？？？"):
            result = local_ai_server._generate_llm_response("テスト用プロンプト")

        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_health_snapshot_reports_ollama_and_sessions(self):
        with patch.object(
            local_ai_server,
            "_ollama_json_get",
            side_effect=[{"version": "0.1.0"}, {"models": [{"name": "llama3"}]}],
        ):
            health = local_ai_server._health_snapshot()

        self.assertEqual(health["status"], "ok")
        self.assertTrue(health["ollama"]["reachable"])
        self.assertTrue(health["ollama"]["model_available"])

    def test_server_meta_includes_open_urls(self):
        with patch.object(local_ai_server, "_resolve_local_ip", return_value="192.168.1.10"):
            meta = local_ai_server._server_meta()

        self.assertTrue(meta["ok"])
        self.assertEqual(meta["server"]["local_ip"], "192.168.1.10")
        self.assertIn("http://192.168.1.10:8000/", meta["server"]["open_urls"])

    def test_build_chat_payload_persists_assistant_turn(self):
        with patch.object(local_ai_server, "ask_local_llm", return_value="ちゃんと答えます。"):
            result = local_ai_server._build_chat_payload("こんにちは", "session-b")

        self.assertTrue(result["ok"])
        history = local_ai_server._snapshot_session("session-b")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["role"], "assistant")

    def test_document_crud_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(user_profile_memory, "_PROFILE_PATH", os.path.join(tmpdir, "user_profile.json")), \
                patch.object(user_profile_memory, "_NOTES_PATH", os.path.join(tmpdir, "user_notes.json")), \
                patch.object(user_profile_memory, "_KEEP_REQUESTS_PATH", os.path.join(tmpdir, "user_keep_requests.json")), \
                patch.object(user_profile_memory, "_TEXT_DOCS_DIR", os.path.join(tmpdir, "documents")), \
                patch.object(user_profile_memory, "_TEXT_DOCS_DB_PATH", os.path.join(tmpdir, "documents_db.txt")), \
                patch.object(user_profile_memory, "_DOC_SESSION_PATH", os.path.join(tmpdir, "document_session.json")), \
                patch.object(user_profile_memory, "_VIEW_PATH", os.path.join(tmpdir, "user_memory_view.json")):

                created = user_profile_memory.create_document_item("自己PR", "1行目\n2行目")
                self.assertTrue(created["ok"])
                self.assertEqual(created["document"]["title"], "自己PR")
                self.assertEqual(user_profile_memory.get_document_session()["current_title"], "自己PR")

                documents = user_profile_memory.list_document_items()
                self.assertEqual(len(documents), 1)
                doc_id = documents[0]["doc_id"]

                loaded = user_profile_memory.get_document_item(doc_id=doc_id)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded["content"], "1行目\n2行目")

                updated = user_profile_memory.update_document_item(doc_id, title="自己PR改", content="更新後本文")
                self.assertTrue(updated["ok"])

                refreshed = user_profile_memory.get_document_item(doc_id=doc_id)
                self.assertIsNotNone(refreshed)
                self.assertEqual(refreshed["title"], "自己PR改")
                self.assertEqual(refreshed["content"], "更新後本文")

                deleted = user_profile_memory.delete_document_item(doc_id)
                self.assertTrue(deleted["ok"])
                self.assertEqual(user_profile_memory.list_document_items(), [])
                self.assertIsNone(user_profile_memory.get_document_item(doc_id=doc_id))
                self.assertEqual(user_profile_memory.get_document_session()["current_doc_id"], "")


if __name__ == "__main__":
    unittest.main()
