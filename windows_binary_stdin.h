#ifndef AUTO_RX_WINDOWS_BINARY_STDIN_H
#define AUTO_RX_WINDOWS_BINARY_STDIN_H

#if defined(_WIN32)
#include <stdio.h>
#include <fcntl.h>
#include <io.h>

static void __attribute__((constructor)) auto_rx_set_binary_stdin(void) {
    _setmode(_fileno(stdin), _O_BINARY);
}
#endif

#endif
