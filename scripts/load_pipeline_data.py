#!/usr/bin/env python3
"""Load telemetry data into the Digital Twin API.

Supports JSON arrays, NDJSON and CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load telemetry data into Twin API")
    parser.add_argument("source", type=Path, help="Path to JSON/JSONL/CSV file")
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1/telemetry", help="Target telemetry endpoint")
    parser.add_argument("--bulk", action="store_true", help="Send in a single bulk request")
    return parser.parse_args()


def load_records(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix in {".json", ".jsn"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else [payload]
    if suffix in {".jsonl", ".ndjson"}:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if suffix == ".csv":
        rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
        return [
            {
                "halls": [
                    {
                        "id": row["hall_id"],
                        "racks": [
                            {
                                "id": row["rack_id"],
                                "cpuUtilization": float(row["cpu_utilization"]),
                                "inletTempC": float(row["inlet_temp_c"]),
                                "maxKw": float(row["max_kw"]),
                            }
                        ],
                    }
                ],
                "weather": {"ambientTempC": float(row["ambient_temp_c"])},
            }
            for row in rows
        ]
    raise ValueError(f"Unsupported file extension: {suffix}")


def main() -> None:
    args = parse_args()
    records = load_records(args.source)

    if args.bulk:
        target = args.api_url if args.api_url.endswith("/bulk") else f"{args.api_url}/bulk"
        response = requests.post(target, json=records, timeout=10)
        response.raise_for_status()
        print(f"Sent {len(records)} records to {target}: {response.json()}")
        return

    for record in records:
        response = requests.post(args.api_url, json=record, timeout=10)
        response.raise_for_status()
    print(f"Sent {len(records)} records to {args.api_url}")


if __name__ == "__main__":
    main()
