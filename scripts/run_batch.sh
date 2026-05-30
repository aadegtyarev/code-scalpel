#!/usr/bin/env bash
# Запускает N probe-прогонов notes_cli/notes_cli_empty и пишет результаты в файл.
# Использование: bash scripts/run_batch.sh [N=10] [outfile=batch_results.txt]

set -euo pipefail

N=${1:-10}
OUTFILE=${2:-batch_results.txt}
SCENARIO="notes_cli"
FIXTURE="notes_cli_empty"
PLAN_MSG="хочу собрать python-CLI для заметок: команды add, list, search, delete. json-storage, pytest. спроектируй и реализуй с тестами. если есть архитектурные вопросы — задай."
CLI="python scripts/probes_v2/cli.py"

source .venv/bin/activate

echo "# Batch: $N прогонов  $(date '+%Y-%m-%d %H:%M:%S')" | tee "$OUTFILE"
echo "# commit: $(git rev-parse --short HEAD)" | tee -a "$OUTFILE"
echo "" | tee -a "$OUTFILE"

scores=()

for i in $(seq 1 "$N"); do
    echo "=== Run $i/$N ===" | tee -a "$OUTFILE"

    RUN_ID=$($CLI start "$SCENARIO" "$FIXTURE" 2>/dev/null)
    echo "run_id: $RUN_ID" | tee -a "$OUTFILE"

    # plan step
    $CLI step "$RUN_ID" "$PLAN_MSG" --mode plan > /dev/null 2>&1 || true

    # go
    GO_OUT=$($CLI go "$RUN_ID" 2>&1 || true)
    echo "$GO_OUT" | tee -a "$OUTFILE"

    # finalize
    $CLI finalize "$RUN_ID" --reason=task_solved > /dev/null 2>&1 || \
    $CLI finalize "$RUN_ID" --reason=user_gave_up > /dev/null 2>&1 || true

    # extract score
    SCORE=$(python3 -c "
import json, glob
vf = 'docs/article/probe-runs/$RUN_ID/verdict.json'
try:
    d = json.load(open(vf))
    print(d['pass_score'], d['pass_max'])
except:
    print('? ?')
" 2>/dev/null || echo "? ?")
    echo "score: $SCORE" | tee -a "$OUTFILE"
    echo "" | tee -a "$OUTFILE"

    NUM=$(echo "$SCORE" | awk '{print $1}')
    if [[ "$NUM" =~ ^[0-9]+$ ]]; then
        scores+=("$NUM")
    fi
done

echo "=== Итог ===" | tee -a "$OUTFILE"
echo "Scores: ${scores[*]}" | tee -a "$OUTFILE"
python3 -c "
scores = [${scores[*]/#/} ]
scores.sort()
n = len(scores)
if n == 0:
    print('нет данных')
else:
    mid = n // 2
    median = scores[mid] if n % 2 else (scores[mid-1] + scores[mid]) / 2
    print(f'median={median}  mean={sum(scores)/n:.1f}  min={min(scores)}  max={max(scores)}  n={n}')
" 2>/dev/null | tee -a "$OUTFILE" || echo "scores: ${scores[*]}" | tee -a "$OUTFILE"
