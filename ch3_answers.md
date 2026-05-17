# rCore 第三章练习完成稿

## 一、实验环境

- 操作系统：Ubuntu 24.04 on WSL2
- rCore 第三章工程：`/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch3`（ch3-lab 分支）
- Rust 编译目标：`riscv64gc-unknown-none-elf`
- QEMU 模拟 RISC-V 64 位硬件

环境准备命令（已安装过则跳过）：

```bash
rustup target add riscv64gc-unknown-none-elf
cargo install cargo-binutils
rustup component add rust-src llvm-tools-preview
sudo apt install -y build-essential qemu-system-misc
```

检出 ch3-lab 分支：

```bash
cd /home/daihuohuo/code
git clone https://github.com/LearningOS/rCore-Tutorial-Code-2025S.git \
    rCore-Tutorial-Code-2025S-ch3
cd rCore-Tutorial-Code-2025S-ch3
git checkout ch3-lab
```

## 二、实验任务：实现 `sys_trace`

### 背景

ch3 实验要求实现 syscall ID 410 对应的 `sys_trace`。它是 2025S 版本中代替旧版 `sys_task_info` 的调试接口，提供三种功能：

```rust
pub enum TraceRequest {
    Read    = 0,  // 读一个字节：trace(0, addr, 0) → 返回 addr 处的字节
    Write   = 1,  // 写一个字节：trace(1, addr, val) → 把 val 写到 addr
    Syscall = 2,  // 查系统调用次数：trace(2, syscall_id, 0) → 返回当前任务调用该 syscall 的次数
}
```

ch3 还没引入页表，用户程序地址和物理地址相同，内核可以直接通过指针读写用户内存。

---

### 改动 1：`os/src/config.rs` — 确认常量定义

```rust
// 系统调用 ID 最大值，用于数组大小
pub const MAX_SYSCALL_NUM: usize = 500;
```

---

### 改动 2：`os/src/task/task.rs` — 给 TCB 加统计字段

在 `TaskControlBlock` 结构体里新增两个字段：

```rust
use crate::config::MAX_SYSCALL_NUM;
use crate::timer::get_time_ms;  // 用于记录首次运行时间

pub struct TaskControlBlock {
    pub task_status: TaskStatus,
    pub task_cx: TaskContext,
    // 新增：每个 syscall 被调用的次数（下标 = syscall ID）
    pub syscall_times: [u32; MAX_SYSCALL_NUM],
    // 新增：任务第一次被调度运行的时间（毫秒），0 表示还没运行过
    pub first_run_time: usize,
}
```

初始化时把新字段清零：

```rust
impl TaskControlBlock {
    pub fn new() -> Self {
        Self {
            task_status: TaskStatus::UnInit,
            task_cx: TaskContext::zero_init(),
            syscall_times: [0; MAX_SYSCALL_NUM],
            first_run_time: 0,
        }
    }
}
```

---

### 改动 3：`os/src/task/mod.rs` — 暴露统计接口

在 `TaskManager` 的 `impl` 块里加两个方法，然后对外暴露为模块级公开函数：

```rust
impl TaskManager {
    /// 统计当前任务调用的 syscall 次数（在分发 syscall 之前调用）
    fn record_current_syscall(&self, syscall_id: usize) {
        let mut inner = self.inner.exclusive_access();
        let cur = inner.current_task;
        if syscall_id < MAX_SYSCALL_NUM {
            inner.tasks[cur].syscall_times[syscall_id] += 1;
        }
        // 如果这是任务第一次运行到 syscall，顺手记录首次运行时间
        if inner.tasks[cur].first_run_time == 0 {
            inner.tasks[cur].first_run_time = get_time_ms();
        }
    }

    /// 查询当前任务某个 syscall 的调用次数
    fn get_current_syscall_count(&self, syscall_id: usize) -> isize {
        let inner = self.inner.exclusive_access();
        let cur = inner.current_task;
        if syscall_id < MAX_SYSCALL_NUM {
            inner.tasks[cur].syscall_times[syscall_id] as isize
        } else {
            -1
        }
    }
}

/// 在 syscall 分发入口处调用，记录本次调用
pub fn record_current_syscall(syscall_id: usize) {
    TASK_MANAGER.record_current_syscall(syscall_id);
}

/// 给 sys_trace 用：查某 syscall 的调用次数
pub fn get_current_syscall_count(syscall_id: usize) -> isize {
    TASK_MANAGER.get_current_syscall_count(syscall_id)
}
```

---

### 改动 4：`os/src/syscall/mod.rs` — 注册 SYSCALL_TRACE 并计数

```rust
use crate::task::record_current_syscall;

const SYSCALL_WRITE:     usize = 64;
const SYSCALL_EXIT:      usize = 93;
const SYSCALL_YIELD:     usize = 124;
const SYSCALL_GET_TIME:  usize = 169;
const SYSCALL_TRACE:     usize = 410;   // 新增

pub fn syscall(syscall_id: usize, args: [usize; 3]) -> isize {
    // 进入 syscall 后、分发之前先计数
    // 这样 sys_trace(Syscall, id) 查到的次数包含本次调用本身
    record_current_syscall(syscall_id);

    match syscall_id {
        SYSCALL_WRITE    => sys_write(args[0], args[1] as *const u8, args[2]),
        SYSCALL_EXIT     => sys_exit(args[0] as i32),
        SYSCALL_YIELD    => sys_yield(),
        SYSCALL_GET_TIME => sys_get_time(args[0] as *mut TimeVal, args[1]),
        SYSCALL_TRACE    => sys_trace(args[0], args[1], args[2]),  // 新增
        _ => panic!("Unsupported syscall_id: {}", syscall_id),
    }
}
```

