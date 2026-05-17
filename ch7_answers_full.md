# rCore 第七章练习完成稿

## 一、实验环境

- 操作系统：Ubuntu 24.04 on WSL2
- 答案目录：`/home/daihuohuo/code/ch7-exercises`
- rCore 第七章工程：`/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch7`
- 练习来源：rCore Tutorial Book v3 第七章练习
- Linux 示例程序目录：`/home/daihuohuo/code/ch7-exercises`

基础配置命令：

```bash
cd /home/daihuohuo/code
mkdir -p ch7-exercises

rustup target add riscv64gc-unknown-none-elf
cargo install cargo-binutils
rustup component add rust-src
rustup component add llvm-tools-preview

sudo apt update
sudo apt install -y build-essential qemu-system-misc
```

第七章练习主要围绕进程间通信 IPC，包括：

- pipe 管道
- signal 信号
- mailbox 邮箱
- 共享内存、信号量、消息队列等 Linux IPC 机制

---

## 二、编程题完成情况

### 编程题 1 — 基于管道、共享内存、信号量和消息队列实现进程间数据交换

**目标**：写一个 Linux 用户态程序，演示多种 IPC 机制。

**实现位置**：

- `ch7-exercises/ipc_demo.c`

查看代码：

```bash
cat /home/daihuohuo/code/ch7-exercises/ipc_demo.c
```

运行步骤：

```bash
cd /home/daihuohuo/code/ch7-exercises
make clean
make
./ipc_demo
```

预期输出：

```text
[ch7] pipe child received: hello through anonymous pipe
[ch7] shared memory child read: hello from System V shared memory
[ch7] message queue child received: hello from System V message queue
[ch7] IPC demo finished successfully
```

代码如下：

```c
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
        printf("[ch7] pipe child received: %s\n", buffer);
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
        printf("[ch7] shared memory child read: %s\n", child_shared);
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
        printf("[ch7] message queue child received: %s\n", msg.text);
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
```

实现过程：

1. `pipe()` 创建匿名管道，父进程写入，子进程读取。
2. `shmget/shmat` 创建并映射 System V 共享内存。
3. `semget/semop` 创建信号量，保证子进程在父进程写完共享内存后再读。
4. `msgget/msgsnd/msgrcv` 创建消息队列，父进程发送一条消息，子进程接收。
5. 最后用 `IPC_RMID` 删除 System V IPC 资源，避免泄露。

---

### 编程题 2 — 基于 UNIX signal 实现异步通知

**目标**：用 UNIX signal 实现父进程对子进程的异步通知。

**实现位置**：

- `ch7-exercises/signal_demo.c`

查看代码：

```bash
cat /home/daihuohuo/code/ch7-exercises/signal_demo.c
```

运行步骤：

```bash
cd /home/daihuohuo/code/ch7-exercises
make
./signal_demo
```

预期输出：

```text
[ch7] parent sends SIGUSR1 to child ...
[ch7] child caught SIGUSR1
[ch7] signal demo finished successfully
```

代码如下：

```c
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
    if (kill(child, SIGUSR1) != 0) {
        perror("kill");
        return 1;
    }
    waitpid(child, NULL, 0);
    printf("[ch7] signal demo finished successfully\n");
    return 0;
}
```

实现过程：

1. 子进程通过 `sigaction` 注册 `SIGUSR1` handler。
2. 子进程使用 `pause()` 阻塞等待信号。
3. 父进程 `sleep(1)` 确保子进程 handler 已安装。
4. 父进程用 `kill(child, SIGUSR1)` 发送信号。
5. 子进程收到信号后执行 handler，打印提示并退出。

---

### 编程题 3 — 编写支持管道功能的简单 shell

**目标**：实现一个简单 shell，支持普通命令和一条管道命令。

**实现位置**：

- `ch7-exercises/mini_shell.c`

查看代码：

```bash
cat /home/daihuohuo/code/ch7-exercises/mini_shell.c
```

运行步骤：

```bash
cd /home/daihuohuo/code/ch7-exercises
make
printf "echo hello world | wc -w\nexit\n" | ./mini_shell
```

预期输出：

```text
mini-shell$ 2
mini-shell$
```

代码如下：

