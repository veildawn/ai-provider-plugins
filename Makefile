.PHONY: validate

validate:
	python3 scripts/validate.py
	go run scripts/verify_signatures.go
