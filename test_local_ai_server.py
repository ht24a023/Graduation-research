import unittest
import os
import tempfile
from unittest.mock import patch

import functions.google_workspace as google_workspace
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

    def test_build_chat_payload_returns_evaluation_metrics(self):
        with patch.object(local_ai_server, "ask_local_llm", return_value="了解です。"):
            result = local_ai_server._build_chat_payload("こんにちは", "session-eval")

        self.assertTrue(result["ok"])
        self.assertIn("evaluation", result)
        self.assertIn("request_id", result["evaluation"])
        self.assertIn("route", result["evaluation"])
        self.assertIn("response_time_sec", result["evaluation"])
        self.assertIn("api_called", result["evaluation"])
        self.assertIn("saved_cost_yen", result["evaluation"])
        self.assertIn("api_reduction_rate", result["evaluation"])

    def test_build_chat_payload_records_experiment_mode_and_test_case(self):
        with patch.object(local_ai_server, "ask_local_llm", return_value="了解です。"):
            result = local_ai_server._build_chat_payload(
                "こんにちは",
                "session-mode",
                experiment_mode="DYNAMIC_ROUTING",
                test_case_id="conversation_001",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result.get("experiment_mode"), "DYNAMIC_ROUTING")
        self.assertEqual(result.get("test_case_id"), "conversation_001")
        self.assertEqual(result["evaluation"].get("experiment_mode"), "DYNAMIC_ROUTING")
        self.assertEqual(result["evaluation"].get("test_case_id"), "conversation_001")

    def test_format_search_answer_handles_title_only_english_results(self):
        with patch.object(google_workspace, "translate_text", return_value="翻訳 (en -> ja):\nハローワールドの概要 / ハローワールド入門"):
            result = local_ai_server.search_google_web.__globals__["_format_search_answer"](
                "hello world",
                [
                    {"title": "Hello World Overview", "url": "https://example.com/hello-world", "snippet": ""},
                    {"title": "Introduction to Hello World", "url": "https://example.com/intro", "snippet": ""},
                ],
            )

        self.assertIn("要約", result)
        self.assertIn("https://example.com/hello-world", result)

    def test_fixed_routing_uses_cloud_for_general_query(self):
        with patch.object(local_ai_server, "ask_cloud_ai", return_value="クラウド回答") as mocked_cloud, \
            patch.object(local_ai_server, "ask_local_llm") as mocked_local:
            result = local_ai_server._build_chat_payload(
                "この研究テーマを要約して",
                "session-fixed",
                experiment_mode="FIXED_ROUTING",
                test_case_id="conversation_010",
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["evaluation"]["api_called"])
        self.assertEqual(result["evaluation"]["experiment_mode"], "FIXED_ROUTING")
        mocked_cloud.assert_called_once()
        mocked_local.assert_not_called()

    def test_dynamic_routing_asks_consent_before_cloud(self):
        with patch.object(local_ai_server, "classify_intent", return_value="chat"), \
            patch.object(local_ai_server, "ask_local_llm", return_value="（ローカルLLMエラー: timeout）"), \
            patch.object(local_ai_server, "search_google_web", return_value="検索結果サマリ"), \
            patch.object(local_ai_server, "ask_cloud_ai") as mocked_cloud:
            result = local_ai_server._build_chat_payload(
                "最新の生成AI動向を詳しく教えて",
                "session-consent",
                experiment_mode="DYNAMIC_ROUTING",
                test_case_id="conversation_020",
            )

        self.assertTrue(result["ok"])
        self.assertIn("ui", result)
        self.assertEqual(result["ui"]["type"], "cloud_api_consent")
        self.assertEqual(result["ui"]["interaction"], "send")
        self.assertEqual(len(result["ui"]["options"]), 2)
        mocked_cloud.assert_not_called()

    def test_dynamic_routing_cloud_runs_after_user_approval(self):
        with patch.object(local_ai_server, "classify_intent", return_value="chat"), \
            patch.object(local_ai_server, "ask_local_llm", return_value="（ローカルLLMエラー: timeout）"), \
            patch.object(local_ai_server, "search_google_web", return_value="検索結果サマリ"), \
            patch.object(local_ai_server, "ask_cloud_ai", return_value="クラウド詳細回答") as mocked_cloud:
            first = local_ai_server._build_chat_payload(
                "最新の生成AI動向を詳しく教えて",
                "session-consent-2",
                experiment_mode="DYNAMIC_ROUTING",
                test_case_id="conversation_021",
            )

            approve_message = first["ui"]["options"][0]["message"]
            second = local_ai_server._build_chat_payload(
                approve_message,
                "session-consent-2",
                experiment_mode="DYNAMIC_ROUTING",
                test_case_id="conversation_021",
            )

        self.assertTrue(second["ok"])
        self.assertEqual(second["response"], "クラウド詳細回答")
        self.assertTrue(second["evaluation"]["api_called"])
        mocked_cloud.assert_called_once()

    def test_capability_question_returns_local_templates_without_llm(self):
        with patch.object(local_ai_server, "ask_local_llm") as mocked_local_llm:
            result = local_ai_server._build_chat_payload("このローカルサーバーで何ができるの？", "session-cap")

        self.assertTrue(result["ok"])
        self.assertIn("このローカルサーバーで今すぐ使える処理", result["response"])
        self.assertIn("ui", result)
        self.assertEqual(result["ui"]["interaction"], "fill")
        self.assertGreaterEqual(len(result["ui"]["options"]), 5)
        mocked_local_llm.assert_not_called()

    def test_plain_route_query_uses_navigation_handler(self):
        with patch.object(local_ai_server, "resolve_navigation", return_value="Google Mapsリンク:\nhttps://example.com/route") as mocked_nav, \
            patch.object(local_ai_server, "ask_local_llm") as mocked_local_llm:
            result = local_ai_server._build_chat_payload("ここから東京駅まで", "session-route")

        self.assertTrue(result["ok"])
        self.assertIn("Google Mapsリンク", result["response"])
        mocked_nav.assert_called_once()
        called_args, called_kwargs = mocked_nav.call_args
        self.assertEqual(called_args[0], "ここから東京駅まで")
        self.assertIn("current_location_details", called_kwargs)
        mocked_local_llm.assert_not_called()

    def test_clarification_response_adds_recompute_input(self):
        with patch.object(local_ai_server, "classify_intent", return_value="cloud"), \
            patch.object(local_ai_server, "ask_local_llm", return_value="確認質問：希望する予算を入力してください（例：5万円）"):
            result = local_ai_server._build_chat_payload("おすすめのPCを選んで", "session-clarify")

        self.assertTrue(result["ok"])
        self.assertEqual(result["ui"]["type"], "prompt_input")
        self.assertEqual(result["ui"]["interaction"], "recompute")
        self.assertIn("おすすめのPCを選んで", result["ui"]["template"])
        recomputed = result["ui"]["template"].replace("{value}", "予算は5万円")
        self.assertIn("予算は5万円", recomputed)

    def test_structured_clarification_prompts_for_incomplete_comparison(self):
        with patch.object(
            local_ai_server,
            "ask_local_llm_json",
            return_value={
                "answerable": False,
                "needs_clarification": True,
                "question": "比較したい2つの対象を入力してください（例：PythonとJava）。",
            },
        ) as mocked_classifier, patch.object(local_ai_server, "ask_local_llm") as mocked_local:
            result = local_ai_server._build_chat_payload("この2つを比較して", "session-structured-clarify")

        self.assertTrue(result["ok"])
        self.assertIn("確認質問：", result["response"])
        self.assertEqual(result["ui"]["type"], "prompt_input")
        self.assertEqual(result["ui"]["interaction"], "recompute")
        self.assertIn("元の依頼：この2つを比較して", result["ui"]["template"])
        mocked_classifier.assert_not_called()
        mocked_local.assert_not_called()

    def test_clarification_followup_does_not_loop_back_to_prompt_input(self):
        followup = "元の依頼：この2つを比較して\n追加情報：PythonとJava\n上記の追加情報を使って元の依頼を再計算してください。"
        with patch.object(local_ai_server, "ask_local_llm_json") as mocked_classifier, \
            patch.object(local_ai_server, "ask_local_llm", return_value="Pythonは汎用性が高く、Javaは大規模開発で安定しています。"):
            result = local_ai_server._build_chat_payload(followup, "session-structured-followup")

        self.assertTrue(result["ok"])
        self.assertNotIn("ui", result)
        self.assertIn("Python", result["response"])
        mocked_classifier.assert_not_called()

    def test_missing_calculation_expression_uses_common_clarification_ui(self):
        with patch.object(local_ai_server, "ask_local_llm") as mocked_local:
            result = local_ai_server._build_chat_payload("これを計算して", "session-calc-clarify")

        self.assertTrue(result["ok"])
        self.assertIn("確認質問：", result["response"])
        self.assertEqual(result["ui"]["type"], "prompt_input")
        self.assertIn("元の依頼：これを計算して", result["ui"]["template"])
        mocked_local.assert_not_called()

    def test_missing_navigation_destination_uses_common_clarification_ui(self):
        with patch.object(local_ai_server, "ask_local_llm") as mocked_local:
            result = local_ai_server._build_chat_payload("指定した場所までの行き方を教えて", "session-route-clarify")

        self.assertTrue(result["ok"])
        self.assertIn("確認質問：", result["response"])
        self.assertEqual(result["ui"]["type"], "prompt_input")
        self.assertIn("元の依頼：指定した場所までの行き方を教えて", result["ui"]["template"])
        mocked_local.assert_not_called()

    def test_explicit_two_targets_with_vs_does_not_trigger_clarification(self):
        with patch.object(local_ai_server, "ask_local_llm", return_value="AとBの違いは性能と用途です。") as mocked_local:
            result = local_ai_server._build_chat_payload("Redis vs Memcached のメリット・デメリットを比較して", "session-vs-compare")

        self.assertTrue(result["ok"])
        self.assertNotIn("ui", result)
        mocked_local.assert_called_once()

    def test_ambiguous_comparison_still_triggers_clarification(self):
        result = local_ai_server._build_chat_payload("この2つを比較して", "session-ambiguous-compare")
        self.assertTrue(result["ok"])
        self.assertIn("ui", result)
        self.assertEqual(result["ui"]["type"], "prompt_input")

    def test_chinese_search_prompt_completes_local_search_when_results_exist(self):
        with patch.object(
            local_ai_server,
            "search_google_web",
            return_value="入力文の日本語訳：エッジAIとは何かを検索し、日本語で要約してください。\n日本語訳：エッジAIは端末側で推論を行う技術です。\n日本語による要約：エッジAIは端末側で推論を行う技術です。\n参照リンク：https://example.com/edge-ai",
        ):
            result = local_ai_server._build_chat_payload("什么是边缘人工智能？请搜索并用日语总结。", "session-zh-search")

        self.assertTrue(result["ok"])
        self.assertEqual(result["route"], "local_search")
        self.assertIn("入力文の日本語訳", result["response"])
        self.assertIn("参照リンク", result["response"])

    def test_korean_search_prompt_completes_local_search_when_results_exist(self):
        with patch.object(
            local_ai_server,
            "search_google_web",
            return_value="入力文の日本語訳：エッジAIとは何かを検索して、日本語で要約してください。\n日本語訳：エッジAIは端末側で推論を行う技術です。\n日本語による要約：エッジAIは端末側で推論を行う技術です。\n参照リンク：https://example.com/edge-ai",
        ):
            result = local_ai_server._build_chat_payload("엣지 AI란 무엇인가요? 검색해서 일본어로 요약해 주세요。", "session-ko-search")

        self.assertTrue(result["ok"])
        self.assertEqual(result["route"], "local_search")
        self.assertIn("入力文の日本語訳", result["response"])
        self.assertIn("https://example.com/edge-ai", result["response"])

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
