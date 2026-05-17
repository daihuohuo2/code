#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/*
 * Count how many processes reach printf("A") for expressions made of
 * fork(), && and ||, using C short-circuit semantics and && precedence.
 *
 * For one AND term containing k fork() calls, each incoming process creates:
 *   - 1 true-result process: all k forks returned true in the parent path
 *   - k false-result processes: the first false return stops the AND term
 *
 * For OR terms, true-result processes stop evaluating and reach printf;
 * false-result processes continue to the next OR term.
 */

static void skip_spaces(const char **p) {
    while (isspace((unsigned char)**p)) {
        (*p)++;
    }
}

static int consume(const char **p, const char *token) {
    size_t len = strlen(token);
    skip_spaces(p);
    if (strncmp(*p, token, len) == 0) {
        *p += len;
        return 1;
    }
    return 0;
}

static unsigned long long count_forks_in_and_term(const char **p) {
    unsigned long long forks = 0;
    if (!consume(p, "fork()")) {
        fprintf(stderr, "expected fork()\n");
        exit(1);
    }
    forks++;
    while (consume(p, "&&")) {
        if (!consume(p, "fork()")) {
            fprintf(stderr, "expected fork() after &&\n");
            exit(1);
        }
        forks++;
    }
    return forks;
}

static unsigned long long count_prints(const char *expr) {
    const char *p = expr;
    unsigned long long finished = 0;
    unsigned long long incoming = 1;

    for (;;) {
        unsigned long long k = count_forks_in_and_term(&p);
        finished += incoming; /* true result: OR short-circuits */
        incoming *= k;        /* false result: continue to next OR term */

        if (!consume(&p, "||")) {
            break;
        }
    }

    skip_spaces(&p);
    if (*p != '\0') {
        fprintf(stderr, "unexpected input near: %s\n", p);
        exit(1);
    }

    return finished + incoming; /* final false-result processes also print */
}

int main(int argc, char **argv) {
    const char *expr = "fork() && fork() && fork() || fork() && fork() || fork() && fork()";
    if (argc > 1) {
        expr = argv[1];
    }
    printf("expression: %s\n", expr);
    printf("A count: %llu\n", count_prints(expr));
    return 0;
}
