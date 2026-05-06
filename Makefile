.PHONY: install format-check lint test build pipeline-generate validate-data ci

install:
	task install

format-check:
	task format:check

lint:
	task lint

build:
	task build

test:
	task test

pipeline-generate:
	task pipeline:generate

validate-data:
	task validate:data

ci:
	task ci
