#define _POSIX_C_SOURCE 200809L

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static volatile sig_atomic_t received = 0;

static void on_signal(int signo) {
    received = signo;
    ssize_t written = write(STDOUT_FILENO, "[ch7] child caught SIGUSR1\n", 27);
    (void) written;
}

int main(void) {
    pid_t child = fork();
    if (child < 0) {
        perror("fork");
        return 1;
    }

    if (child == 0) {
        struct sigaction action;
        action.sa_handler = on_signal;
        sigemptyset(&action.sa_mask);
        action.sa_flags = 0;
        if (sigaction(SIGUSR1, &action, NULL) != 0) {
            _exit(2);
        }
        while (!received) {
            pause();
        }
        _exit(0);
    }

    sleep(1);
    printf("[ch7] parent sends SIGUSR1 to child %d\n", child);
    fflush(stdout);
    if (kill(child, SIGUSR1) != 0) {
        perror("kill");
        return 1;
    }
    waitpid(child, NULL, 0);
    printf("[ch7] signal demo finished successfully\n");
    return 0;
}
