"""応答の評価指標を記録・集計するモデルで、性能確認と改善の判断材料を残します。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import csv
import json
import math
import os
import threading
from typing import Any


# Cost settings are intentionally env-driven so experiments can be reproduced.
# Values are in JPY per 1K tokens.
_INPUT_COST_PER_1K_TOKENS_YEN = float(os.getenv("EVAL_INPUT_COST_PER_1K_TOKENS_YEN", "0.05"))
_OUTPUT_COST_PER_1K_TOKENS_YEN = float(os.getenv("EVAL_OUTPUT_COST_PER_1K_TOKENS_YEN", "0.20"))
_BASELINE_MIN_COST_YEN = float(os.getenv("EVAL_BASELINE_MIN_COST_YEN", "0.018"))
_CHARS_PER_TOKEN = float(os.getenv("EVAL_CHARS_PER_TOKEN", "4.0"))


@dataclass
class EvaluationRecord:
    timestamp: str
    request_id: str
    experiment_mode: str
    test_case_id: str
    entry_point: str
    input_text: str
    route: str
    response_time_sec: float
    local_time_sec: float
    cloud_time_sec: float
    api_called: bool
    input_tokens: int
    output_tokens: int
    actual_cost_yen: float
    baseline_cost_yen: float
    saved_cost_yen: float
    success: bool
    user_rating: str = ""
    quality_passed: bool = False
    notes: str = ""


class EvaluationMetrics:
    def __init__(self, log_path: str = "data/evaluation_log.jsonl") -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def estimate_tokens(text: str) -> int:
        text = (text or "").strip()
        if not text:
            return 0
        return max(1, int(math.ceil(len(text) / _CHARS_PER_TOKEN)))

    @staticmethod
    def estimate_cloud_cost(input_tokens: int, output_tokens: int) -> float:
        input_cost = (max(0, input_tokens) / 1000.0) * _INPUT_COST_PER_1K_TOKENS_YEN
        output_cost = (max(0, output_tokens) / 1000.0) * _OUTPUT_COST_PER_1K_TOKENS_YEN
        return round(input_cost + output_cost, 6)

    def save(self, record: EvaluationRecord) -> None:
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def load_all(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []

        records: list[dict[str, Any]] = []
        with self._lock:
            with self.log_path.open("r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def _normalize_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for record in records:
            row = dict(record)
            row.setdefault("user_rating", "")
            row.setdefault("quality_passed", False)
            row.setdefault("notes", "")
            normalized.append(row)
        return normalized

    def _write_all(self, records: list[dict[str, Any]]) -> None:
        with self._lock:
            with self.log_path.open("w", encoding="utf-8") as file:
                for record in records:
                    file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def set_user_feedback(self, request_id: str, rating: str, notes: str = "") -> bool:
        request_id = (request_id or "").strip()
        if not request_id:
            return False

        rating = (rating or "").strip()
        quality_passed = rating in {"good", "partial"}

        records = self._normalize_records(self.load_all())
        updated = False
        for record in records:
            if str(record.get("request_id", "")).strip() != request_id:
                continue
            record["user_rating"] = rating
            record["quality_passed"] = quality_passed
            record["notes"] = (notes or "").strip()
            updated = True
            break

        if updated:
            self._write_all(records)
        return updated

    def export_csv(self, output_path: str = "data/evaluation_log.csv") -> str:
        records = self._normalize_records(self.load_all())
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "timestamp",
            "request_id",
            "experiment_mode",
            "test_case_id",
            "entry_point",
            "input_text",
            "route",
            "response_time_sec",
            "local_time_sec",
            "cloud_time_sec",
            "api_called",
            "input_tokens",
            "output_tokens",
            "actual_cost_yen",
            "baseline_cost_yen",
            "saved_cost_yen",
            "user_rating",
            "quality_passed",
            "success",
            "notes",
        ]

        with path.open("w", encoding="utf-8-sig", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow({key: record.get(key, "") for key in fieldnames})

        return str(path)

    def get_summary(self) -> dict[str, Any]:
        records = self._normalize_records(self.load_all())
        total = len(records)
        if total == 0:
            return {
                "total_requests": 0,
                "cloud_requests": 0,
                "avoided_requests": 0,
                "cloud_api_call_reduction_rate": 0.0,
                "api_reduction_rate": 0.0,
                "estimated_token_reduction_rate": 0.0,
                "average_response_time_sec": 0.0,
                "total_actual_cost_yen": 0.0,
                "total_baseline_cost_yen": 0.0,
                "total_saved_cost_yen": 0.0,
                "estimated_cost_reduction_rate": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "quality_passed_local_avoided_requests": 0,
                "quality_passed_api_reduction_rate": 0.0,
                "route_breakdown": {},
                "mode_breakdown": {},
            }

        cloud_requests = sum(1 for record in records if bool(record.get("api_called", False)))
        avoided_requests = total - cloud_requests

        total_response_time = sum(float(record.get("response_time_sec", 0.0)) for record in records)
        total_actual_cost = sum(float(record.get("actual_cost_yen", 0.0)) for record in records)
        total_baseline_cost = sum(float(record.get("baseline_cost_yen", 0.0)) for record in records)
        total_saved_cost = sum(float(record.get("saved_cost_yen", 0.0)) for record in records)
        total_input_tokens = sum(int(record.get("input_tokens", 0) or 0) for record in records)
        total_output_tokens = sum(int(record.get("output_tokens", 0) or 0) for record in records)
        total_baseline_tokens = sum(
            int(record.get("input_tokens", 0) or 0) + int(record.get("output_tokens", 0) or 0)
            for record in records
        )
        total_actual_tokens = sum(
            (int(record.get("input_tokens", 0) or 0) + int(record.get("output_tokens", 0) or 0))
            if bool(record.get("api_called", False))
            else 0
            for record in records
        )
        quality_passed_local_avoided_requests = sum(
            1
            for record in records
            if (not bool(record.get("api_called", False))) and bool(record.get("quality_passed", False))
        )

        route_groups: dict[str, dict[str, float]] = {}
        mode_groups: dict[str, dict[str, float]] = {}
        for record in records:
            route = str(record.get("route", "unknown"))
            group = route_groups.setdefault(route, {"count": 0, "total_response_time_sec": 0.0})
            group["count"] += 1
            group["total_response_time_sec"] += float(record.get("response_time_sec", 0.0))

            mode = str(record.get("experiment_mode", "DYNAMIC_ROUTING") or "DYNAMIC_ROUTING")
            mode_group = mode_groups.setdefault(mode, {"count": 0, "cloud_requests": 0, "total_response_time_sec": 0.0})
            mode_group["count"] += 1
            mode_group["total_response_time_sec"] += float(record.get("response_time_sec", 0.0))
            if bool(record.get("api_called", False)):
                mode_group["cloud_requests"] += 1

        route_breakdown: dict[str, dict[str, float]] = {}
        for route, group in route_groups.items():
            count = int(group["count"]) or 1
            route_breakdown[route] = {
                "count": int(group["count"]),
                "average_response_time_sec": round(group["total_response_time_sec"] / count, 3),
            }

        mode_breakdown: dict[str, dict[str, float]] = {}
        for mode, group in mode_groups.items():
            count = int(group["count"]) or 1
            cloud_requests_mode = int(group["cloud_requests"])
            mode_breakdown[mode] = {
                "count": int(group["count"]),
                "cloud_requests": cloud_requests_mode,
                "cloud_api_call_reduction_rate": round(((count - cloud_requests_mode) / count) * 100.0, 2),
                "average_response_time_sec": round(group["total_response_time_sec"] / count, 3),
            }

        api_reduction_rate = round((avoided_requests / total) * 100.0, 2)
        avg_response_time_sec = round(total_response_time / total, 3)
        cost_reduction_rate = 0.0
        if total_baseline_cost > 0:
            cost_reduction_rate = round((total_saved_cost / total_baseline_cost) * 100.0, 2)
        token_reduction_rate = 0.0
        if total_baseline_tokens > 0:
            token_reduction_rate = round(((total_baseline_tokens - total_actual_tokens) / total_baseline_tokens) * 100.0, 2)
        quality_passed_api_reduction_rate = round((quality_passed_local_avoided_requests / total) * 100.0, 2)

        return {
            "total_requests": total,
            "cloud_requests": cloud_requests,
            "avoided_requests": avoided_requests,
            "cloud_api_call_reduction_rate": api_reduction_rate,
            "api_reduction_rate": api_reduction_rate,
            "estimated_token_reduction_rate": token_reduction_rate,
            "average_response_time_sec": avg_response_time_sec,
            "total_actual_cost_yen": round(total_actual_cost, 6),
            "total_baseline_cost_yen": round(total_baseline_cost, 6),
            "total_saved_cost_yen": round(total_saved_cost, 6),
            "estimated_cost_reduction_rate": cost_reduction_rate,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "quality_passed_local_avoided_requests": quality_passed_local_avoided_requests,
            "quality_passed_api_reduction_rate": quality_passed_api_reduction_rate,
            "route_breakdown": route_breakdown,
            "mode_breakdown": mode_breakdown,
        }

    def build_record(
        self,
        *,
        request_id: str,
        experiment_mode: str = "DYNAMIC_ROUTING",
        test_case_id: str = "",
        entry_point: str,
        input_text: str,
        response_text: str,
        route: str,
        response_time_sec: float,
        local_time_sec: float,
        cloud_time_sec: float,
        api_called: bool,
        success: bool,
    ) -> EvaluationRecord:
        estimated_input_tokens = self.estimate_tokens(input_text)
        estimated_output_tokens = self.estimate_tokens(response_text)

        baseline_cost = max(
            self.estimate_cloud_cost(estimated_input_tokens, estimated_output_tokens),
            _BASELINE_MIN_COST_YEN,
        )

        actual_cost = 0.0
        if api_called:
            actual_cost = self.estimate_cloud_cost(estimated_input_tokens, estimated_output_tokens)

        saved_cost = max(baseline_cost - actual_cost, 0.0)

        return EvaluationRecord(
            timestamp=datetime.now().isoformat(),
            request_id=request_id,
            experiment_mode=(experiment_mode or "DYNAMIC_ROUTING").strip().upper(),
            test_case_id=(test_case_id or "").strip(),
            entry_point=entry_point,
            input_text=input_text,
            route=route,
            response_time_sec=round(response_time_sec, 3),
            local_time_sec=round(local_time_sec, 3),
            cloud_time_sec=round(cloud_time_sec, 3),
            api_called=api_called,
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
            actual_cost_yen=round(actual_cost, 6),
            baseline_cost_yen=round(baseline_cost, 6),
            saved_cost_yen=round(saved_cost, 6),
            success=success,
        )


evaluation_metrics = EvaluationMetrics()


def build_user_facing_evaluation(record: EvaluationRecord, summary: dict[str, Any]) -> dict[str, Any]:
    cloud_api_call = "あり" if record.api_called else "なし"
    return {
        "request_id": record.request_id,
        "experiment_mode": record.experiment_mode,
        "test_case_id": record.test_case_id,
        "route": record.route,
        "response_time_sec": record.response_time_sec,
        "local_time_sec": record.local_time_sec,
        "cloud_time_sec": record.cloud_time_sec,
        "api_called": record.api_called,
        "cloud_api_call": cloud_api_call,
        "estimated_api_reduction_count": 0 if record.api_called else 1,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "estimated_api_cost_yen": record.actual_cost_yen,
        "estimated_cloud_baseline_cost_yen": record.baseline_cost_yen,
        "saved_cost_yen": record.saved_cost_yen,
        "api_reduction_rate": float(summary.get("api_reduction_rate", 0.0)),
        "cloud_api_call_reduction_rate": float(summary.get("cloud_api_call_reduction_rate", 0.0)),
        "estimated_token_reduction_rate": float(summary.get("estimated_token_reduction_rate", 0.0)),
        "estimated_cost_reduction_rate": float(summary.get("estimated_cost_reduction_rate", 0.0)),
        "user_rating": record.user_rating,
        "quality_passed": record.quality_passed,
    }