```c
#define _GNU_SOURCE

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define MAX_ARGS 16
#define MAX_LINE 256

static char *trim(char *text) {
    while (isspace((unsigned char) *text)) {
        text++;
    }
    if (*text == '\0') {
        return text;
    }
    char *end = text + strlen(text) - 1;
    while (end > text && isspace((unsigned char) *end)) {
        *end-- = '\0';
    }
    return text;
}

static void parse_args(char *line, char **argv) {
    int index = 0;
    char *token = strtok(line, " \t");
    while (token != NULL && index < MAX_ARGS - 1) {
        argv[index++] = token;
        token = strtok(NULL, " \t");
    }
    argv[index] = NULL;
}

static int run_simple(char *line) {
    char *argv[MAX_ARGS];
    parse_args(line, argv);
    if (argv[0] == NULL) {
        return 0;
    }
    pid_t child = fork();
    if (child < 0) {
        perror("fork");
        return 1;
    }
    if (child == 0) {
        execvp(argv[0], argv);
        perror("execvp");
        _exit(127);
    }
    int status = 0;
    waitpid(child, &status, 0);
    return WEXITSTATUS(status);
}

static int run_pipeline(char *left, char *right) {
    char *argv_left[MAX_ARGS];
    char *argv_right[MAX_ARGS];
    parse_args(left, argv_left);
    parse_args(right, argv_right);
    if (argv_left[0] == NULL || argv_right[0] == NULL) {
        return 1;
    }

    int fds[2];
    if (pipe(fds) != 0) {
        perror("pipe");
        return 1;
    }

    pid_t left_child = fork();
    if (left_child < 0) {
        perror("fork left");
        return 1;
    }
    if (left_child == 0) {
        dup2(fds[1], STDOUT_FILENO);
        close(fds[0]);
        close(fds[1]);
        execvp(argv_left[0], argv_left);
        perror("execvp left");
        _exit(127);
    }

    pid_t right_child = fork();
    if (right_child < 0) {
        perror("fork right");
        return 1;
    }
    if (right_child == 0) {
        dup2(fds[0], STDIN_FILENO);
        close(fds[0]);
        close(fds[1]);
        execvp(argv_right[0], argv_right);
        perror("execvp right");
        _exit(127);
    }

    close(fds[0]);
    close(fds[1]);
    waitpid(left_child, NULL, 0);
    int status = 0;
    waitpid(right_child, &status, 0);
    return WEXITSTATUS(status);
}

int main(void) {
    char line[MAX_LINE];

    while (1) {
        printf("mini-shell$ ");
        fflush(stdout);
        if (fgets(line, sizeof(line), stdin) == NULL) {
            putchar('\n');
            break;
        }

        char *input = trim(line);
        if (*input == '\0') {
            continue;
        }
        if (strcmp(input, "exit") == 0) {
            break;
        }

        char *pipe_symbol = strchr(input, '|');
        if (pipe_symbol != NULL) {
            *pipe_symbol = '\0';
            char *left = trim(input);
            char *right = trim(pipe_symbol + 1);
            run_pipeline(left, right);
        } else {
            run_simple(input);
        }
    }

    return 0;
}
```

实现过程：

1. 读取一行命令。
2. 如果是 `exit`，退出 shell。
3. 如果没有 `|`，走普通 `fork + execvp + waitpid`。
4. 如果存在 `|`，先用 `pipe()` 创建管道。
5. 左侧子进程把标准输出重定向到管道写端。
6. 右侧子进程把标准输入重定向到管道读端。
7. 父进程关闭管道两端并等待两个子进程退出。

---

### 编程题 4 — 扩展内核，实现共享内存机制

**目标**：在 rCore 内核中实现共享内存，让多个进程映射同一组物理页。

核心设计：

```rust
pub struct SharedMemory {
    pub key: usize,
    pub frames: Vec<FrameTracker>,
    pub ref_count: usize,
    pub size: usize,
}
```

实现步骤：

1. 内核维护一张全局共享内存表：`key -> SharedMemory`。
2. `shmget(key, size)` 查表，存在则返回 id，不存在则分配物理页。
3. `shmat(id, addr)` 把这组物理页映射到当前进程地址空间。
4. 每个进程可以用不同虚拟地址映射同一物理页。
5. `shmdt` 解除当前进程映射，引用计数减一。
6. 引用计数为 0 时释放物理页。

代码片段：

```rust
pub fn sys_shmat(id: usize, addr: usize) -> isize {
    let shm = SHM_MANAGER.exclusive_access().get(id)?;
    let task = current_task().unwrap();
    let mut inner = task.inner_exclusive_access();
    inner.memory_set.map_shared_frames(addr.into(), &shm.frames, MapPermission::R | MapPermission::W | MapPermission::U);
    addr as isize
}
```

---

### 编程题 5 — 扩展内核，实现 signal 机制

**目标**：在内核中实现 UNIX 风格信号机制。

核心结构：

```rust
pub struct SignalActions {
    pub table: [SignalAction; MAX_SIG],
}

pub struct TaskControlBlockInner {
    pub signal_pending: SignalFlags,
    pub signal_mask: SignalFlags,
    pub signal_actions: SignalActions,
}
```

实现步骤：

