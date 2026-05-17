# rCore 第二章练习完成稿

## 一、编程题完成情况

### 1. 实验环境

跑在 WSL 里的 Ubuntu 24.04 上：
- 实验目录：`/home/daihuohuo/code/ch2-exercises`
- rCore 第二章工程：`/home/daihuohuo/code/rCore-Tutorial-Code-2025S`
- Rust 编译目标：`riscv64gc-unknown-none-elf`（裸机 RISC-V 64 位，没有标准库）
- 用 QEMU 模拟 RISC-V 硬件跑内核镜像

本章需要的配置命令：

```bash
cd /home/daihuohuo/code
mkdir -p ch2-exercises

rustup target add riscv64gc-unknown-none-elf
cargo install cargo-binutils
rustup component add rust-src
rustup component add llvm-tools-preview

sudo apt update
sudo apt install -y build-essential qemu-system-misc
```

如果 `cargo install cargo-binutils` 已经安装过，会提示已存在，不影响后续实验。

### 2. 实验题：给 `sys_write` 加安全检查

原来的 `sys_write` 收到用户传来的指针，直接就拿去读内存了，根本没检查地址是否合法。恶意应用可以传一个别的应用的内存地址，让内核帮它读到不该读的内容。这道题就是要堵住这个漏洞——只允许读当前应用自己占用的那块内存。

补丁文件：
- `/home/daihuohuo/code/ch2-exercises/sys_write_safe_patch.rs`

怎么跑：

```bash
cd /home/daihuohuo/code/ch2-exercises
cat sys_write_safe_patch.rs

cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S/os
# 按 sys_write_safe_patch.rs 中注释，把代码分别合入 config.rs、batch.rs、syscall/fs.rs
make run LOG=TRACE
```

`sys_write_safe_patch.rs` 代码如下：

```rust
// sys_write safety-check patch sketch for rCore chapter 2 lab.
// Suggested files:
// - os/src/config.rs
// - os/src/batch.rs
// - os/src/syscall/fs.rs

pub const USER_STACK_SIZE: usize = 4096;
pub const APP_BASE_ADDRESS: usize = 0x8040_0000;
pub const APP_SIZE_LIMIT: usize = 0x20_000;

pub fn current_app_range() -> (usize, usize) {
    let app_id = get_current_app();
    let start = crate::config::APP_BASE_ADDRESS + app_id * crate::config::APP_SIZE_LIMIT;
    let end = start + crate::config::APP_SIZE_LIMIT;
    (start, end)
}

pub fn current_user_stack_range() -> (usize, usize) {
    extern "C" {
        fn boot_stack_top();
    }
    let top = boot_stack_top as usize;
    (top - crate::config::USER_STACK_SIZE, top)
}

pub fn is_current_app_buffer(buf: usize, len: usize) -> bool {
    let Some(end) = buf.checked_add(len) else {
        return false;
    };
    let (app_start, app_end) = current_app_range();
    let (stack_start, stack_end) = current_user_stack_range();
    (app_start <= buf && end <= app_end) || (stack_start <= buf && end <= stack_end)
}

const FD_STDOUT: usize = 1;

pub fn sys_write(fd: usize, buf: *const u8, len: usize) -> isize {
    match fd {
        FD_STDOUT => {
            let start = buf as usize;
            if !crate::batch::is_current_app_buffer(start, len) {
                println!(
                    "[kernel] sys_write rejected invalid buffer [{:#x}, {:#x})",
                    start,
                    start.saturating_add(len)
                );
                return -1;
            }
            let slice = unsafe { core::slice::from_raw_parts(buf, len) };
            let s = core::str::from_utf8(slice).unwrap();
            print!("{}", s);
            len as isize
        }
        _ => -1,
    }
}
```

实现思路：
1. 第二章还没有页表，没法做虚地址翻译，只能直接用"当前应用加载区间 + 用户栈区间"这两段地址范围来判断指针是否合法。
2. 在 `batch.rs` 里加两个辅助函数，分别返回当前应用的代码/数据区间和用户栈区间。
3. `sys_write` 里先用 `checked_add` 算出缓冲区末尾地址（防止整数溢出造成绕过），再检查是否落在合法范围内。
4. 合法就正常打印；不合法直接返回 `-1`，内核完全不碰那块内存。

### 3. 课后编程题 1：打印调用栈

在 panic 时顺着栈帧链把每一层的函数返回地址打出来，方便定位是哪里崩了。

