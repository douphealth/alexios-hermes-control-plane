#!/usr/bin/env bash
set -euo pipefail
python -m compileall -q src tests
python - <<'PY'
import ast
from pathlib import Path
for path in list(Path('src').rglob('*.py')) + list(Path('tests').rglob('*.py')):
    ast.parse(path.read_text(), filename=str(path))
print('syntax: PASS')
PY
ruff check .
mypy src
pytest -q
docker compose config --quiet
printf 'validation: PASS\n'
