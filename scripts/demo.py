"""调用真实 HTTP 接口；重复运行不会重复导入相同示例。"""

import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    sample = Path(__file__).resolve().parents[1] / "examples" / "sources.json"
    with httpx.Client(base_url=args.url, timeout=90, trust_env=False) as client:
        response = client.post("/api/v1/sources/import", json=json.loads(sample.read_text("utf-8")))
        response.raise_for_status()
        source_id = response.json()[0]["id"]
        response = client.post(
            "/api/v1/companion/run",
            json={
                "source_id": source_id,
                "tasks": ["reading", "cards", "facts", "author"],
                "question": "如何进行主动回忆？",
                "claims": ["主动回忆是尝试在不看原文的情况下回想所学内容。"],
            },
        )
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
