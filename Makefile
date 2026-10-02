PY ?= python

.PHONY: test analysis sim frame db rebuild

test:        ## unit tests (no network)
	$(PY) -m pytest

db:          ## create data/grocery.sqlite and load config/items.csv
	$(PY) db/init_db.py --load-items

frame:       ## sampling frame + seeded store sample (no network after fetch_external)
	$(PY) -m sampling.fetch_external
	$(PY) -m sampling.build_frame

rebuild:     ## rebuild the database from data/raw (no network)
	$(PY) -m collectors.reparse

sim:         ## estimator validation on simulated data
	$(PY) simulation/validate_tail_estimators.py

analysis:    ## all analysis modules
	$(PY) run_all.py
