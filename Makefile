.DEFAULT_GOAL := help
UV ?= uv tool run --from uv==0.12.21 uv
PLAZIA_TOOLS = $(UV) run --locked plazia-tools
TEST_SUITE ?= fast
TEST_FLAGS ?=
TEST_OPTION = $(if $(strip $(TEST_FLAGS)),-- $(TEST_FLAGS))
CHECK_TOOL ?= fast
CHECK_FLAGS ?=

PLAZIA_MAKE_HELP_VERSION := 1
PLAZIA_PUBLIC_TARGETS := help bootstrap format lint typecheck frontend browser-install build image check test integration acceptance coverage preflight hardening-checks normalizers docs-check actions-check openapi openapi-check migrate schema-check
PLAZIA_PRIVATE_TARGETS := flyway-migrate
PLAZIA_HELP_ROOT := $(CURDIR)/help

PLAZIA_HELP_SELECTOR_check := CHECK_TOOL
PLAZIA_HELP_VALUES_check := fast all normalizers actions links openapi vulture semantic-dry wrap crap make-help
PLAZIA_HELP_DEFAULT_check := fast
PLAZIA_HELP_SELECTOR_test := TEST_SUITE
PLAZIA_HELP_VALUES_test := fast unit architecture integration acceptance all
PLAZIA_HELP_DEFAULT_test := fast
PLAZIA_HELP_SELECTOR_coverage := TEST_SUITE
PLAZIA_HELP_VALUES_coverage := fast
PLAZIA_HELP_DEFAULT_coverage := fast

PLAZIA_HELP_EFFECT_help := read-only
PLAZIA_HELP_EFFECT_bootstrap := workspace
PLAZIA_HELP_EFFECT_format := workspace
PLAZIA_HELP_EFFECT_lint := read-only
PLAZIA_HELP_EFFECT_typecheck := read-only
PLAZIA_HELP_EFFECT_frontend := workspace
PLAZIA_HELP_EFFECT_browser-install := workspace
PLAZIA_HELP_EFFECT_build := workspace
PLAZIA_HELP_EFFECT_image := runtime
PLAZIA_HELP_EFFECT_check := runtime
PLAZIA_HELP_EFFECT_test := runtime
PLAZIA_HELP_EFFECT_integration := runtime
PLAZIA_HELP_EFFECT_acceptance := runtime
PLAZIA_HELP_EFFECT_coverage := runtime
PLAZIA_HELP_EFFECT_preflight := runtime
PLAZIA_HELP_EFFECT_hardening-checks := runtime
PLAZIA_HELP_EFFECT_normalizers := read-only
PLAZIA_HELP_EFFECT_docs-check := read-only
PLAZIA_HELP_EFFECT_actions-check := read-only
PLAZIA_HELP_EFFECT_openapi := workspace
PLAZIA_HELP_EFFECT_openapi-check := runtime
PLAZIA_HELP_EFFECT_migrate := external
PLAZIA_HELP_EFFECT_flyway-migrate := external
PLAZIA_HELP_EFFECT_schema-check := read-only

.PHONY: $(PLAZIA_PUBLIC_TARGETS) $(PLAZIA_PRIVATE_TARGETS)

include .make/help.mk

ifeq ($(PLAZIA_MAKE_HELP_ACTIVE),)
check:
	@$(PLAZIA_TOOLS) check "$(CHECK_TOOL)" $(CHECK_FLAGS)
bootstrap:
	$(UV) sync --locked
lint:
	@$(PLAZIA_TOOLS) quality lint
typecheck:
	@$(PLAZIA_TOOLS) quality typecheck
format:
	@$(PLAZIA_TOOLS) quality format
test:
	@$(PLAZIA_TOOLS) test "$(TEST_SUITE)" $(TEST_OPTION)
integration:
	@$(PLAZIA_TOOLS) test integration $(TEST_OPTION)
coverage:
	@$(PLAZIA_TOOLS) coverage "$(TEST_SUITE)"
build:
	$(UV) build
normalizers:
	@$(PLAZIA_TOOLS) check normalizers $(CHECK_FLAGS)
preflight:
	@$(PLAZIA_TOOLS) preflight
hardening-checks:
	@$(MAKE) coverage TEST_SUITE=fast
	@$(MAKE) check CHECK_TOOL=all

CONTAINER ?= podman
FLYWAY_IMAGE := docker.io/flyway/flyway:13.4.0@sha256:e19dbd5c73a1487d825ffe02f9e11e0ce3f37b80bbc012ece1cba15af4f9f9ce
FLYWAY_NETWORK_ARGS ?=
FLYWAY = $(CONTAINER) run --rm $(FLYWAY_NETWORK_ARGS) -v $(CURDIR)/app/platform/persistence/sql:/flyway/project:ro -w /flyway/project -e FLYWAY_URL -e FLYWAY_USER -e FLYWAY_PASSWORD $(FLYWAY_IMAGE) -configFiles=/flyway/project/flyway.toml
migrate:
	$(UV) run --locked python -m app.cli schema-prepare
	@$(MAKE) flyway-migrate
	$(UV) run --locked python -m app.cli schema-finish
flyway-migrate:
	$(FLYWAY) migrate
	$(FLYWAY) validate
schema-check:
	$(UV) run --locked python -m app.cli schema-check
acceptance:
	@CONTAINER=$(CONTAINER) $(PLAZIA_TOOLS) test acceptance

image:
	CONTAINER=$(CONTAINER) $(UV) run --locked python tools/image.py
openapi:
	$(UV) run --locked python -c 'import json; from pathlib import Path; from app.main import app; Path(".plazia/local").mkdir(parents=True, exist_ok=True); Path(".plazia/local/openapi.json").write_text(json.dumps(app.openapi(), indent=2)+"\n")'
openapi-check:
	@$(PLAZIA_TOOLS) check openapi $(CHECK_FLAGS)

browser-install:
	$(UV) run --locked playwright install chromium

frontend:
	$(UV) run --locked python tools/ui.py

docs-check:
	@$(PLAZIA_TOOLS) check links $(CHECK_FLAGS)
actions-check:
	@$(PLAZIA_TOOLS) check actions $(CHECK_FLAGS)
endif
