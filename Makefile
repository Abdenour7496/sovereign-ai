# Sovereign AI — Build & Supply Chain Targets
IMAGE ?= sovereign-brain:latest

.PHONY: build scan sbom sign supply-chain help

## Build the sovereign-brain Docker image
build:
	docker compose build sovereign-brain

## Scan image for HIGH/CRITICAL CVEs with Trivy
scan: build
	./scripts/supply-chain/scan.sh $(IMAGE)

## Generate SBOM (CycloneDX + SPDX) with syft
sbom: build
	./scripts/supply-chain/sbom.sh $(IMAGE)

## Sign the image with cosign (set COSIGN_KEY for keyed mode)
sign: build
	./scripts/supply-chain/sign.sh $(IMAGE)

## Full supply chain check: scan + sbom + sign
supply-chain: build
	./scripts/supply-chain/check-all.sh $(IMAGE) --fail-on-critical

## Show available targets
help:
	@grep -E '^## ' Makefile | sed 's/## /  /'
