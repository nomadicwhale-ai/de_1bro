# Universal Data Types and 1-Billion-Row Data Engineering Benchmark
# `cp .env.example .env` first; every variable below can be overridden in .env or on the command line.
-include .env
export

PY        ?= python3
SIZE      ?= 1m                    # 1k 10k 1m 10m 100m 1b
DATASETS  ?= all                   # A,B,C,D,E | all
DATA_DIR  ?= ./data
WORKERS   ?= $(or $(GEN_WORKERS),4)

.PHONY: help setup test gen gen-dry stream estimate verify golden types conformance smoke bench report clean

help:
	@echo "make setup                 install Python dependencies"
	@echo "make test                  unit + golden tests (generator reference == vectorised)"
	@echo "make gen SIZE=10m          generate datasets (DATASETS=A,B,C | all) into $(DATA_DIR)"
	@echo "make gen-dry SIZE=1b       size estimate + disk guard only, writes nothing"
	@echo "make stream SIZE=1b        generate+digest on the fly, no files (streaming throughput)"
	@echo "make verify                re-check generated files against their manifests"
	@echo "make estimate              measure bytes/row, write docs/dataset-sizes.md"
	@echo "make golden                regenerate spec/golden.json with the pure-Python reference"
	@echo "make types                 rebuild docs/data-types from types.yaml"
	@echo "make conformance           build+run per-language conformance probes"
	@echo "make smoke                 runner smoke profile (1k+10k rows, all implementations)"
	@echo "make bench / report        full runs / reports (Phase 2+)"

setup:
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m pytest tests -q

gen:
	$(PY) -m generator gen --dataset $(DATASETS) --rows $(SIZE) --out $(DATA_DIR) --workers $(WORKERS)

gen-dry:
	$(PY) -m generator gen --dataset $(DATASETS) --rows $(SIZE) --out $(DATA_DIR) --dry-run

stream:
	$(PY) -m generator gen --dataset $(DATASETS) --rows $(SIZE) --sink null --workers $(WORKERS)

verify:
	$(PY) -m generator verify $(DATA_DIR)

estimate:
	$(PY) -m generator estimate --markdown docs/dataset-sizes.md

golden:
	$(PY) -m generator golden

types:
	$(PY) docs/data-types/build.py

conformance:
	bash conformance/run_all.sh

smoke:
	$(PY) -m runner run --smoke

bench:
	$(PY) -m runner run --rows $(SIZE)

report:
	@echo "Phase 4: report generation not implemented yet" && exit 1

clean:
	rm -rf $(DATA_DIR) results/raw results/tmp .pytest_cache
