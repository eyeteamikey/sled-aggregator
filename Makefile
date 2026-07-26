.PHONY: install dev test lint check

install:
	python -m pip install -e ".[dev]"

dev:
	uvicorn sled_aggregator.main:app --reload

test:
	python -m unittest discover -s tests -v

lint:
	ruff check .

check: test lint