---

### 改动 5：`os/src/syscall/process.rs` — 实现 `sys_trace`

```rust
use crate::task::get_current_syscall_count;

const TRACE_READ:    usize = 0;
const TRACE_WRITE:   usize = 1;
const TRACE_SYSCALL: usize = 2;

/// sys_trace：内核调试接口
///   request=0: 读 id 地址处的一个字节，返回字节值；地址非法返回 -1
///   request=1: 把 data 低 8 位写到 id 地址，返回 0；地址非法返回 -1
///   request=2: 返回当前任务调用 syscall id 的次数
pub fn sys_trace(request: usize, id: usize, data: usize) -> isize {
    match request {
        TRACE_READ => {
            // ch3 没有页表，用户地址即物理地址，内核可直接访问
            unsafe { *(id as *const u8) as isize }
        }
        TRACE_WRITE => {
            unsafe { *(id as *mut u8) = data as u8; }
            0
        }
        TRACE_SYSCALL => {
            // 注意：在进入本次 sys_trace 之前，
            // record_current_syscall(SYSCALL_TRACE) 已经执行，
            // 所以这里查到的 TRACE 次数已经包含本次调用
            get_current_syscall_count(id)
        }
        _ => -1,
    }
}
```

---

## 三、测试样例在哪

测试用例在 GitHub 仓库 [`LearningOS/rCore-Tutorial-Test-2025S`](https://github.com/LearningOS/rCore-Tutorial-Test-2025S) 的 `src/bin/` 目录下：

| 文件 | 说明 |
|------|------|
| `ch3b_yield0.rs` | 三个任务交替 yield，观察调度顺序 |
| `ch3b_yield1.rs` | yield 基础测试（输出 B） |
| `ch3b_yield2.rs` | yield 基础测试（输出 C） |
| `ch3_sleep.rs` | 任务 sleep 后能继续运行 |
| `ch3_sleep1.rs` | sleep 计时精度测试 |
| `ch3_trace.rs` | **主要测试：验证 sys_trace 的三种功能** |

`ch3_trace.rs` 的测试逻辑是：
1. 调用若干 `get_time()`、`sleep()`、`println!`。
2. 用 `count_syscall(SYSCALL_WRITE)` 等查询各 syscall 的调用次数，用 `assert_eq!` 校验。
3. 用 `trace_read(&var)` 读一个局部变量的值，校验返回的字节和变量值一致。
4. 用 `trace_write(&var, new_val)` 修改局部变量的值（绕过 Rust 不可变检查），再用 `read_volatile` 校验写入成功。
5. 用 `trace_read(main as *const _)` 读代码段地址，期望返回 `Some(某字节)` 而不是 `None`。

---

## 四、怎么复现测试结果

**在 WSL 里执行：**

```bash
# 1. 进入工程目录（ch3-lab 分支已 checkout）
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch3/os

# 2. 编译并运行所有 ch3 测例（BASE=1 表示跳过 ch2 的 bad 用例）
make run TEST=3 BASE=1
```

预期输出里应包含：

```text
Test write A OK!          ← ch3b_yield0
Test write B OK!          ← ch3b_yield1
Test write C OK!          ← ch3b_yield2
Test sleep OK!            ← ch3_sleep
Test sleep1 passed!       ← ch3_sleep1
Test trace OK!            ← ch3_trace （sys_trace 功能验证）
```

如果只想单独跑 trace 测试，可以临时在 `user/src/bin/` 里只保留 `ch3_trace.rs` 等文件然后 `make run`，或者通过 `TEST=3` + `BASE=1` 参数让构建系统只引入 ch3 的用例。

---

## 五、实验报告小结（报告要求部分）

### 与第二章相比本次增加的内容（≤5行）

第三章在第二章批处理的基础上，增加了同时在内存中驻留多个任务、时钟中断驱动的抢占式调度和 `yield` 协作式调度。为配合本次实验新增了 `sys_trace` 系统调用，用于在内核侧统计各 syscall 的调用次数，以及通过内核直接读写用户内存的调试功能。

### 问答作业（节选）

**1. 程序进入 U 态后，使用 S 态特权指令或访问 S 态寄存器会发生什么？**

会触发 `IllegalInstruction` 异常，CPU 切回 S 态并跳转到 `stvec` 指向的 trap handler。内核会在 trap handler 里打印错误信息并终止该进程。对应的测例是 `ch2b_bad_instructions.rs` 和 `ch2b_bad_register.rs`：运行后可以看到 `[kernel] IllegalInstruction in application` 相关提示。

**2. 机器加电后跳转到 0x80200000 的过程是什么？**

QEMU 上电后先从 0x1000 处运行 ROM 里的固件，随后跳到 0x80000000（RustSBI 所在位置）。SBI 完成硬件初始化，把 `mepc` 设为 0x80200000（内核入口），通过 `mret` 指令降权到 S-mode 并跳转到内核。内核随即完成剩余初始化并进入任务调度。