1. `kill(pid, signum)` 设置目标进程 `signal_pending`。
2. `sigaction(signum, handler)` 注册用户态 handler。
3. `sigprocmask` 修改当前进程 signal mask。
4. 每次从 trap 返回用户态前检查 pending 且未被 mask 的信号。
5. 若 handler 是默认动作，按信号默认语义处理。
6. 若 handler 是用户函数，构造 signal frame，使用户态先执行 handler。
7. handler 结束后调用 `sigreturn` 恢复原上下文。

代码片段：

```rust
pub fn handle_signals() {
    let task = current_task().unwrap();
    let mut inner = task.inner_exclusive_access();
    let signal = inner.signal_pending.difference(inner.signal_mask).first();
    if let Some(signum) = signal {
        inner.signal_pending.remove(signum);
        match inner.signal_actions.table[signum].handler {
            SignalHandler::Default => terminate_current_with_signal(signum),
            SignalHandler::User(handler) => setup_signal_frame(handler, signum),
            SignalHandler::Ignore => {}
        }
    }
}
```

---

## 三、实验练习完成情况

### 实验练习 1 — 实现进程通信邮箱

**目标**：为每个进程实现一个 mailbox，支持进程之间发送固定大小消息。

建议系统调用：

- `mailread(buf: *mut u8, len: usize) -> isize`
- `mailwrite(pid: usize, buf: *const u8, len: usize) -> isize`

核心规则：

1. 每个进程有一个邮箱。
2. 邮箱最多保存 16 条消息。
3. 每条消息最大 256 字节。
4. `mailwrite` 写入目标进程邮箱，邮箱满返回 `-1`。
5. `mailread` 从当前进程邮箱读一条消息，邮箱空返回 `-1`。

内核结构示例：

```rust
pub const MAILBOX_SIZE: usize = 16;
pub const MAIL_SIZE: usize = 256;

#[derive(Copy, Clone)]
pub struct Mail {
    pub len: usize,
    pub data: [u8; MAIL_SIZE],
}

pub struct MailBox {
    pub queue: VecDeque<Mail>,
}

impl MailBox {
    pub fn write(&mut self, data: &[u8]) -> isize {
        if self.queue.len() >= MAILBOX_SIZE {
            return -1;
        }
        let mut mail = Mail { len: data.len().min(MAIL_SIZE), data: [0; MAIL_SIZE] };
        mail.data[..mail.len].copy_from_slice(&data[..mail.len]);
        self.queue.push_back(mail);
        mail.len as isize
    }

    pub fn read(&mut self, out: &mut [u8]) -> isize {
        let Some(mail) = self.queue.pop_front() else {
            return -1;
        };
        let len = mail.len.min(out.len());
        out[..len].copy_from_slice(&mail.data[..len]);
        len as isize
    }
}
```

实现步骤：

1. 在 `TaskControlBlockInner` 中增加 `mailbox: MailBox`。
2. 在 `sys_mail_write(pid, buf, len)` 中根据 pid 找目标进程。
3. 用当前页表翻译用户缓冲区，把消息复制到内核临时数组。
4. 把消息压入目标进程邮箱。
5. 在 `sys_mail_read(buf, len)` 中从当前进程邮箱弹出消息。
6. 把消息复制回用户缓冲区。

查看和运行建议：

```bash
grep -R "mail_read\|mail_write\|MailBox\|mailbox" -n /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch7/os/src
grep -R "mail_read\|mail_write" -n /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch7/user/src

cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch7/os
make run TEST=7 BASE=0
```

预期输出应包含：

```text
mail read/write test passed
ch7_usertest passed
```

---

### 实验练习 2 — pipe 管道

**目标**：支持 `pipe`、`read`、`write`、`close`，让父子进程能通过 fd 通信。

核心结构：

```rust
pub struct Pipe {
    readable: bool,
    writable: bool,
    buffer: Arc<UPSafeCell<PipeRingBuffer>>,
}

pub struct PipeRingBuffer {
    arr: [u8; RING_BUFFER_SIZE],
    head: usize,
    tail: usize,
    status: RingBufferStatus,
    write_end: Option<Weak<Pipe>>,
}
```

实现过程：

1. `pipe()` 创建一对文件对象：读端和写端。
2. 两端共享同一个环形缓冲区。
3. `write` 向缓冲区写入字节。
4. `read` 从缓冲区读取字节。
5. 缓冲区为空时，读端可以让出 CPU 等待写入。
6. 写端全部关闭后，读端读到 EOF。

复现命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch7/os
make run TEST=7 BASE=0
```

---

### 实验练习 3 — signal 信号

**目标**：支持信号的注册、屏蔽、投递和返回。

关键系统调用：

- `kill`
- `sigaction`
- `sigprocmask`
- `sigreturn`

实现过程：

1. 每个进程保存 pending 信号集合。
2. 发送信号只设置目标 pending 位。
3. 进程即将返回用户态时检查 pending。
4. 如果信号未被 mask，则根据 action 执行默认行为或用户 handler。
5. 进入 handler 前保存原 TrapContext。
6. handler 调用 `sigreturn` 后恢复原 TrapContext。

复现命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch7/os
make run TEST=7 BASE=1
```

