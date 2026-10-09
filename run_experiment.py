"""実験モードや評価用の処理をまとめて実行するスクリプトで、挙動検証と記録を行います。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

MODES = ["LOCAL_ONLY", "FIXED_ROUTING", "DYNAMIC_ROUTING"]


def post_json(url: str, payload: dict, timeout: float = 120.0) -> dict:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def get_json(url: str, timeout: float = 60.0) -> dict:
    req = Request(url, headers={"User-Agent": "experiment-runner"}, method="GET")
    with urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def run_experiment(base_url: str, question_set_path: Path, session_prefix: str) -> dict:
    with question_set_path.open("r", encoding="utf-8") as f:
        questions = json.load(f)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("data") / "experiment_runs" / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "experiment_result.jsonl"

    total = 0
    success = 0

    with result_path.open("w", encoding="utf-8") as out:
        for mode in MODES:
            session_id = f"{session_prefix}-{mode.lower()}"
            for item in questions:
                payload = {
                    "message": item["message"],
                    "session_id": session_id,
                    "experiment_mode": mode,
                    "test_case_id": item["test_case_id"],
                }
                response = post_json(f"{base_url.rstrip('/')}/chat", payload)
                row = {
                    "mode": mode,
                    "test_case_id": item["test_case_id"],
                    "category": item.get("category", ""),
                    "message": item["message"],
                    "ok": bool(response.get("ok", False)),
                    "response": response.get("response", response.get("error", "")),
                    "evaluation": response.get("evaluation", {}),
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                total += 1
                if row["ok"]:
                    success += 1
                print(f"[{mode}] {item['test_case_id']} ok={row['ok']}")

    summary = get_json(f"{base_url.rstrip('/')}/evaluation/summary")
    csv_req = Request(f"{base_url.rstrip('/')}/evaluation/export.csv", method="GET")
    csv_path = out_dir / "evaluation_log.csv"
    with urlopen(csv_req, timeout=60.0) as res:
        csv_path.write_bytes(res.read())

    final = {
        "total_requests": total,
        "success_requests": success,
        "result_jsonl": str(result_path),
        "evaluation_csv": str(csv_path),
        "summary": summary.get("summary", summary),
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="Run routing mode comparison experiments against local_ai_server.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Local AI server URL")
    parser.add_argument(
        "--question-set",
        default="data/experiment_question_set.json",
        help="Path to experiment question set JSON",
    )
    parser.add_argument("--session-prefix", default="exp", help="Session ID prefix")
    args = parser.parse_args()

    result = run_experiment(
        base_url=args.base_url,
        question_set_path=Path(args.question_set),
        session_prefix=args.session_prefix,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
