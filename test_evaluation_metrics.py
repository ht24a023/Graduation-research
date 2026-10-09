import tempfile
import unittest
from pathlib import Path

from models.evaluation_metrics import EvaluationMetrics


class EvaluationMetricsTests(unittest.TestCase):
    def test_feedback_updates_quality_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = str(Path(tmpdir) / "evaluation_log.jsonl")
            metrics = EvaluationMetrics(log_path=log_path)

            record_a = metrics.build_record(
                request_id="req-a",
                entry_point="test",
                input_text="こんにちは",
                response_text="こんにちは。",
                route="ローカル処理",
                response_time_sec=1.1,
                local_time_sec=1.0,
                cloud_time_sec=0.0,
                api_called=False,
                success=True,
            )
            record_b = metrics.build_record(
                request_id="req-b",
                entry_point="test",
                input_text="最新ニュース",
                response_text="クラウド応答",
                route="クラウドフォールバック",
                response_time_sec=2.2,
                local_time_sec=1.0,
                cloud_time_sec=1.2,
                api_called=True,
                success=True,
            )
            metrics.save(record_a)
            metrics.save(record_b)

            self.assertTrue(metrics.set_user_feedback("req-a", "good"))
            self.assertTrue(metrics.set_user_feedback("req-b", "bad"))

            summary = metrics.get_summary()
            self.assertEqual(summary["total_requests"], 2)
            self.assertEqual(summary["cloud_requests"], 1)
            self.assertEqual(summary["cloud_api_call_reduction_rate"], 50.0)
            self.assertEqual(summary["quality_passed_local_avoided_requests"], 1)
            self.assertEqual(summary["quality_passed_api_reduction_rate"], 50.0)

    def test_export_csv_outputs_expected_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = str(Path(tmpdir) / "evaluation_log.jsonl")
            csv_path = str(Path(tmpdir) / "evaluation_log.csv")
            metrics = EvaluationMetrics(log_path=log_path)

            record = metrics.build_record(
                request_id="req-c",
                entry_point="test",
                input_text="テスト入力",
                response_text="テスト応答",
                route="ローカルLLM",
                response_time_sec=1.5,
                local_time_sec=1.4,
                cloud_time_sec=0.0,
                api_called=False,
                success=True,
            )
            metrics.save(record)
            metrics.set_user_feedback("req-c", "partial", notes="一部修正")

            exported = metrics.export_csv(output_path=csv_path)
            content = Path(exported).read_text(encoding="utf-8-sig")
            self.assertIn("request_id", content)
            self.assertIn("user_rating", content)
            self.assertIn("quality_passed", content)
            self.assertIn("req-c", content)
            self.assertIn("partial", content)


if __name__ == "__main__":
    unittest.main()
