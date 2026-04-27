import argparse
import json
from pathlib import Path


def load_report(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_delta(new: float, old: float) -> float:
    if old == 0:
        return 0.0
    return round((new - old) / old, 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two benchmark reports.")
    parser.add_argument("--baseline", required=True, help="path to baseline report JSON")
    parser.add_argument("--candidate", required=True, help="path to candidate report JSON")
    parser.add_argument("--output", default="backend/data/benchmark-compare.json")
    args = parser.parse_args()

    base = load_report(args.baseline)
    cand = load_report(args.candidate)

    summary = {
        "baseline": args.baseline,
        "candidate": args.candidate,
        "metrics": {
            "cache_hit_rate": {
                "baseline": base.get("cache_hit_rate", 0.0),
                "candidate": cand.get("cache_hit_rate", 0.0),
                "delta": round(cand.get("cache_hit_rate", 0.0) - base.get("cache_hit_rate", 0.0), 4),
            },
            "avg_total_ms": {
                "baseline": base.get("avg_total_ms", 0.0),
                "candidate": cand.get("avg_total_ms", 0.0),
                "delta_ratio": safe_delta(cand.get("avg_total_ms", 0.0), base.get("avg_total_ms", 0.0)),
            },
            "p95_total_ms": {
                "baseline": base.get("p95_total_ms", 0.0),
                "candidate": cand.get("p95_total_ms", 0.0),
                "delta_ratio": safe_delta(cand.get("p95_total_ms", 0.0), base.get("p95_total_ms", 0.0)),
            },
            "avg_api_ms": {
                "baseline": base.get("avg_api_ms", 0.0),
                "candidate": cand.get("avg_api_ms", 0.0),
                "delta_ratio": safe_delta(cand.get("avg_api_ms", 0.0), base.get("avg_api_ms", 0.0)),
            },
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\ncomparison saved to: {out}")


if __name__ == "__main__":
    main()
