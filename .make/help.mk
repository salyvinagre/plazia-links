PLAZIA_MAKE_HELP_GOALS := $(strip $(MAKECMDGOALS))
PLAZIA_MAKE_HELP_ACTIVE := $(filter help,$(PLAZIA_MAKE_HELP_GOALS))
PLAZIA_MAKE_HELP_TARGET := help
PLAZIA_MAKE_HELP_PAGE := $(PLAZIA_HELP_ROOT)/index.txt
PLAZIA_MAKE_HELP_AWK := BEGIN { b=sprintf("%c[1m",27); r=sprintf("%c[0m",27) } \
  /^[A-Z][A-Z0-9 _-]*$$/ && (NR==1 || p=="") \
  { print b $$0 r; p=$$0; next } { print; p=$$0 }

ifneq ($(PLAZIA_MAKE_HELP_ACTIVE),)
ifneq ($(PLAZIA_MAKE_HELP_GOALS),help)
ifneq ($(words $(PLAZIA_MAKE_HELP_GOALS)),2)
$(error Usage: make help | make <public-target> help [SELECTOR=value])
endif
ifneq ($(lastword $(PLAZIA_MAKE_HELP_GOALS)),help)
$(error Usage: make help | make <public-target> help [SELECTOR=value])
endif
PLAZIA_MAKE_HELP_TARGET := $(firstword $(PLAZIA_MAKE_HELP_GOALS))
ifeq ($(filter $(PLAZIA_PUBLIC_TARGETS),$(PLAZIA_MAKE_HELP_TARGET)),)
$(error Unknown public target; run make help)
endif
PLAZIA_MAKE_HELP_PAGE := $(PLAZIA_HELP_ROOT)/$(PLAZIA_MAKE_HELP_TARGET).txt
PLAZIA_MAKE_HELP_SELECTOR := $(PLAZIA_HELP_SELECTOR_$(PLAZIA_MAKE_HELP_TARGET))
ifneq ($(PLAZIA_MAKE_HELP_SELECTOR),)
ifneq ($(filter command line environment environment override,$(origin $(PLAZIA_MAKE_HELP_SELECTOR))),)
PLAZIA_MAKE_HELP_VALUE := $($(PLAZIA_MAKE_HELP_SELECTOR))
ifneq ($(PLAZIA_MAKE_HELP_SELECTOR),RELEASE_ENV)
ifeq ($(filter $(PLAZIA_HELP_VALUES_$(PLAZIA_MAKE_HELP_TARGET)),$(PLAZIA_MAKE_HELP_VALUE)),)
$(error Unsupported $(PLAZIA_MAKE_HELP_SELECTOR); supported: $(PLAZIA_HELP_VALUES_$(PLAZIA_MAKE_HELP_TARGET)))
endif
endif
PLAZIA_MAKE_HELP_DETAIL := $(PLAZIA_HELP_DETAIL_$(PLAZIA_MAKE_HELP_TARGET)_$(PLAZIA_MAKE_HELP_SELECTOR)_$(PLAZIA_MAKE_HELP_VALUE))
ifneq ($(PLAZIA_MAKE_HELP_DETAIL),)
PLAZIA_MAKE_HELP_PAGE := $(PLAZIA_MAKE_HELP_DETAIL)
endif
endif
endif
ifneq ($(PLAZIA_MAKE_HELP_TARGET),help)
.PHONY: $(PLAZIA_MAKE_HELP_TARGET)
$(PLAZIA_MAKE_HELP_TARGET): ; @:
endif
endif
endif

ifeq ($(wildcard $(PLAZIA_MAKE_HELP_PAGE)),)
$(error Missing Make help page: $(patsubst $(CURDIR)/%,%,$(PLAZIA_MAKE_HELP_PAGE)))
endif

.PHONY: help
help:
	@if [ -t 1 ] && [ -z "$${NO_COLOR:-}" ]; then \
		awk '$(PLAZIA_MAKE_HELP_AWK)' "$(PLAZIA_MAKE_HELP_PAGE)"; \
	else \
		cat "$(PLAZIA_MAKE_HELP_PAGE)"; \
	fi
