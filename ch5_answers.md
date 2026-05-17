# rCore 第五章练习完成稿

## 一、编程题完成情况

### 1. 实验环境

实验环境：
- 操作系统：Ubuntu 24.04 on WSL
- 实验目录：`/home/daihuohuo/code/ch5-exercises`
- rCore 第五章工程：`/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5`
- Rust 目标平台：`riscv64gc-unknown-none-elf`
- QEMU 启动方式：`-bios default -kernel`

本章需要的配置命令：

```bash
cd /home/daihuohuo/code
mkdir -p ch5-exercises

rustup target add riscv64gc-unknown-none-elf
cargo install cargo-binutils
rustup component add rust-src
rustup component add llvm-tools-preview

sudo apt update
sudo apt install -y build-essential qemu-system-misc
```

如果 `cargo install cargo-binutils` 已经安装过，会提示已存在，不影响后续实验。

### 2. 课后编程题 1：使用 Linux 进程管理系统调用

写一个 Linux 程序，把 `nice`、`fork`、`exec`、`posix_spawn` 等进程相关系统调用都跑一遍。

相关文件：
- `process_management_demo.c`
- `Makefile`

运行命令：

```bash
cd /home/daihuohuo/code/ch5-exercises
make clean
make
./process_management_demo
```

`process_management_demo.c` 代码如下：

```c
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
```

`Makefile` 代码如下：

```makefile
CC := gcc
CFLAGS := -Wall -Wextra -O2 -std=c11

.PHONY: all clean run run-fork-count

all: process_management_demo fork_expr_count

process_management_demo: process_management_demo.c
	$(CC) $(CFLAGS) -o $@ $<

fork_expr_count: fork_expr_count.c
	$(CC) $(CFLAGS) -o $@ $<

run: all
	./process_management_demo
	./fork_expr_count

run-fork-count: fork_expr_count
	./fork_expr_count

clean:
	rm -f process_management_demo fork_expr_count
```

实现思路：先用 `getpriority`/`nice` 查看并调整进程优先级，然后 `fork` 出子进程，子进程里 `execve` 换成 `/bin/echo`，父进程 `waitpid` 回收；再用 `posix_spawn` 直接启动一个新程序，模拟 rCore `spawn` 的语义，最后再 `waitpid` 等它结束。

### 3. 课后编程题 2：显示操作系统切换进程的过程

在内核里加几行 log，在任务切换的地方打印出"从哪个进程切换到哪个进程"，这样就能看到调度器的工作过程。

改动位置：
- `/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src/task/manager.rs`
- `/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src/task/processor.rs`
- 或本地实际工程中负责 `run_tasks`、`schedule`、`fetch_task` 的同名模块

可查看任务模块：

```bash
find /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src/task -type f -maxdepth 1
grep -R "fn run_tasks\|fn schedule\|fetch_task\|__switch" -n /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src/task
```

关键补丁思路如下：

```rust
// 在调度器选中 next_task 后、__switch 之前加入日志。
let from_pid = processor_inner.current.as_ref().map(|task| task.pid.0);
let to_pid = next_task.pid.0;
println!(
    "[kernel] switch: {:?} -> {}",
    from_pid,
    to_pid
);
```

如果当前工程使用 `TaskManager::fetch_task()` 取就绪进程，可在取出任务时打印：