---

## 四、问答题参考答案

### 1. 直接通信和间接通信的本质区别是什么？

直接通信要求通信双方直接知道彼此身份，例如向指定 pid 发送信号。间接通信通过中间对象完成，例如管道、消息队列、邮箱、共享内存。直接通信关系清晰但耦合更强；间接通信更灵活，可支持多个发送者和接收者。

### 2. 如果在本章内核中实现 UNIX signal，大致设计思路是什么？

发送信号时只设置目标进程的 pending 标志。内核在 Trap 返回用户态前检查 pending 与 mask，找到可投递信号后，根据 `sigaction` 决定忽略、终止还是进入用户 handler。进入 handler 时需要保存原 TrapContext，handler 结束后通过 `sigreturn` 恢复。

### 3. 无名管道和有名管道的异同

相同点：都是 FIFO 字节流，常用于进程间通信。不同点：无名管道没有路径名，通常依赖 `fork` 后 fd 继承；有名管道 FIFO 是文件系统中的对象，无亲缘关系进程也能通过路径打开通信。

### 4. Linux 无名管道的特征和适用场景

无名管道轻量、顺序、半双工，适合父子进程或 shell 管线，例如 `cat file | grep keyword`。它不保留消息边界，只提供连续字节流。

### 5. Linux 消息队列的特征和适用场景

消息队列按消息为单位传输，保留消息边界，还可以按类型接收。它适合异步任务分发、日志队列、控制消息等场景。

### 6. Linux 共享内存的特征和适用场景

共享内存让多个进程直接访问同一块物理内存，速度快，适合大量数据交换。但它不自带同步机制，需要配合信号量、互斥锁或内存屏障。

### 7. bash 中按 Ctrl+C 会发生什么？

终端驱动会向前台进程组发送 `SIGINT`。默认行为是终止前台程序。shell 本身通常不会退出，而是重新显示提示符。

### 8. bash 中按 Ctrl+Z 会发生什么？

终端驱动会向前台进程组发送 `SIGTSTP`。默认行为是暂停前台程序，并把控制权交回 shell。之后可以用 `fg` 恢复到前台。

### 9. `kill -9 2022` 的含义是什么？

向 pid 为 2022 的进程发送信号 9，也就是 `SIGKILL`。它不能被捕获、不能被忽略、不能被阻塞，通常用于强制终止进程。

### 10. 举出一种跨计算机的主机间 IPC 机制

Socket。它可以用 TCP/UDP 在不同主机之间传输数据，是跨机器进程通信最常见的机制。

### 11. pipe 的实际应用

例如：

```bash
cat access.log | grep 404 | wc -l
```

第一个进程输出日志内容，第二个进程筛选 404 行，第三个进程统计行数。每个阶段都通过 pipe 串起来。

### 12. `__sync_synchronize` 的作用是什么？去掉会怎样？

`__sync_synchronize` 是全内存屏障，保证屏障前后的内存读写不会被编译器或 CPU 重排序。共享内存通信中，如果去掉它，另一个进程或线程可能看到标志位已经更新，但数据内容仍是旧值。

---

## 五、实验报告小结

第七章的核心是进程间通信。前几章已经有进程、地址空间、文件系统，第七章进一步让进程之间能够交换数据或发送异步事件。管道适合流式数据，邮箱和消息队列适合带边界的消息，共享内存适合大量数据，signal 适合异步通知。

本章我最需要掌握的是：IPC 不是一种机制，而是一组不同通信抽象。选择哪一种 IPC，取决于数据量、是否需要消息边界、是否异步、是否跨主机、是否需要同步。

---

## 六、文件结构总览

```text
ch7-exercises/
├── answers.md
├── ipc_demo.c
├── signal_demo.c
├── mini_shell.c
├── Makefile
├── ipc_demo
├── signal_demo
└── mini_shell
```

常用查看命令：

```bash
cat /home/daihuohuo/code/ch7-exercises/answers.md
cat /home/daihuohuo/code/ch7-exercises/ipc_demo.c
cat /home/daihuohuo/code/ch7-exercises/signal_demo.c
cat /home/daihuohuo/code/ch7-exercises/mini_shell.c
cat /home/daihuohuo/code/ch7-exercises/Makefile
```

常用运行命令：

```bash
cd /home/daihuohuo/code/ch7-exercises
make clean
make
./ipc_demo
./signal_demo
printf "echo hello world | wc -w\nexit\n" | ./mini_shell
```

rCore 第七章工程运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch7/os
make run TEST=7 BASE=0
make run TEST=7 BASE=1
```
