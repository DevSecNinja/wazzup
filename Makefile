PYTHON ?= python3
PYTHONPATH := src
export PYTHONPATH

.PHONY: install format-check lint test build pipeline-generate validate-data ci

install:
	$(PYTHON) -m pip install -r requirements.txt

format-check:
	$(PYTHON) scripts/check_format.py

lint:
	$(PYTHON) scripts/lint.py

build:
	$(PYTHON) -m compileall -q src scripts

test:
	$(PYTHON) -m unittest discover -s tests

pipeline-generate:
	$(PYTHON) -m wazzup.pipeline

validate-data:
	$(PYTHON) -m wazzup.validate_data public/data

ci: format-check lint test build
