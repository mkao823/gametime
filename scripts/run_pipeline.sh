#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "=== download (2024 RS + playoffs; may take several minutes) ==="
gametime-download

echo "=== build snapshots ==="
gametime-build

echo "=== train ==="
gametime-train

echo "=== eval (playoff holdout) ==="
gametime-eval

echo "=== backtest signals ==="
gametime-backtest-signals

echo "Done. See reports/eval/ and reports/signals/"
