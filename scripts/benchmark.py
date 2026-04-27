import argparse
import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int((len(ordered) - 1) * q)
    return round(ordered[index], 2)


def post_json(url: str, payload: dict) -> tuple[dict, float, bool]:
    start = time.perf_counter()
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    cache_hit = False
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        cache_hit = bool(body.get("cache_hit", False))
    elapsed_ms = (time.perf_counter() - start) * 1000
    return body, elapsed_ms, cache_hit


def main() -> None:
    parser = argparse.ArgumentParser(description="agentic-context-rag baseline benchmark")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--session-id", default=f"bench-{int(time.time())}")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument(
        "--question",
        default="请总结知识库中和缓存命中率优化相关的核心建议。",
    )
    parser.add_argument(
        "--report",
        default="backend/data/benchmark-report.json",
    )
    args = parser.parse_args()

    chat_url = urllib.parse.urljoin(args.base_url.rstrip("/") + "/", "chat")
    total_ms_values: list[float] = []
    api_ms_values: list[float] = []
    cache_hits = 0
    failures: list[str] = []

    for i in range(args.rounds):
        try:
            payload = {"session_id": args.session_id, "question": args.question}
            response, api_ms, cache_hit = post_json(chat_url, payload)
            metrics = response.get("metrics", {})
            total_ms_values.append(float(metrics.get("total_ms", api_ms)))
            api_ms_values.append(api_ms)
            if cache_hit:
                cache_hits += 1
            print(
                f"round={i+1} cache_hit={cache_hit} "
                f"total_ms={metrics.get('total_ms', round(api_ms, 2))}"
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            failures.append(f"round {i+1}: {exc}")

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "base_url": args.base_url,
        "session_id": args.session_id,
        "rounds": args.rounds,
        "success": len(total_ms_values),
        "failures": failures,
        "cache_hit_rate": round(cache_hits / max(len(total_ms_values), 1), 4),
        "avg_total_ms": round(statistics.mean(total_ms_values), 2) if total_ms_values else 0.0,
        "p50_total_ms": percentile(total_ms_values, 0.5),
        "p95_total_ms": percentile(total_ms_values, 0.95),
        "avg_api_ms": round(statistics.mean(api_ms_values), 2) if api_ms_values else 0.0,
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nBenchmark Summary")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nreport saved to: {report_path}")


if __name__ == "__main__":
    main()
