AUTO_RX_VERSION ?= $(shell cd auto_rx && (python -m autorx.version 2>/dev/null || python3 -m autorx.version))

# Uncomment to use clang as a compiler.
#CC = clang
#export CC

CFLAGS = -O3 -w -Wno-unused-variable -DVER_JSN_STR=\"$(AUTO_RX_VERSION)\"
ifeq ($(WINDOWS_BINARY_STDIN),1)
CFLAGS += -include $(abspath windows_binary_stdin.h)
endif
export CFLAGS

SUBDIRS := \
	demod/mod \
	imet \
	c50 \
	mk2a \
	scan \
	dropsonde \
	utils \
	weathex \

all: $(SUBDIRS)

clean: $(SUBDIRS)

$(SUBDIRS):
	$(MAKE) -C $@ $(MAKECMDGOALS)

.PHONY: all clean $(SUBDIRS)
