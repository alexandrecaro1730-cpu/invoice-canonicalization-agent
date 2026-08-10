# Business objective: provide memorable one-command workflows for reviewers, operators, and interview assessors.
# Technical description: installs exact dependency locks and delegates quality, demo, API/MCP, fixture, and human-review operations to versioned Python entry points.
.PHONY: install assess assess-full lint typecheck test demo interview-demo delivery-evidence api mcp fixtures review-demo review-export review-list review-process clean

install:
	python -m pip install -r requirements-dev.lock
	python -m pip install -e . --no-deps

assess:
	PYTHONPATH=src python scripts/quality_gate.py

assess-full:
	PYTHONPATH=src REQUIRE_DOCKER=1 REQUIRE_STATIC_TOOLS=1 python scripts/quality_gate.py

lint:
	python -m ruff check src tests scripts

typecheck:
	python -m mypy src/invoice_canonicalizer

test:
	PYTHONPATH=src python -m pytest -q

demo:
	PYTHONPATH=src python -m invoice_canonicalizer document "data/examples/input/challenge_invoice.pdf" --tenant testinger --partner default-partner

interview-demo:
	PYTHONPATH=src python scripts/interview_demo.py

delivery-evidence:
	PYTHONPATH=src python scripts/generate_delivery_evidence.py

api:
	PYTHONPATH=src python -m invoice_canonicalizer serve

mcp:
	PYTHONPATH=src python -m invoice_canonicalizer mcp

fixtures:
	python scripts/generate_fixtures.py

review-demo:
	rm -f .runtime/catalog.db .runtime/review_queue.csv .runtime/review_archive.jsonl
	PYTHONPATH=src python -m invoice_canonicalizer line "Black Leather Jacket Midnight" --source-line-id demo-novel
	PYTHONPATH=src python -m invoice_canonicalizer line "BLACK LEATHER JACKET MIDNIGHT!!!" --source-line-id demo-repeat
	PYTHONPATH=src python -m invoice_canonicalizer line "Black crew athletic sock" --source-line-id demo-llm-existing
	PYTHONPATH=src python -m invoice_canonicalizer line "Athletic crew sock" --source-line-id demo-auto
	PYTHONPATH=src python -m invoice_canonicalizer review-export --tenant testinger --path .runtime/review_queue.csv
	@echo "Edit .runtime/review_queue.csv, then run: make review-process"

review-export:
	PYTHONPATH=src python -m invoice_canonicalizer review-export --tenant testinger --path .runtime/review_queue.csv

review-list:
	PYTHONPATH=src python -m invoice_canonicalizer review-list --tenant testinger

review-process:
	PYTHONPATH=src python -m invoice_canonicalizer review-process --path .runtime/review_queue.csv --archive .runtime/review_archive.jsonl

clean:
	rm -rf .runtime .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov reports/*.json reports/*.html reports/*.md reports/*.xml reports/wheels build dist *.egg-info src/*.egg-info
