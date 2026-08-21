.PHONY: validate check

validate:
	python3 scripts/validate.py
	go run scripts/verify_signatures.go

check: validate