补丁文件：
- `/home/daihuohuo/code/ch2-exercises/stack_trace.rs`

怎么跑：

```bash
cd /home/daihuohuo/code/ch2-exercises
cat stack_trace.rs

cp stack_trace.rs /home/daihuohuo/code/rCore-Tutorial-Code-2025S/os/src/stack_trace.rs
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S/os
# 在 src/main.rs 中加入 mod stack_trace;
# 在 panic handler 中调用 crate::stack_trace::print_stack_trace();
make run LOG=TRACE
```

关键前提：`.cargo/config.toml` 或 `.cargo/config` 中需要保留帧指针：

```toml
rustflags = [
    "-Cforce-frame-pointers=yes",
]
```

`stack_trace.rs` 代码如下：

```rust
use core::{arch::asm, ptr};

pub unsafe fn print_stack_trace() {
    let mut fp: *const usize;
    asm!("mv {}, fp", out(reg) fp);

    println!("== Begin stack trace ==");
    let mut depth = 0usize;
    while !fp.is_null() && depth < 32 {
        let saved_ra = *fp.sub(1);
        let saved_fp = *fp.sub(2);
        println!("#{}: ra={:#018x}, fp={:#018x}", depth, saved_ra, saved_fp);
        if saved_fp == 0 || saved_fp <= fp as usize {
            break;
        }
        fp = saved_fp as *const usize;
        depth += 1;
    }
    println!("== End stack trace ==");
}
```

实现思路：
1. 要先让编译器保留帧指针（在 `.cargo/config.toml` 里加 `-Cforce-frame-pointers=yes`），否则 fp 链会被优化掉，没法往上追。
2. 用内联汇编读 `fp` 寄存器，这是 RISC-V 当前帧的栈帧指针。
3. 按 RISC-V 栈帧布局：`*(fp-1)` 是返回地址 ra，`*(fp-2)` 是上一层的帧指针，顺着这条链就能遍历整个调用路径。
4. 最多追 32 层，避免栈被破坏时死循环。
5. 注册进 panic handler，崩溃时自动打印。

### 4. 课后编程题 2：`get_taskinfo`——让应用知道自己叫什么

给内核加一个新系统调用，让用户程序可以问内核"我是第几号应用、叫什么名字"。然后再写一个用户程序来调用它验证。

补丁文件：
- `/home/daihuohuo/code/ch2-exercises/get_taskinfo_patch.rs`

怎么跑：

```bash
cd /home/daihuohuo/code/ch2-exercises
cat get_taskinfo_patch.rs

cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S
# 按 get_taskinfo_patch.rs 注释，把 kernel/user 片段分别放入对应文件
cd os
make run LOG=TRACE
```

核心结构：

```rust
#[repr(C)]
#[derive(Copy, Clone)]
pub struct TaskInfo {
    pub id: usize,
    pub name: [u8; 32],
}
```

系统调用实现：

```rust
pub fn sys_get_taskinfo(info: *mut TaskInfo) -> isize {
    if info.is_null() {
        return -1;
    }
    let mut task_info = TaskInfo {
        id: crate::batch::get_current_app(),
        name: [0; 32],
    };
    let name = crate::batch::get_current_app_name().as_bytes();
    let len = core::cmp::min(name.len(), task_info.name.len() - 1);
    task_info.name[..len].copy_from_slice(&name[..len]);
    unsafe {
        info.write(task_info);
    }
    0
}
```

用户程序：

```rust
#![no_std]
#![no_main]

#[macro_use]
extern crate user_lib;

use user_lib::get_taskinfo;

#[no_mangle]
fn main() -> i32 {
    let info = get_taskinfo().expect("get_taskinfo failed");
    let end = info
        .name
        .iter()
        .position(|&ch| ch == 0)
        .unwrap_or(info.name.len());
    let name = core::str::from_utf8(&info.name[..end]).unwrap();
    println!("task id = {}, name = {}", info.id, name);
    0
}
```

实现思路：
1. 先定义 `TaskInfo` 结构，包含任务编号和一个 32 字节名称缓冲区，用 `#[repr(C)]` 保证内核和用户侧内存布局完全一致。
2. 在 `batch.rs` 里加两个函数：读当前应用编号，读应用名称字符串。
3. 在 `syscall()` 分发函数里加一个分支，把新系统调用号映射到 `sys_get_taskinfo`。
4. `sys_get_taskinfo` 填好结构体后，直接写到用户传进来的指针地址（第二章没有虚拟内存，地址可以直接用）。
5. 用户程序调这个系统调用，把返回的名字打出来，验证正确。

