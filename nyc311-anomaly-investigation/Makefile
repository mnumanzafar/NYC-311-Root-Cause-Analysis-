.PHONY: setup etl external sql test lint report export nightly nightly-dry install-cron metrics audit clean

setup:
	python -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt

etl:
	python -m src.etl.extract && python -m src.etl.load_to_db && python -m src.etl.extract_external && python -m src.etl.load_external && python -m src.etl.run_sql_pipeline

external:
	python -m src.etl.extract_external && python -m src.etl.load_external && python -m src.etl.run_sql_pipeline

sql:
	python -m src.etl.run_sql_pipeline

test:
	pytest -q

report:
	jupyter nbconvert --execute --to notebook --inplace notebooks/*.ipynb

export:
	python -m src.reporting.cohort_export --out reports/exports --format all

# Nightly: refresh SQL layers, export the latest complete week, e-mail the files.
nightly:
	python -m src.orchestration.nightly_export --out reports/exports/nightly --format all

# Same job without touching the database or sending mail — safe to run anytime.
nightly-dry:
	python -m src.orchestration.nightly_export --skip-refresh --email-dry-run --slack-dry-run

# Export an arbitrary range, e.g. make range POST_START=2024-06-01 POST_END=2024-06-30
range:
	python -m src.reporting.cohort_export --out reports/exports --format all \
	  --post-start $(POST_START) --post-end $(POST_END) \
	  $(if $(BASELINE_START),--baseline-start $(BASELINE_START) --baseline-end $(BASELINE_END),) \
	  $(if $(FILTERS),--filters-json $(FILTERS),powerbi/filter_state.json)

# Pipeline health: last run, record counts, mart freshness, latest artifacts.
status:
	python -m src.reporting.status --html reports/status.html

install-cron:
	bash deploy/install_cron.sh

clean:
	rm -rf data/interim/* data/processed/* .pytest_cache

metrics:
	python -m src.observability.metrics --out reports/metrics/nyc311.prom

audit:
	python -m src.reporting.audit --list
