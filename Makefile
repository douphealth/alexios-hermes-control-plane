.PHONY: install lint typecheck test check up down
install:
	python -m pip install -e '.[dev]'
lint:
	ruff check .
typecheck:
	mypy src
test:
	pytest -q
check: lint typecheck test
up:
	docker compose up --build
down:
	docker compose down