```rust
pub fn fetch_task(&self) -> Option<Arc<TaskControlBlock>> {
    let mut inner = self.inner.exclusive_access();
    let task = inner.ready_queue.pop_front();
    if let Some(task) = task.as_ref() {
        println!("[kernel] fetch runnable pid={}", task.pid.0);
    }
    task
}
```

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os
make run
```

预期看到：

```text
[kernel] fetch runnable pid=0
[kernel] switch: None -> 0
[kernel] fetch runnable pid=1
[kernel] switch: Some(0) -> 1
```

### 4. 课后编程题 3：分析 fork 逻辑表达式输出 A 的数量

题目代码：

```c
int main() {
    fork() && fork() && fork() || fork() && fork() || fork() && fork();
    printf("A");
    return 0;
}
```

答案：会输出 `22` 个 `A`。

我把通用计算程序放在：
- `/home/daihuohuo/code/ch5-exercises/fork_expr_count.c`

复现命令：

```bash
cd /home/daihuohuo/code/ch5-exercises
make fork_expr_count
./fork_expr_count
```

可用下面命令查看代码：

```bash
cat /home/daihuohuo/code/ch5-exercises/fork_expr_count.c
```

`fork_expr_count.c` 代码如下：

```c
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
```

计算过程：
1. `&&` 优先级比 `||` 高，所以表达式分为三段：`3 个 fork`、`2 个 fork`、`2 个 fork`。
2. 一个包含 `k` 个 `fork()` 的 `&&` 段，对每个进入的进程会产生 `1` 个真结果进程和 `k` 个假结果进程。
3. `||` 短路：真结果进程直接结束表达式并打印 `A`；假结果进程继续进入下一段。
4. 第一段：进入 `1` 个进程，打印贡献 `1`，继续 `3`。
5. 第二段：进入 `3` 个进程，打印贡献 `3`，继续 `6`。
6. 第三段：进入 `6` 个进程，打印贡献 `6`，最后假结果也会打印 `12`。
7. 总数：`1 + 3 + 6 + 12 = 22`。

### 5. 课后编程题 4：实现一种非 RR 调度算法

我选择 stride 调度作为实现方案，因为实验练习 2 也正好要求 stride。

核心规则：
- 每个进程维护 `priority`、`pass`、`stride`。
- `pass = BIG_STRIDE / priority`。
- 每次调度选择 `stride` 最小的 runnable 进程。
- 该进程被选中后执行 `stride += pass`。

建议修改位置：
- `/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src/task/task.rs`
- `/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src/task/manager.rs`
- `/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src/syscall/process.rs`
- `/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src/syscall/mod.rs`

任务控制块新增字段示例：

```rust
const BIG_STRIDE: usize = usize::MAX;
const DEFAULT_PRIORITY: usize = 16;

pub struct TaskControlBlockInner {
    // 原有字段省略
    pub priority: usize,
    pub stride: usize,
}

impl TaskControlBlockInner {
    pub fn pass(&self) -> usize {
        BIG_STRIDE / self.priority
    }
}
```

创建任务时初始化：

```rust
priority: DEFAULT_PRIORITY,
stride: 0,
```

实现 `set_priority`：

```rust
pub fn set_priority(&self, prio: isize) -> isize {
    if prio < 2 {
        return -1;
    }
    let mut inner = self.inner_exclusive_access();
    inner.priority = prio as usize;
    prio
}
```

系统调用分发：

```rust
const SYSCALL_SET_PRIORITY: usize = 140;

pub fn sys_set_priority(prio: isize) -> isize {
    if prio < 2 {
        return -1;
    }
    current_task().unwrap().set_priority(prio)
}
```

调度器选择最小 stride：

```rust
pub fn fetch_task(&self) -> Option<Arc<TaskControlBlock>> {
    let mut inner = self.inner.exclusive_access();
    if inner.ready_queue.is_empty() {
        return None;
    }
    let mut selected = 0;
    let mut selected_stride = usize::MAX;
    for (idx, task) in inner.ready_queue.iter().enumerate() {
        let stride = task.inner_exclusive_access().stride;
        if stride < selected_stride {
            selected = idx;
            selected_stride = stride;
        }
    }
    let task = inner.ready_queue.remove(selected).unwrap();
    {
        let mut task_inner = task.inner_exclusive_access();
        task_inner.stride = task_inner.stride.wrapping_add(task_inner.pass());
    }
    Some(task)
}
```

复现命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os
make run TEST=2
make run TEST=3
```

预期：
- `TEST=2` 检查 `set_priority` 语义。
- `TEST=3` 检查 stride 公平性，即不同优先级进程获得 CPU 的次数大致与优先级成比例。

### 6. 课后编程题 5：扩展内核支持多核处理器

这是三星扩展题，本章基础实现不要求必须完成。可落地路线如下：

1. 为每个 hart 准备独立内核栈和 per-hart `Processor`。
2. `TaskManager` 的就绪队列必须加锁，或改为每核一个运行队列。
3. 时钟中断和调度入口要能区分当前 hart。
4. 需要处理跨核唤醒、负载均衡和关机同步。

核心结构示例：

```rust
pub struct Processor {
    pub current: Option<Arc<TaskControlBlock>>,
    pub idle_task_cx: TaskContext,
}

static PROCESSORS: [UPSafeCell<Processor>; MAX_HARTS] = /* per-hart init */;

pub fn current_processor() -> &'static UPSafeCell<Processor> {
    let hart_id = riscv::register::tp::read();
    &PROCESSORS[hart_id]
}
```

### 7. 课后编程题 6：扩展内核支持在内核态响应并处理中断

这是三星扩展题，本章基础实现不要求必须完成。关键点：

