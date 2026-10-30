import inspect
import json
import datetime
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from functions import research_tools
from functions import weather as weather_module
from functions import google_workspace
from functions import location as location_module
from models.intent_classifier import classify_intent
import local_ai_server


class ResearchToolsTests(unittest.TestCase):
    def test_weather_wmo_code_mapping_is_complete(self):
        expected = {
            0: "快晴",
            1: "晴れ",
            2: "晴れ時々くもり",
            3: "くもり",
            45: "霧",
            48: "着氷性の霧",
            51: "弱い霧雨",
            53: "霧雨",
            55: "強い霧雨",
            56: "弱い着氷性の霧雨",
            57: "強い着氷性の霧雨",
            61: "弱い雨",
            63: "雨",
            65: "強い雨",
            66: "弱い着氷性の雨",
            67: "強い着氷性の雨",
            71: "弱い雪",
            73: "雪",
            75: "強い雪",
            77: "雪粒",
            80: "弱いにわか雨",
            81: "にわか雨",
            82: "激しいにわか雨",
            85: "弱いにわか雪",
            86: "激しいにわか雪",
            95: "雷雨",
            96: "弱いひょうを伴う雷雨",
            99: "強いひょうを伴う雷雨",
        }

        for code, label in expected.items():
            with self.subTest(code=code):
                self.assertEqual(weather_module._weather_code_to_text(code), label)

    def test_weather_unknown_code_has_diagnostic_text(self):
        self.assertEqual(
            weather_module._weather_code_to_text(123),
            "未対応の天気コード（コード: 123）",
        )

    def test_youtube_search_returns_clickable_url(self):
        result = research_tools.youtube_search("卒業研究 発表")
        self.assertIn("YouTube検索", result)
        self.assertIn("https://www.youtube.com/results?search_query=", result)

    def test_generate_qr_code_clamps_size(self):
        result = research_tools.generate_qr_code("https://example.com", size=5000)
        self.assertIn("quickchart.io/qr", result)
        self.assertIn("size=1000", result)

    def test_translate_text_parses_response(self):
        fake_json = '[[["Hello", "こんにちは", null, null]], null, "ja"]'
        with patch.object(research_tools, "_http_get_text", return_value=fake_json):
            result = research_tools.translate_text("こんにちは", target_lang="en", source_lang="ja")

        self.assertIn("翻訳 (ja -> en):", result)
        self.assertIn("Hello", result)

    def test_translate_text_structured_returns_ok_payload(self):
        fake_json = '[[["Hello", "こんにちは", null, null]], null, "ja"]'
        with patch.object(research_tools, "_http_get_text", return_value=fake_json):
            result = research_tools.translate_text_structured("こんにちは", target_lang="en", source_lang="ja")

        self.assertTrue(result["ok"])
        self.assertEqual(result["translated_text"], "Hello")
        self.assertEqual(result["source_language"], "ja")
        self.assertFalse(result["retryable"])

    def test_translate_text_structured_marks_http_429_retryable(self):
        error = research_tools.HTTPError("https://example.com", 429, "Too Many Requests", hdrs={"Retry-After": "2"}, fp=None)
        with patch.object(research_tools, "_http_get_text", side_effect=error):
            result = research_tools.translate_text_structured("hello", target_lang="ja", source_lang="en")

        self.assertFalse(result["ok"])
        self.assertTrue(result["retryable"])
        self.assertIn("429", result["error"])
        self.assertEqual(result.get("retry_after_seconds"), 2)

    def test_translate_text_structured_caches_same_input(self):
        fake_json = '[[["Hello", "こんにちは", null, null]], null, "ja"]'
        calls = []

        def fake_http_get_text(url):
            calls.append(url)
            return fake_json

        research_tools._TRANSLATION_CACHE.clear()
        with patch.object(research_tools, "_http_get_text", side_effect=fake_http_get_text):
            first = research_tools.translate_text_structured("こんにちは", target_lang="en", source_lang="ja")
            second = research_tools.translate_text_structured("こんにちは", target_lang="en", source_lang="ja")

        self.assertTrue(first["ok"])
        self.assertEqual(second["translated_text"], "Hello")
        self.assertEqual(len(calls), 1)

    def test_translate_text_returns_error_string_for_failures(self):
        with patch.object(research_tools, "_http_get_text", side_effect=research_tools.HTTPError("https://example.com", 429, "Too Many Requests", hdrs={}, fp=None)):
            result = research_tools.translate_text("hello", target_lang="ja", source_lang="en")

        self.assertIn("翻訳に失敗しました", result)

    def test_search_translation_failure_does_not_become_search_query(self):
        with patch.object(google_workspace, "ask_local_llm", return_value="（Ollamaタイムアウト: timed out）"), \
             patch.object(google_workspace, "translate_text", return_value="翻訳に失敗しました: HTTP Error 429: Too Many Requests"), \
             patch.object(google_workspace, "_search_google_web_impl", return_value="Google 検索結果:\n1. Edge AI overview\nhttps://example.com/edge-ai"), \
             patch.object(google_workspace, "_search_duckduckgo_lite", return_value="検索結果を抽出できませんでした。"), \
             patch.object(google_workspace, "_search_bing", return_value="検索結果を抽出できませんでした。"):
            result = google_workspace.search_google_web("What is edge AI? Please search the web and summarize the results.")

        self.assertNotIn("HTTP Error 429", result)
        self.assertNotIn("Too Many Requests", result)
        self.assertNotIn("https://example.com/edge-ai", result)
        self.assertIn("翻訳できませんでした", result)

    def test_wikipedia_summary_formats_extract_and_link(self):
        fake_payload = '{"extract":"要約本文","content_urls":{"desktop":{"page":"https://ja.wikipedia.org/wiki/テスト"}}}'
        with patch.object(research_tools, "_http_get_text", return_value=fake_payload):
            result = research_tools.wikipedia_summary("テスト")

        self.assertIn("Wikipedia要約: テスト", result)
        self.assertIn("要約本文", result)
        self.assertIn("https://ja.wikipedia.org/wiki/テスト", result)

    def test_summarize_web_url_uses_meta_description(self):
        html = """
        <html>
          <head>
            <title>Sample Page</title>
            <meta name=\"description\" content=\"This is summary text.\">
          </head>
          <body><p>Paragraph text.</p></body>
        </html>
        """
        with patch.object(research_tools, "_http_get_text", return_value=html):
            result = research_tools.summarize_web_url("https://example.com")

        self.assertIn("URL要約: Sample Page", result)
        self.assertIn("要点: This is summary text.", result)
        self.assertIn("リンク:\nhttps://example.com", result)

    def test_search_google_web_translates_english_summary_into_japanese(self):
        with patch.object(google_workspace, "_search_google_web_impl", return_value="Google 検索結果:\n1. Weather in Tokyo is sunny and warm today.\nhttps://example.com/weather"), \
             patch.object(google_workspace, "_search_duckduckgo_lite", return_value="検索結果を抽出できませんでした。"), \
             patch.object(google_workspace, "_search_bing", return_value="検索結果を抽出できませんでした。"), \
             patch.object(google_workspace, "translate_text", return_value="翻訳 (en -> ja):\n東京の天気は晴れで暖かいです。今日は快適な一日です。"):
            result = google_workspace.search_google_web("東京の天気")

        self.assertIn("日本語訳", result)
        self.assertIn("要約", result)
        self.assertIn("https://example.com/weather", result)
        self.assertNotIn("Weather in Tokyo is sunny and warm today.", result)
        self.assertLess(result.index("日本語訳"), result.index("要約"))
        self.assertIn("参考情報", result)

    def test_foreign_language_query_is_translated_before_search(self):
        translations = {
            "什么是边缘人工智能？请搜索并用日语总结。": "翻訳 (zh -> ja):\nエッジAIとは何かを検索し、日本語で要約してください。",
            "엣지 AI란 무엇인가요? 검색해서 일본어로 요약해 주세요.": "翻訳 (ko -> ja):\nエッジAIとは何かを検索して、日本語で要約してください。",
        }

        searched_queries = []

        def fake_search(query, max_results, language, country):
            searched_queries.append(query)
            return "Google 検索結果:\n1. Edge AI overview in Japanese.\nhttps://example.com/edge-ai"

        with patch.object(google_workspace, "_search_google_web_impl", side_effect=fake_search), \
             patch.object(google_workspace, "_search_duckduckgo_lite", return_value="検索結果を抽出できませんでした。"), \
             patch.object(google_workspace, "_search_bing", return_value="検索結果を抽出できませんでした。"), \
             patch.object(
                 google_workspace,
                 "translate_text",
                 side_effect=lambda text, target_lang="ja", source_lang="auto": translations.get(
                     text,
                     "翻訳 (en -> ja):\nEdge AIの概要を日本語で説明します。",
                 ),
             ):
            result_zh = google_workspace.search_google_web("什么是边缘人工智能？请搜索并用日语总结。")
            result_ko = google_workspace.search_google_web("엣지 AI란 무엇인가요? 검색해서 일본어로 요약해 주세요.")

        self.assertEqual(len(searched_queries), 2)
        self.assertIn("エッジAIとは何か", searched_queries[0])
        self.assertIn("エッジAIとは何か", searched_queries[1])
        self.assertIn("入力文の日本語訳", result_zh)
        self.assertIn("入力文の日本語訳", result_ko)
        self.assertIn("参考情報", result_zh)
        self.assertIn("https://example.com/edge-ai", result_ko)

    def test_search_output_sections_keep_required_order(self):
        with patch.object(google_workspace, "_search_google_web_impl", return_value="Google 検索結果:\n1. Edge AI helps inference near devices.\nhttps://example.com/edge-ai"), \
             patch.object(google_workspace, "_search_duckduckgo_lite", return_value="検索結果を抽出できませんでした。"), \
             patch.object(google_workspace, "_search_bing", return_value="検索結果を抽出できませんでした。"), \
               patch.object(google_workspace, "translate_text", return_value="翻訳 (en -> ja):\nEdge AIはデバイス近傍で推論を行う技術です。"):
            result = google_workspace.search_google_web("Edge AIについて英語の情報を検索して")

        head = [line for line in result.splitlines() if line.strip()][:5]
        self.assertTrue(head[0].startswith("日本語訳"), head)
        self.assertTrue(any(line.startswith("要約") for line in result.splitlines()), head)
        self.assertTrue(any(line.startswith("参考情報") for line in result.splitlines()), result)
        self.assertTrue(any(line.startswith("検索情報") for line in result.splitlines()) or any(line.startswith("参考情報") for line in result.splitlines()), result)

    def test_structured_search_records_keep_engine_query_rank_and_timestamp(self):
        records = [
            google_workspace._result_record(
                engine="Google",
                query="Edge AI",
                title="Edge AI overview",
                url="https://example.com/edge-ai",
                snippet="summary",
                language="en",
                rank=1,
                body_checked=False,
            )
        ]

        rendered = google_workspace._render_search_response(
            query="Edge AI",
            language="en",
            engine="Google",
            search_query="Edge AI",
            results=records,
        )

        self.assertIn("検索エンジン：Google", rendered)
        self.assertIn("検索語：Edge AI", rendered)
        self.assertIn("Edge AI overview", rendered)
        self.assertIn("https://example.com/edge-ai", rendered)
        self.assertIn("取得日時：", rendered)

    def test_search_result_dedup_and_urlless_filtering(self):
        cleaned = google_workspace._clean_search_results(
            [
                {"title": "A", "url": "https://example.com/a"},
                {"title": "A duplicate", "url": "https://example.com/a"},
                {"title": "No URL", "url": ""},
            ]
        )

        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["title"], "A")

    def test_language_detection_handles_mixed_english_and_japanese(self):
        self.assertEqual(google_workspace._detect_language("This is an English sentence with some 日本語 mixed in."), "en")
        self.assertEqual(google_workspace._detect_language("これは日本語の文章です。"), "ja")
        self.assertEqual(google_workspace._detect_language("这是中文内容，说明中文能被识别。"), "zh")
        self.assertEqual(google_workspace._detect_language("한국어 문장은 한글로 잘 인식됩니다."), "ko")
        self.assertEqual(google_workspace._detect_language("This is an English sentence."), "en")

    def test_weather_query_parser_detects_relative_day(self):
        result = weather_module.parse_weather_query("明日の大阪の天気は？")

        self.assertEqual(result["date_kind"], "tomorrow")
        self.assertEqual(result["location"], "大阪")
        self.assertEqual(result["query_text"], "大阪の天気")

    def test_weather_date_ranges_and_yesterday_are_rejected_explicitly(self):
        self.assertIn("取得範囲外", weather_module.get_weather("16日後の東京の天気"))
        self.assertIn("取得範囲外", weather_module.get_weather("17日後の東京の天気"))
        self.assertIn("予報APIでは取得できません", weather_module.get_weather("昨日の東京の天気"))

    def test_weather_missing_location_message_when_geocode_fails(self):
        with patch.object(weather_module, "_geocode_weather_location", return_value=None):
            self.assertIn("地域を特定できませんでした", weather_module.get_weather("存在しない地域の天気"))

    def test_get_location_details_returns_none_when_all_providers_fail(self):
        location_module._LOCATION_CACHE["details"] = None
        location_module._LOCATION_CACHE["expires_at"] = 0.0
        with patch.object(location_module, "_fetch_json", side_effect=Exception("network failure")):
            self.assertIsNone(location_module.get_location_details())

    def test_weather_returns_api_error_when_fetch_fails(self):
        with patch.object(weather_module, "_geocode_weather_location", return_value={"latitude": 35.6762, "longitude": 139.6503}), \
             patch.object(weather_module, "urlopen", side_effect=Exception("network error")):
            self.assertIn("取得できませんでした", weather_module.get_weather("今日の東京の天気"))

    def test_weather_questions_route_to_weather_instead_of_time(self):
        self.assertEqual(classify_intent("今日の天気は？"), "weather")
        self.assertEqual(classify_intent("今日の時刻は？"), "time")
        self.assertEqual(classify_intent("3日後の福岡の天気は？"), "weather")
        self.assertEqual(classify_intent("大阪の明日"), "weather")
        result = weather_module.parse_weather_query("3日後の福岡の天気は？")
        self.assertEqual(result["date_kind"], "days_after")
        self.assertEqual(result["location"], "福岡")

    def test_calculate_supports_natural_addition_phrase(self):
        self.assertEqual(local_ai_server.calculate("10と20を足して"), "答えは30です。")
        self.assertEqual(classify_intent("10と20を足して"), "calculate")

    def test_weather_prompt_ui_template_keeps_user_query_for_rerun(self):
        ui = local_ai_server._build_missing_info_ui(
            title="地域や日付を指定して再検索",
            placeholder="例: 大阪の明日 / 東京の3日後 / 札幌の天気",
            field="weather_query",
            question="{value}",
        )
        final_text = (ui["template"] or "{value}").replace("{value}", "大阪の明日")

        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        payload = {
            "current": {"temperature_2m": 28.4, "weather_code": 1},
            "daily": {
                "time": [today.isoformat(), tomorrow.isoformat()],
                "weather_code": [1, 1],
                "temperature_2m_max": [29.0, 31.0],
                "temperature_2m_min": [24.0, 25.0],
            },
        }

        with patch.object(weather_module, "_geocode_weather_location", return_value={"latitude": 34.6937, "longitude": 135.5023}), \
             patch.object(weather_module, "urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
            response = weather_module.get_weather(final_text)

        self.assertEqual(final_text, "大阪の明日")
        self.assertNotIn("取得できませんでした", response)
        self.assertNotIn("予報範囲外", response)
        self.assertIn("大阪の明日の天気", response)
        self.assertIn("31度", response)
        self.assertEqual(ui["field"], "weather_query")
        self.assertEqual(ui["button_label"], "再演算")

    def test_explicit_two_target_comparison_does_not_require_prompt_input(self):
        with patch.object(local_ai_server, "ask_local_llm", return_value="PythonとJavaは用途や実行方式が異なります。") as mocked_local:
            result = local_ai_server._build_chat_payload("PythonとJavaの主な違いを比較して", "session-compare-direct")

        self.assertTrue(result["ok"])
        self.assertNotIn("ui", result)
        self.assertEqual(result["route"], "local_llm")
        mocked_local.assert_called_once()

    def test_search_intent_and_route_for_english_search_prompt(self):
        query = "Edge AIについて英語の情報を検索して"
        self.assertEqual(classify_intent(query), "search")
        self.assertEqual(
            classify_intent("What is edge AI? Please search the web and summarize the results."),
            "search",
        )
        self.assertEqual(
            classify_intent("什么是边缘人工智能？请搜索并用日语总结。"),
            "search",
        )
        self.assertEqual(
            classify_intent("엣지 AI란 무엇인가요? 검색해서 일본어로 요약해 주세요."),
            "search",
        )

        with patch.object(google_workspace, "_search_google_web_impl", return_value="Google 検索結果:\n1. Edge AI is a lightweight AI pattern that runs on edge devices.\nhttps://example.com/edge-ai"), \
             patch.object(google_workspace, "_search_duckduckgo_lite", return_value="検索結果を抽出できませんでした。"), \
             patch.object(google_workspace, "_search_bing", return_value="検索結果を抽出できませんでした。"), \
             patch.object(google_workspace, "translate_text", return_value="翻訳 (en -> ja):\nエッジAIはエッジデバイスで動く軽量なAI手法です。\nこれはローカル処理の一種です。"):
            payload = local_ai_server._build_chat_payload(query, "session-search")

        self.assertTrue(payload["ok"])
        self.assertIn("日本語訳", payload["response"])
        self.assertIn("要約", payload["response"])
        self.assertIn("参考情報", payload["response"])
        self.assertIn("https://example.com/edge-ai", payload["response"])
        self.assertEqual(payload["route"], "local_search")
        self.assertEqual(payload["evaluation"]["route"], "ローカル処理")

    def test_today_weather_includes_current_temperature_humidity_and_precipitation_probability(self):
        today = datetime.date.today()
        payload = {
            "current": {
                "temperature_2m": 29.4,
                "relative_humidity_2m": 68,
                "wind_speed_10m": 4.4,
                "apparent_temperature": 31.1,
                "weather_code": 2,
            },
            "daily": {
                "time": [today.isoformat()],
                "weather_code": [2],
                "temperature_2m_max": [31.0],
                "temperature_2m_min": [25.0],
                "precipitation_probability_max": [70],
                "precipitation_sum": [8.2],
                "relative_humidity_2m_max": [68],
                "wind_speed_10m_max": [7.5],
                "sunrise": ["2026-08-25T05:12"],
                "sunset": ["2026-08-25T18:42"],
            },
        }
        with patch.object(weather_module, "_geocode_weather_location", return_value={"latitude": 34.6937, "longitude": 135.5023}), \
             patch.object(weather_module, "urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
            response = weather_module.get_weather("今日の大阪の天気")

        self.assertIn("現在気温", response)
        self.assertIn("現在湿度", response)
        self.assertIn("現在風速", response)
        self.assertIn("降水確率", response)
        self.assertIn("29度", response)
        self.assertIn("4.4m/s", response)
        self.assertIn("情報源：Open-Meteo", response)

    def test_tomorrow_weather_uses_tomorrow_values_not_todays_current_values(self):
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        payload = {
            "current": {
                "temperature_2m": 25.0,
                "relative_humidity_2m": 80,
                "apparent_temperature": 27.0,
                "weather_code": 1,
            },
            "daily": {
                "time": [today.isoformat(), tomorrow.isoformat()],
                "weather_code": [1, 3],
                "temperature_2m_max": [29.0, 31.0],
                "temperature_2m_min": [24.0, 25.0],
                "precipitation_probability_max": [20, 70],
                "precipitation_sum": [0.2, 8.2],
                "relative_humidity_2m_max": [65, 68],
                "wind_speed_10m_max": [4.0, 7.5],
                "sunrise": ["2026-08-25T05:12", "2026-08-26T05:13"],
                "sunset": ["2026-08-25T18:42", "2026-08-26T18:41"],
            },
        }
        with patch.object(weather_module, "_geocode_weather_location", return_value={"latitude": 34.6937, "longitude": 135.5023}), \
             patch.object(weather_module, "urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
            response = weather_module.get_weather("明日の大阪の天気")

        self.assertIn("明日の天気", response)
        self.assertIn("最高気温", response)
        self.assertIn("予想最大湿度", response)
        self.assertIn("予想最大風速", response)
        self.assertIn("70%", response)
        self.assertIn("7.5m/s", response)
        self.assertNotIn("80%", response)

    def test_weather_rounding_rules_are_fixed(self):
        self.assertEqual(weather_module._fmt_temperature(28.5), "28度")
        self.assertEqual(weather_module._fmt_percent(66.5), "66%")
        self.assertEqual(weather_module._fmt_precipitation(8.24), "8.2mm")
        self.assertEqual(weather_module._fmt_wind_speed(7.54), "7.5m/s")

    def test_weather_handles_missing_fields_without_failing(self):
        today = datetime.date.today()
        payload = {
            "current": {"temperature_2m": 28.2, "weather_code": 0},
            "daily": {
                "time": [today.isoformat()],
                "weather_code": [0],
                "temperature_2m_max": [30.0],
                "temperature_2m_min": [24.0],
            },
        }
        with patch.object(weather_module, "_geocode_weather_location", return_value={"latitude": 34.6937, "longitude": 135.5023}), \
             patch.object(weather_module, "urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
            response = weather_module.get_weather("今日の大阪の天気")

        self.assertIn("大阪の今日の天気", response)
        self.assertNotIn("不明", response)
        self.assertNotIn("None", response)

    def test_weather_response_contains_reference_metadata_footer(self):
        today = datetime.date.today()
        payload = {
            "current": {"temperature_2m": 28.2, "weather_code": 0},
            "daily": {
                "time": [today.isoformat()],
                "weather_code": [0],
                "temperature_2m_max": [30.0],
                "temperature_2m_min": [24.0],
                "precipitation_probability_max": [25],
                "precipitation_sum": [1.2],
                "relative_humidity_2m_max": [60],
                "wind_speed_10m_max": [3.5],
                "sunrise": ["2026-08-25T05:12"],
                "sunset": ["2026-08-25T18:42"],
            },
        }
        with patch.object(weather_module, "_geocode_weather_location", return_value={"latitude": 34.6937, "longitude": 135.5023}), \
             patch.object(weather_module, "urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
            response = weather_module.get_weather("今日の大阪の天気")
            requested_url = mock_urlopen.call_args[0][0].full_url

        self.assertIn("temperature_unit=celsius", requested_url)
        self.assertIn("precipitation_unit=mm", requested_url)
        self.assertIn("wind_speed_unit=ms", requested_url)
        self.assertIn("情報源：Open-Meteo", response)
        self.assertIn("対象地点：大阪", response)
        self.assertIn("予報対象日：", response)
        self.assertIn("取得日時：", response)
        self.assertIn("https://api.open-meteo.com/v1/forecast", response)

    def test_weather_api_failure_does_not_show_fictional_numbers(self):
        with patch.object(weather_module, "_geocode_weather_location", return_value={"latitude": 34.6937, "longitude": 135.5023}), \
             patch.object(weather_module, "urlopen", side_effect=Exception("network error")):
            response = weather_module.get_weather("今日の大阪の天気")

        self.assertIn("取得できませんでした", response)
        self.assertNotIn("℃", response)
        self.assertNotIn("%", response)
        self.assertNotIn("m/s", response)

    def test_weather_prompt_input_ui_sends_recomputed_message(self):
        source = inspect.getsource(local_ai_server)
        self.assertIn("const finalText = (ui.template || '{value}').replace('{value}', value);", source)
        self.assertIn("messageInput.value = finalText;", source)
        self.assertIn("sendMessage();", source)

    def test_search_result_uses_actual_reference_url_when_available(self):
        result = google_workspace._translate_raw_search_result(
            "Google 検索結果:\n1. The weather in Tokyo is sunny and warm today.\nhttps://example.com/weather"
        )
        self.assertIn("https://example.com/weather", result)


if __name__ == "__main__":
    unittest.main()
