// test_vuln_chain.c
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static void log_input(const char *s) {
    printf("input length=%zu\n", strlen(s));
}

static void step1(const char *s);
static void step2(const char *s);
static void vulnerable_copy(const char *s);

static void step1(const char *s) {
    log_input(s);
    step2(s);
}

static void step2(const char *s) {
    // just another hop in the call chain
    vulnerable_copy(s);
}

// Intentionally vulnerable: classic stack buffer overflow via strcpy.
static void vulnerable_copy(const char *s) {
    char buf[16];
    strcpy(buf, s);  // VULNERABLE: no bounds check
    printf("buf=%s\n", buf);
}

int main(int argc, char **argv) {
    if (argc < 2) return 1;
    step1(argv[1]);     
    return 0;
}