1. 内核态也可能被中断打断，所以要设计内核重入策略。
2. 临界区必须能屏蔽中断或使用可中断安全的锁。
3. Trap handler 要区分来自 U-mode 还是 S-mode。
4. 内核栈要能承受中断嵌套。

核心判断示例：

```rust
use riscv::register::sstatus::{self, SPP};

pub fn trap_handler() -> ! {
    let from_user = sstatus::read().spp() == SPP::User;
    if from_user {
        handle_user_trap();
    } else {
        handle_kernel_trap();
    }
}
```

临界区保护示例：

```rust
pub struct InterruptGuard {
    old_sie: bool,
}

impl InterruptGuard {
    pub fn new() -> Self {
        let old_sie = riscv::register::sstatus::read().sie();
        unsafe { riscv::register::sstatus::clear_sie(); }
        Self { old_sie }
    }
}

impl Drop for InterruptGuard {
    fn drop(&mut self) {
        if self.old_sie {
            unsafe { riscv::register::sstatus::set_sie(); }
        }
    }
}
```

## 二、实验练习完成情况

第五章页面说明实验练习 1 和实验练习 2 可以二选一完成。我选择完成实验练习 1：`spawn`。

### 1. 实验练习 1：实现 `spawn`

syscall ID = 400，直接从 ELF 路径创建新进程，成功返回子进程 pid，失败返回 -1。

**系统调用分发（syscall/mod.rs）：**

```rust
const SYSCALL_SPAWN: usize = 400;

match syscall_id {
    // 原有分支省略
    SYSCALL_SPAWN => sys_spawn(args[0] as *const u8),
    _ => panic!("Unsupported syscall_id: {}", syscall_id),
}
```

`sys_spawn` 实现：

```rust
use alloc::sync::Arc;
use crate::loader::get_app_data_by_name;
use crate::mm::translated_str;
use crate::task::{add_task, current_task, current_user_token, TaskControlBlock};

pub fn sys_spawn(path: *const u8) -> isize {
    trace!("kernel: sys_spawn");
    let token = current_user_token();
    let path = translated_str(token, path);
    let Some(elf_data) = get_app_data_by_name(path.as_str()) else {
        return -1;
    };

    let parent = current_task().unwrap();
    let child = Arc::new(TaskControlBlock::new(elf_data));
    let child_pid = child.pid.0;

    {
        let mut child_inner = child.inner_exclusive_access();
        child_inner.parent = Some(Arc::downgrade(&parent));
    }
    {
        let mut parent_inner = parent.inner_exclusive_access();
        parent_inner.children.push(child.clone());
    }

    add_task(child);
    child_pid as isize
}
```

实现思路：先把用户态路径字符串转到内核（`translated_str`），查 ELF 表，找不到就返回 -1。找到后直接 `TaskControlBlock::new(elf_data)` 建一个全新地址空间，设好父子关系，加进调度队列，返回新 pid 就完事了。

为什么不能简单做成 `fork + exec`：
- `fork` 会复制父进程地址空间。
- `exec` 又会立刻丢弃这份复制出来的地址空间。
- `spawn` 可以直接用目标 ELF 创建新地址空间，避免无效复制。

复现命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os
make run TEST=5 BASE=0
```

也可以只看 spawn 相关用户程序：

```bash
cat /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/user/src/bin/ch5_spawn0.rs
cat /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/user/src/bin/ch5_spawn1.rs
```

预期输出包含：

```text
Test spawn0 OK!
Test wait OK!
Test waitpid OK!
```

### 2. 实验练习 2：stride 调度补充说明

本次主线选择的是实验练习 1，所以实验练习 2 不作为最终验证路线。若继续完成实验练习 2，需要同时实现：
- `sys_set_priority`
- `priority/pass/stride` 字段
- 最小 stride 选择逻辑
- 溢出安全的 stride 比较

stride 溢出比较函数参考：

```rust
use core::cmp::Ordering;

#[derive(Copy, Clone)]
struct Stride(u64);

impl PartialOrd for Stride {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        let diff = self.0.wrapping_sub(other.0) as i64;
        if diff < 0 {
            Some(Ordering::Less)
        } else {
            Some(Ordering::Greater)
        }
    }
}