### 5. 课后编程题 3：统计系统调用次数

在内核里维护一张二维计数表，横轴是应用编号，纵轴是系统调用编号，每次系统调用触发时给对应格子加一，应用退出时打印统计。

补丁文件：
- `/home/daihuohuo/code/ch2-exercises/syscall_stats_patch.rs`

怎么跑：

```bash
cd /home/daihuohuo/code/ch2-exercises
cat syscall_stats_patch.rs

cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S/os
# 将统计表和 record_syscall 放入 syscall/mod.rs，退出时打印统计
make run LOG=TRACE
```

核心代码：

```rust
pub const MAX_APP_NUM: usize = 16;
pub const MAX_SYSCALL_ID: usize = 512;

static mut SYSCALL_COUNTS: [[usize; MAX_SYSCALL_ID]; MAX_APP_NUM] =
    [[0; MAX_SYSCALL_ID]; MAX_APP_NUM];

pub fn record_syscall(app_id: usize, syscall_id: usize) {
    if app_id < MAX_APP_NUM && syscall_id < MAX_SYSCALL_ID {
        unsafe {
            SYSCALL_COUNTS[app_id][syscall_id] += 1;
        }
    }
}

pub fn syscall(syscall_id: usize, args: [usize; 3]) -> isize {
    let app_id = crate::batch::get_current_app();
    record_syscall(app_id, syscall_id);
    match syscall_id {
        // SYSCALL_WRITE => sys_write(args[0], args[1] as *const u8, args[2]),
        // SYSCALL_EXIT => sys_exit(args[0] as i32),
        _ => panic!("Unsupported syscall_id: {}", syscall_id),
    }
}
```

实现思路：
1. 所有系统调用必须经过 `syscall()` 这个总入口，在这一处加计数最省事，不用到处改代码。
2. 每次进来都取当前 app 编号和系统调用号，给计数表里对应格子加一。
3. 应用正常退出（`sys_exit`）或异常被杀死时，打印这个 app 的全部统计。
4. 第二章最常出现的两个调用是 `write`（64 号）和 `exit`（93 号）。

### 6. 课后编程题 4：统计每个应用的执行时长

每个应用开始跑时记一下时间戳，退出时再读一次，相减就是运行时长。RISC-V 有 `time` 寄存器可以直接读计时值，很方便。

补丁文件：
- `/home/daihuohuo/code/ch2-exercises/time_exception_patch.rs`

怎么跑：

```bash
cd /home/daihuohuo/code/ch2-exercises
cat time_exception_patch.rs

cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S/os
# 增加 timer.rs，并在 run_next_app/sys_exit/trap_handler 对应位置调用
make run LOG=TRACE
```

核心代码：

```rust
use riscv::register::time;

pub fn get_time() -> usize {
    time::read()
}

pub fn get_time_ms() -> usize {
    get_time() / 10_000
}

static mut APP_START_MS: [usize; MAX_APP_NUM] = [0; MAX_APP_NUM];

pub fn mark_app_start(app_id: usize) {
    if app_id < MAX_APP_NUM {
        unsafe {
            APP_START_MS[app_id] = crate::timer::get_time_ms();
        }
    }
}

pub fn print_app_finish_time(app_id: usize) {
    if app_id < MAX_APP_NUM {
        let now = crate::timer::get_time_ms();
        let start = unsafe { APP_START_MS[app_id] };
        println!(
            "[kernel] app_{} finished, elapsed={}ms",
            app_id,
            now.saturating_sub(start)
        );
    }
}
```

实现思路：
1. 新建 `timer.rs`，封装读 `time` 寄存器的操作，折算成毫秒方便输出。
2. 在 `run_next_app` 里，每次切到新应用前把当前时间存到数组对应位置。
3. `sys_exit` 正常退出时打 `elapsed=xxxms`。
4. 异常退出的路径也要打，不然崩溃的 app 就没有时间记录了。

### 7. 课后编程题 5：打印异常程序的出错信息

应用崩溃时，内核已经知道异常类型、出错地址、触发异常的指令在哪，把这些信息打出来方便排查。

补丁文件：
- `/home/daihuohuo/code/ch2-exercises/time_exception_patch.rs`

