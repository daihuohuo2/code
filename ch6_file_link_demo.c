#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void die(const char *msg) {
    perror(msg);
    exit(1);
}

static void show_stat(const char *label, const char *path) {
    struct stat st;
    if (stat(path, &st) < 0) {
        die("stat");
    }
    printf(
        "%s: path=%s inode=%llu nlink=%llu size=%lld mode=%o\n",
        label,
        path,
        (unsigned long long)st.st_ino,
        (unsigned long long)st.st_nlink,
        (long long)st.st_size,
        st.st_mode & 07777
    );
}

static void show_fstat(const char *label, int fd) {
    struct stat st;
    if (fstat(fd, &st) < 0) {
        die("fstat");
    }
    printf(
        "%s: inode=%llu nlink=%llu size=%lld mode=%o\n",
        label,
        (unsigned long long)st.st_ino,
        (unsigned long long)st.st_nlink,
        (long long)st.st_size,
        st.st_mode & 07777
    );
}

int main(void) {
    const char *origin = "ch6_origin.txt";
    const char *hardlink = "ch6_hardlink.txt";
    const char *message = "hello from rCore chapter 6\n";

    unlink(origin);
    unlink(hardlink);

    int fd = open(origin, O_CREAT | O_TRUNC | O_RDWR, 0644);
    if (fd < 0) {
        die("open origin");
    }
    if (write(fd, message, strlen(message)) != (ssize_t)strlen(message)) {
        die("write origin");
    }
    show_fstat("after create, fstat(origin fd)", fd);
    close(fd);

    show_stat("after create, stat(origin)", origin);

    if (link(origin, hardlink) < 0) {
        die("link");
    }
    show_stat("after link, stat(origin)", origin);
    show_stat("after link, stat(hardlink)", hardlink);

    if (unlink(origin) < 0) {
        die("unlink origin");
    }
    show_stat("after unlink origin, stat(hardlink)", hardlink);

    fd = open(hardlink, O_RDONLY);
    if (fd < 0) {
        die("open hardlink");
    }
    char buf[128] = {0};
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    if (n < 0) {
        die("read hardlink");
    }
    printf("read through hardlink: %s", buf);
    close(fd);

    if (unlink(hardlink) < 0) {
        die("unlink hardlink");
    }
    puts("all hard links removed, demo done");
    return 0;
}