impl PartialEq for Stride {
    fn eq(&self, _other: &Self) -> bool {
        false
    }
}
```

解释：
- 用 `wrapping_sub` 允许无符号数自然溢出。
- 再转成有符号数判断差值方向。
- 在题目给出的约束下，两个有效 stride 的距离不会超过半个整数空间，因此这种比较能判断真实先后。

## 三、问答题参考答案

### 1. 如何查看 Linux 操作系统中的进程？

常用命令：
- `ps aux`
- `top`
- `htop`
- `pstree`
- `ls /proc`

例如：

```bash
ps aux | head
top
cat /proc/1/status
```

### 2. 简单描述进程地址空间中有哪些数据和代码。

典型进程地址空间包括：
- 代码段：保存程序机器指令，通常只读可执行。
- 只读数据段：保存字符串常量等只读数据。
- 数据段：保存已初始化的全局变量和静态变量。
- BSS 段：保存未初始化的全局变量和静态变量。
- 堆：动态内存分配区域。
- 栈：函数调用、局部变量、返回地址等。
- mmap 区：共享库、文件映射、匿名映射等。

### 3. 进程控制块保存哪些内容？

进程控制块通常保存：
- pid 和进程状态
- 内核栈
- trap 上下文
- 任务上下文
- 地址空间或页表 token
- 父进程和子进程关系
- 退出码
- 打开的文件、当前目录等资源
- 调度相关信息，例如 priority、stride、时间片等

### 4. 进程上下文切换需要保存哪些内容？

至少需要保存：
- 通用寄存器
- 栈指针 `sp`
- 返回地址 `ra`
- callee-saved 寄存器
- 当前页表或地址空间 token
- 当前内核栈位置
- 必要的特权级 CSR 状态

rCore 中通常通过 `TaskContext` 保存内核态任务切换所需的寄存器，通过 `TrapContext` 保存用户态陷入内核时的用户寄存器现场。

### 5. fork 为什么需要在父进程和子进程提供不同返回值？

因为 `fork` 之后父子进程从同一条指令之后继续执行。如果返回值完全相同，程序就无法判断自己处在父进程还是子进程路径中。通常：
- 父进程中 `fork` 返回子进程 pid。
- 子进程中 `fork` 返回 `0`。
- 出错返回负数。

这样同一份代码可以自然分叉成父进程逻辑和子进程逻辑。

### 6. fork + exec 浪费资源，有什么改进策略？

常见策略：
- COW：写时复制，`fork` 时父子共享物理页，只有写入时才复制。
- `vfork`：子进程先运行并共享父进程地址空间，直到 `exec` 或 `_exit`。
- `posix_spawn` 或内核 `spawn`：直接创建并执行目标程序，避免先复制再丢弃。

### 7. 为什么近年来 fork 仍然被批判？

主要原因是现代进程资源越来越复杂。`fork` 不只复制内存语义，还牵涉多线程、锁、文件描述符、GPU/网络设备、语言运行时、沙箱权限等。很多资源并不适合简单继承。即便 COW 解决了内存页复制成本，`fork` 的“复制整个进程再修补”的语义仍然会给现代系统带来复杂性、安全边界和运行时一致性问题。

### 8. 分析给定 fork 代码输出。

代码逻辑：

```c
int val = 2;
printf("%d", 0);
int pid = fork();
if (pid == 0) {
    val++;
    printf("%d", val);
} else {
    val--;
    printf("%d", val);
    wait(NULL);
}
val++;
printf("%d", val);
```

如果 `fork` 后父进程先运行：
- 先打印 `0`
- 父进程：`val = 1`，打印 `1`，等待子进程
- 子进程：`val = 3`，打印 `3`，然后 `val = 4`，打印 `4`
- 父进程等待结束后 `val = 2`，打印 `2`
- 输出：`01342`

如果 `fork` 后子进程先运行：
- 先打印 `0`
- 子进程：打印 `3` 和 `4`
- 父进程：打印 `1`，等待已经退出的子进程，然后打印 `2`
- 输出：`03412`

### 9. 为什么子进程退出后需要父进程 wait 才能被完全回收？

子进程退出后，内核仍要保留最小进程信息给父进程读取，例如 pid、退出码、退出原因等。父进程调用 `wait/waitpid` 后，内核把这些信息交给父进程，并释放子进程控制块。如果父进程一直不 wait，子进程会处于僵尸状态。

### 10. 有哪些可能的时机导致进程切换？

常见时机：
- 当前进程主动 `yield`
- 当前进程退出
- 当前进程阻塞等待 I/O、锁、子进程或事件
- 时间片耗尽触发时钟中断
- 更高优先级进程变为 runnable
- 异常处理后内核决定调度其他进程

### 11. 实现一种非 RR 调度算法的简要步骤。

以 stride 为例：
1. 在进程控制块中加入 `priority` 和 `stride`。
2. 增加 `sys_set_priority(prio)`，要求 `prio >= 2`。
3. 计算 `pass = BIG_STRIDE / priority`。
4. 调度时选择 runnable 队列中 `stride` 最小的进程。
5. 被选中的进程执行后更新 `stride += pass`。
6. 处理 stride 溢出比较问题。

### 12. 非抢占式和抢占式调度算法各有什么优点？

非抢占式优点：
- 实现简单。
- 上下文切换少。
- 对临界区和共享状态要求较低。

抢占式优点：
- 交互响应更好。
- 可以防止单个进程长期占用 CPU。
- 更适合多用户、多任务系统。

### 13. 前台进程和后台进程分类。

题目中的分类：
- `make 编译 linux`：后台计算。
- `vim 光标移动`：前台交互。
- `firefox 下载影片`：后台 I/O 任务。
- `游戏处理玩家点击鼠标开枪`：前台交互。
- `播放交响乐歌曲`：前台实时/准实时任务。
- `转码电影视频`：后台计算。

日常例子：
- 前台：编辑器输入、浏览器页面滚动、游戏、视频会议。
- 后台：云盘同步、系统更新、编译、压缩、备份。

### 14. RR 算法时间片长短对性能指标有什么影响？

时间片太长：
- 上下文切换少，吞吐较好。
- 响应时间变差，可能接近 FCFS。

时间片太短：
- 响应更及时。
- 上下文切换开销变大，缓存局部性变差。

所以 RR 时间片是在响应时间和调度开销之间折中。

### 15. 举例说明如何愚弄 MLFQ。

恶意进程可以在时间片快用完前主动 `yield` 或发起短暂 I/O，让调度器误以为它是交互型进程，从而避免被降到低优先级队列。这样它能长期保持较高优先级，挤占其他 CPU 密集型进程。

### 16. 多核执行和调度引入哪些新问题？

新问题包括：
- 多核运行队列设计
- 负载均衡
- 跨核唤醒
- 锁竞争
- Cache 一致性
- 处理器亲和性
- 中断路由
- 关机和调度状态同步

## 四、解题思路解析

### 1. 第五章和第四章相比新增了什么

1. 第四章重点是地址空间，第五章开始真正管理进程。
2. 新增 `fork`、`exec`、`waitpid`、`spawn` 等进程系统调用。
3. 进程控制块要维护父子关系和退出状态。
4. 调度器不再只是运行固定任务，而要支持动态加入新进程。
5. 用户 shell、initproc、wait 回收让系统更像一个真正的多进程 OS。

### 2. `spawn` 的核心设计

`spawn` 的关键不是“少写一个 syscall”，而是避免 `fork + exec` 的无效工作。它直接从目标 ELF 创建新地址空间，然后挂接父子关系，最后加入调度队列。这样子进程从一开始就是目标程序，不需要复制父进程地址空间。

### 3. fork 表达式统计方法

把表达式按 `||` 分段，每段内部是若干个 `&&` 连接的 `fork()`。对于包含 `k` 个 fork 的 AND 段，每个进入进程会产生 `1` 个真结果和 `k` 个假结果。真结果因为 OR 短路直接打印，假结果继续进入下一段。最后一段的假结果也会打印，所以题目结果是 `22`。

### 4. stride 调度的核心

stride 调度把“优先级高”转化为“pass 小”。优先级越高，每次运行后 stride 增长越慢，因此更容易再次成为最小 stride，被调度到的频率也更高。它比 RR 多维护两个字段，但概念很清楚。

## 五、文件位置

本次答案与 Linux 示例程序位于：

```text
/home/daihuohuo/code/ch5-exercises
```

其中包括：
- `answers.md`
- `process_management_demo.c`
- `fork_expr_count.c`
- `Makefile`
- 编译后生成的 `process_management_demo`
- 编译后生成的 `fork_expr_count`

第五章 rCore 工程位于：

```text
/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5
```

常用查看命令：

```bash
cat /home/daihuohuo/code/ch5-exercises/answers.md
cat /home/daihuohuo/code/ch5-exercises/process_management_demo.c
cat /home/daihuohuo/code/ch5-exercises/fork_expr_count.c
cat /home/daihuohuo/code/ch5-exercises/Makefile

grep -R "SYSCALL_SPAWN\|sys_spawn\|fn spawn" -n /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src
grep -R "set_priority\|stride\|priority" -n /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os/src
```

常用复现命令：

```bash
cd /home/daihuohuo/code/ch5-exercises
make clean
make
make run

cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/os
make run TEST=5 BASE=0
```

参考资料：
- rCore Tutorial Book v3 第五章练习：`https://rcore-os.cn/rCore-Tutorial-Book-v3/chapter5/5exercise.html`