复现命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S/os
make run LOG=TRACE
```

核心代码：

```rust
pub fn report_bad_app(scause: usize, stval: usize, sepc: usize) {
    let app_id = crate::batch::get_current_app();
    println!(
        "[kernel] app_{} exception: scause={:#x}, stval={:#x}, sepc={:#x}",
        app_id, scause, stval, sepc
    );
    crate::batch::print_app_finish_time(app_id);
}
```

实现思路：
1. `trap_handler` 里的 `match scause` 已经有各种异常分支，在 `StoreFault`、`IllegalInstruction` 等分支里加上打印逻辑就行。
2. `scause` 说明异常类型，`stval` 通常就是出错的虚拟地址，`sepc` 是触发异常的指令地址，三个寄存器一起读就能定位问题。
3. 把当前 app 编号、这三个值一起打出来，然后继续走"杀死应用、跑下一个"的正常流程。

## 二、问答题参考答案

### 1. 函数调用与系统调用有何区别？

函数调用只是同一特权级内的普通控制流转移，不会进入内核。系统调用通过 `ecall` 触发 Trap，从 U 态进入 S 态，由内核根据 syscall 编号统一分发处理。函数调用只受语言 ABI 约束；系统调用还涉及特权级切换、上下文保存、参数检查和内核安全边界。

### 2. 哪些寄存器记录了委托信息？RustSBI 委托了哪些异常/中断？

委托信息由 `medeleg` 和 `mideleg` 记录。`medeleg` 控制异常委托，`mideleg` 控制中断委托。OpenSBI 启动时通常会把 U 态 `ecall`、非法指令、访问异常、时钟中断等委托给 S 态，使 rCore 内核能在 S 态处理用户程序 Trap。

在当前环境里常见 OpenSBI 输出为：

```text
OpenSBI v1.3
Runtime SBI Version       : 1.0
Boot HART MIDELEG         : 0x0000000000001666
Boot HART MEDELEG         : 0x0000000000f0b509
```

### 3. 如果操作系统以应用程序库的形式存在，应用程序可以如何破坏操作系统？

如果 OS 和应用在同一特权级、同一地址空间，应用可以越界写内存覆盖 OS 数据结构，也可以伪造参数、修改函数指针、覆盖返回地址、无限消耗资源，甚至直接跳入 OS 内部函数。根本原因是没有硬件隔离。

### 4. 编译器、操作系统、处理器如何合作保护操作系统？

处理器提供特权级、Trap、CSR、地址保护等硬件机制；操作系统配置这些机制，把应用放在 U 态，把内核放在 S 态；编译器遵守 ABI、调用约定和可执行文件格式，让内核和应用能按统一规则传参、保存寄存器和链接运行。

### 5. RISC-V 的 S 态特权指令有哪些，大致作用是什么？

常见 S 态相关操作包括：
- `sret`：从 S 态返回到先前特权级。
- `wfi`：等待中断。
- `sfence.vma`：刷新地址转换缓存。
- 访问 `sstatus`、`sepc`、`stvec`、`sscratch`、`scause`、`stval` 等 CSR 的指令。

这些指令用于 Trap 进入/返回、上下文保存恢复、异常定位和地址空间管理。

### 6. 用户态执行特权指令后的硬件处理过程是什么？

CPU 会触发异常，自动把 Trap 原因写入 `scause`，把相关地址或值写入 `stval`，把异常指令地址写入 `sepc`，更新 `sstatus` 中的特权级状态，然后跳转到 `stvec` 指向的 S 态 Trap 入口。内核处理完后通过 `sret` 返回。

### 7. 操作系统完成用户态和内核态双向切换的一般过程是什么？

用户态到内核态：用户程序执行 `ecall` 或触发异常，CPU 跳到 `stvec`，汇编入口保存寄存器，进入 Rust 的 `trap_handler`。

内核态到用户态：内核准备 `TrapContext`，恢复通用寄存器、`sstatus`、`sepc`，最后执行 `sret`，CPU 回到 U 态继续执行用户程序。

### 8. riscv64 支持哪些中断/异常？如何判断进入内核的原因？

通过 `scause` 判断。最高位为 `1` 表示中断，为 `0` 表示异常；低位编码表示具体原因。重要寄存器包括：
- `scause`：Trap 原因。
- `sepc`：Trap 相关指令地址。
- `stval`：附加信息，常见是错误地址。
- `sstatus`：状态和特权级信息。
- `stvec`：Trap 入口地址。

### 9. 哪些情况下会出现特权级切换？

U 态到 S 态：系统调用、非法指令、访存异常、中断。S 态到 U 态：首次启动应用、系统调用处理完成后返回、异常处理后允许继续执行用户程序。

### 10. Trap 上下文是什么？本章包含什么？不保存会怎样？

Trap 上下文是发生 Trap 时保存的处理器状态。本章通常包含：

```rust
pub struct TrapContext {
    pub x: [usize; 32],
    pub sstatus: Sstatus,
    pub sepc: usize,
}
```

如果不保存这些内容，用户程序的寄存器值、返回地址和特权级状态都会被破坏，内核无法正确返回用户态。

## 三、实验练习与运行结果

### 1. 运行 bad 测例

复现命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S/os
make run LOG=TRACE
```

