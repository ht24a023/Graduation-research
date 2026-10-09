import unittest
from unittest.mock import patch

import local_ai_server
from functions import google_workspace
from models.intent_classifier import classify_intent


class ForeignSearchRoutingTests(unittest.TestCase):
    def test_english_query_is_classified_as_search(self):
        self.assertEqual(classify_intent("Search for the differences between Edge AI and Cloud AI."), "search")

    def test_chinese_query_is_classified_as_search(self):
        self.assertEqual(classify_intent("边缘人工智能和云人工智能有什么区别？"), "search")

    def test_korean_query_is_classified_as_search(self):
        self.assertEqual(classify_intent("엣지 AI의 장점과 단점을 검색해 주세요."), "search")

    def test_foreign_query_translates_then_searches_in_japanese(self):
        with patch.object(google_workspace, "_translate_with_fallback", return_value={"ok": True, "translated_text": "データをクラウドへ送信せず、AIをローカルで実行する利点は何ですか？"}), \
            patch.object(google_workspace, "_search_google_web_impl", return_value={
                "engine": "Google",
                "query": "ローカルAI 利点 クラウドAI 比較",
                "results": [{"title": "Local AI vs Cloud AI", "url": "https://example.com/ai", "snippet": "比較記事"}],
                "trial_route": "Google",
                "body_checked": True,
            }):
            result = google_workspace.search_google_web_structured("What are the benefits of running AI locally instead of sending data to the cloud?")

        self.assertTrue(result["ok"])
        self.assertEqual(result["route"], "foreign_input_translate_search")
        self.assertEqual(result["detected_language"], "en")
        self.assertEqual(result["original_query"], "What are the benefits of running AI locally instead of sending data to the cloud?")
        self.assertEqual(result["translated_query"], "データをクラウドへ送信せず、AIをローカルで実行する利点は何ですか？")
        self.assertEqual(result["actual_search_query"], "ローカルAI 利点 クラウドAI 比較")
        self.assertEqual(result["results"][0]["url"], "https://example.com/ai")
        self.assertIsNotNone(result["summary_ja"])

    def test_translation_failure_stops_before_search(self):
        with patch.object(google_workspace, "_translate_with_fallback", return_value={"ok": False, "translated_text": "", "error": "fail"}), \
            patch.object(google_workspace, "_search_google_web_impl") as mocked_search:
            result = google_workspace.search_google_web_structured("Search for the differences between Edge AI and Cloud AI.")

        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "translation_failed")
        self.assertEqual(result["error_type"], "translation_failed")
        mocked_search.assert_not_called()

    def test_search_failure_returns_search_failed_route(self):
        with patch.object(google_workspace, "_translate_with_fallback", return_value={"ok": True, "translated_text": "エッジAIとクラウドAIの違いを検索してください。"}), \
            patch.object(google_workspace, "_search_google_web_impl", return_value="検索結果を取得できませんでした。"):
            result = google_workspace.search_google_web_structured("Search for the differences between Edge AI and Cloud AI.")

        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "search_failed")
        self.assertEqual(result["error_type"], "search_fetch_failed")
        self.assertEqual(result["results"], [])

    def test_success_and_failure_ui_types_are_separate(self):
        success_ui = local_ai_server._build_search_success_ui()
        failure_ui = local_ai_server._build_search_failure_ui()

        self.assertEqual(success_ui["type"], "search_result_confirmation")
        self.assertEqual(failure_ui["type"], "search_failure_actions")
        self.assertNotEqual(success_ui["type"], failure_ui["type"])


if __name__ == "__main__":
    unittest.main()
