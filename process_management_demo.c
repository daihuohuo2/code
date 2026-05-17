#define _GNU_SOURCE

#include <errno.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static void die(const char *message) {
    perror(message);
    exit(1);
}

int main(void) {
    errno = 0;
    int old_nice = getpriority(PRIO_PROCESS, 0);
    if (old_nice == -1 && errno != 0) {
        die("getpriority before nice");
    }

    errno = 0;
    int new_nice = nice(3);
    if (new_nice == -1 && errno != 0) {
        die("nice");
    }
    printf("[ch5] nice value: %d -> %d\n", old_nice, new_nice);

    pid_t child = fork();
    if (child < 0) {
        die("fork");
    }
    if (child == 0) {
        char *argv[] = {"/bin/echo", "[ch5] child exec says hello", NULL};
        execve("/bin/echo", argv, environ);
        _exit(127);
    }

    int status = 0;
    if (waitpid(child, &status, 0) < 0) {
        die("waitpid fork child");
    }
    printf("[ch5] fork+exec child exit status: %d\n", WEXITSTATUS(status));

    pid_t spawned = -1;
    char *spawn_argv[] = {"/bin/echo", "[ch5] posix_spawn says hello", NULL};
    int rc = posix_spawn(&spawned, "/bin/echo", NULL, NULL, spawn_argv, environ);
    if (rc != 0) {
        errno = rc;
        die("posix_spawn");
    }

    if (waitpid(spawned, &status, 0) < 0) {
        die("waitpid spawned child");
    }
    printf("[ch5] posix_spawn child exit status: %d\n", WEXITSTATUS(status));
    return 0;
}