预期现象：
- `ch2b_bad_address` 触发页故障，被内核杀死。
- `ch2b_bad_instructions` 触发非法指令，被内核杀死。
- `ch2b_bad_register` 触发非法指令，被内核杀死。
- `ch2b_hello_world`、`ch2b_power_3`、`ch2b_power_5`、`ch2b_power_7` 正常执行。

典型输出：

```text
[kernel] PageFault in application, kernel killed it.
[kernel] IllegalInstruction in application, kernel killed it.
[kernel] IllegalInstruction in application, kernel killed it.
Hello, world!
power_3 [10000/10000]
power_5 [10000/10000]
power_7 [10000/10000]
All applications completed!
```

### 2. `trap.S` 中 `__alltraps` 和 `__restore`

`__alltraps` 的作用是从 U 态 Trap 到 S 态后，切换到内核栈并保存通用寄存器、`sstatus`、`sepc` 等上下文。

`__restore` 的作用是从内核准备好的 `TrapContext` 中恢复寄存器，并通过 `sret` 返回 U 态。第一次启动应用和系统调用返回都会用到它。

关键问题：
- 刚进入 `__restore` 时，`a0` 是 `TrapContext` 地址。
- `ld/csrw` 特殊处理 `sstatus`、`sepc`、`sscratch`。
- 恢复时跳过 `x2(sp)`，因为最后用 `csrrw sp, sscratch, sp` 专门交换用户栈和内核栈。
- `sret` 是真正完成状态切换的指令。

## 四、解题思路解析

### 1. 第二章主线

第二章的核心是把用户程序和内核隔离开。用户程序在 U 态运行，不能直接执行特权操作；一旦系统调用或异常发生，硬件 Trap 到 S 态，由内核统一处理。

### 2. 扩展题的共同入口

这些编程题看起来很多，但入口很集中：
- 调用栈：panic handler 和 `fp` 链。
- `get_taskinfo`：`batch.rs` 和 syscall 分发。
- syscall 统计：`syscall()` 统一入口。
- 完成时间：`run_next_app` 和 `sys_exit`。
- 异常统计：`trap_handler`。
- `sys_write` 安全检查：`syscall/fs.rs` 的用户指针验证。

### 3. 为什么 `sys_write` 必须检查用户地址

内核不能信任用户传入的指针。没有检查时，用户可以让内核读取任意地址，导致泄露或崩溃。第二章虽然还没有虚拟内存，但已经能用应用装载区和用户栈区做基本边界检查；后续章节会用页表翻译实现更完整的检查。

## 五、文件位置

本次答案和补丁示例位于：

```text
/home/daihuohuo/code/ch2-exercises
```

其中包括：
- `answers.md`
- `stack_trace.rs`
- `get_taskinfo_patch.rs`
- `syscall_stats_patch.rs`
- `time_exception_patch.rs`
- `sys_write_safe_patch.rs`

常用查看命令：

```bash
cat /home/daihuohuo/code/ch2-exercises/answers.md
cat /home/daihuohuo/code/ch2-exercises/stack_trace.rs
cat /home/daihuohuo/code/ch2-exercises/get_taskinfo_patch.rs
cat /home/daihuohuo/code/ch2-exercises/syscall_stats_patch.rs
cat /home/daihuohuo/code/ch2-exercises/time_exception_patch.rs
cat /home/daihuohuo/code/ch2-exercises/sys_write_safe_patch.rs
```

第二章 rCore 工程位于：

```text
/home/daihuohuo/code/rCore-Tutorial-Code-2025S
```

常用复现命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S/os
make run LOG=TRACE
```

参考资料：
- rCore Tutorial Book v3 第二章练习：`https://rcore-os.cn/rCore-Tutorial-Book-v3/chapter2/5exercise.html`
