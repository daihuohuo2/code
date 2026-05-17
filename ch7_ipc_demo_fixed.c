#define _GNU_SOURCE

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ipc.h>
#include <sys/msg.h>
#include <sys/sem.h>
#include <sys/shm.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

union semun {
    int val;
    struct semid_ds *buf;
    unsigned short *array;
};

struct message {
    long mtype;
    char text[64];
};

static void die(const char *message) {
    perror(message);
    exit(1);
}

static void child_print(const char *prefix, const char *text) {
    char buffer[160];
    int n = snprintf(buffer, sizeof(buffer), "%s%s\n", prefix, text);
    if (n > 0) {
        ssize_t written = write(STDOUT_FILENO, buffer, (size_t)n);
        (void)written;
    }
}

static void run_pipe_demo(void) {
    int fds[2];
    if (pipe(fds) != 0) {
        die("pipe");
    }

    pid_t child = fork();
    if (child < 0) {
        die("fork pipe");
    }
    if (child == 0) {
        close(fds[1]);
        char buffer[64] = {0};
        ssize_t size = read(fds[0], buffer, sizeof(buffer) - 1);
        if (size < 0) {
            _exit(2);
        }
        child_print("[ch7] pipe child received: ", buffer);
        close(fds[0]);
        _exit(0);
    }

    close(fds[0]);
    const char *payload = "hello through anonymous pipe";
    if (write(fds[1], payload, strlen(payload) + 1) < 0) {
        die("write pipe");
    }
    close(fds[1]);
    waitpid(child, NULL, 0);
}

static void run_shared_memory_demo(void) {
    int shmid = shmget(IPC_PRIVATE, 128, IPC_CREAT | 0600);
    if (shmid < 0) {
        die("shmget");
    }
    int semid = semget(IPC_PRIVATE, 1, IPC_CREAT | 0600);
    if (semid < 0) {
        die("semget");
    }
    union semun arg = {.val = 0};
    if (semctl(semid, 0, SETVAL, arg) < 0) {
        die("semctl SETVAL");
    }

    char *shared = (char *) shmat(shmid, NULL, 0);
    if (shared == (char *) -1) {
        die("shmat parent");
    }

    pid_t child = fork();
    if (child < 0) {
        die("fork shm");
    }
    if (child == 0) {
        char *child_shared = (char *) shmat(shmid, NULL, 0);
        if (child_shared == (char *) -1) {
            _exit(3);
        }
        struct sembuf wait_op = {.sem_num = 0, .sem_op = -1, .sem_flg = 0};
        if (semop(semid, &wait_op, 1) < 0) {
            _exit(4);
        }
        child_print("[ch7] shared memory child read: ", child_shared);
        shmdt(child_shared);
        _exit(0);
    }

    strcpy(shared, "hello from System V shared memory");
    struct sembuf post_op = {.sem_num = 0, .sem_op = 1, .sem_flg = 0};
    if (semop(semid, &post_op, 1) < 0) {
        die("semop post");
    }

    waitpid(child, NULL, 0);
    shmdt(shared);
    shmctl(shmid, IPC_RMID, NULL);
    semctl(semid, 0, IPC_RMID);
}

static void run_message_queue_demo(void) {
    int msqid = msgget(IPC_PRIVATE, IPC_CREAT | 0600);
    if (msqid < 0) {
        die("msgget");
    }

    pid_t child = fork();
    if (child < 0) {
        die("fork msg");
    }
    if (child == 0) {
        struct message msg = {0};
        if (msgrcv(msqid, &msg, sizeof(msg.text), 1, 0) < 0) {
            _exit(5);
        }
        child_print("[ch7] message queue child received: ", msg.text);
        _exit(0);
    }

    struct message msg = {.mtype = 1};
    strcpy(msg.text, "hello from System V message queue");
    if (msgsnd(msqid, &msg, sizeof(msg.text), 0) < 0) {
        die("msgsnd");
    }

    waitpid(child, NULL, 0);
    msgctl(msqid, IPC_RMID, NULL);
}

int main(void) {
    run_pipe_demo();
    run_shared_memory_demo();
    run_message_queue_demo();
    printf("[ch7] IPC demo finished successfully\n");
    return 0;
}
