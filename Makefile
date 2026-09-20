.PHONY: validate check test

validate:
	python3 scripts/validate.py
	python3 scripts/versions.py --check
	go run scripts/verify_signatures.go

test:
	python3 -m unittest discover -s tests

check: validate test
