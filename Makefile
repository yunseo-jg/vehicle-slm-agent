.PHONY: schema test lint server eval validate-eval dashboard

schema:
	uv run python ontology/build_schema.py

test:
	uv run pytest -q

lint:
	uv run ruff check . && uv run ruff format --check .

server:
	uv run python tools/server.py

eval:
	uv run python eval/run_eval.py --dataset eval/data/sample.jsonl

validate-eval:
	uv run python eval/validate_dataset.py eval/data/*.jsonl

dashboard:
	uv run --extra dashboard uvicorn dashboard.server:app --port 8000
