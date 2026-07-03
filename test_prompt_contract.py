import unittest

from cloud.local_prompt import PROMPT_CONTRACT_VERSION, build_local_prompt


class PromptContractTests(unittest.TestCase):
    def test_build_local_prompt_includes_contract_metadata(self):
        prompt = build_local_prompt(
            "こんにちは",
            conversation_history=[
                {"role": "user", "content": "前の質問"},
                {"role": "assistant", "content": "前の返答"},
            ],
            current_location="東京",
            mode="chat",
        )

        self.assertIn(f"プロンプト契約: {PROMPT_CONTRACT_VERSION}", prompt)
        self.assertIn("モード: chat", prompt)
        self.assertIn("会話履歴:", prompt)
        self.assertIn("ユーザー: 前の質問", prompt)
        self.assertIn("アシスタント: 前の返答", prompt)
        self.assertIn("現在地情報: 東京", prompt)
        self.assertIn("ユーザー入力: こんにちは", prompt)
        self.assertIn("返答方針: 結論を先に、短く自然な日本語で答える", prompt)

    def test_build_local_prompt_drops_empty_and_invalid_turns(self):
        prompt = build_local_prompt(
            "テスト",
            conversation_history=[
                None,
                {"role": "unknown", "content": "  "},
                {"role": "assistant", "content": "返答"},
            ],
        )

        self.assertIn("アシスタント: 返答", prompt)
        self.assertNotIn("unknown", prompt)


if __name__ == "__main__":
    unittest.main()