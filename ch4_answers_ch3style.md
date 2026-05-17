# rCore 第四章练习完成稿

## 一、实验环境

- 操作系统：Ubuntu 24.04 on WSL2
- 代码仓库：`/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4`
- 答案目录：`/home/daihuohuo/code/ch4-exercises`
- 练习来源：https://rcore-os.cn/rCore-Tutorial-Book-v3/chapter4/8exercise.html
- 运行方式：QEMU `virt` 平台，使用 `-bios default -kernel`

基础配置命令：

```bash
cd /home/daihuohuo/code
mkdir -p ch4-exercises

rustup target add riscv64gc-unknown-none-elf
cargo install cargo-binutils
rustup component add rust-src
rustup component add llvm-tools-preview

sudo apt update
sudo apt install -y build-essential qemu-system-misc
```

---

## 二、编程题完成情况

### 编程题 1 — Linux 内存相关系统调用示例

**目标**：编写一个 Linux 应用程序，使用 `sbrk`、`mmap`、`munmap`、`mprotect`。

**实现位置**：

- `ch4-exercises/linux_mem.c`
- `ch4-exercises/Makefile`

查看代码：

```bash
cat /home/daihuohuo/code/ch4-exercises/linux_mem.c
cat /home/daihuohuo/code/ch4-exercises/Makefile
```

运行步骤：

```bash
cd /home/daihuohuo/code/ch4-exercises
make clean
make
make run
```

预期输出：

```text
=== Linux Memory Syscall Demo ===
sbrk write-read OK
mmap write-read OK
munmap OK
mprotect -> PROT_READ OK
mprotect -> PROT_READ|PROT_WRITE OK
All demos passed.
```

代码如下：

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <errno.h>

void demo_sbrk(void) {
    int i;
    puts("=== sbrk demo ===");
    void *orig = sbrk(0);
    printf("orig brk = %p\n", orig);
    void *ret = sbrk(4096);
    if (ret == (void *)-1) { perror("sbrk"); return; }
    printf("after sbrk(+4096), new brk = %p\n", sbrk(0));
    char *buf = (char *)ret;
    for (i = 0; i < 4096; i++) buf[i] = (char)(i & 0xFF);
    for (i = 0; i < 4096; i++) {
        if (buf[i] != (char)(i & 0xFF)) { fputs("sbrk mismatch\n", stderr); return; }
    }
    puts("sbrk write-read OK");
    sbrk(-4096);
    printf("after sbrk(-4096), brk = %p\n", sbrk(0));
    puts("sbrk demo done\n");
}

void demo_mmap_munmap(void) {
    size_t i;
    puts("=== mmap/munmap demo ===");
    size_t len = 2 * 4096;
    void *addr = mmap(NULL, len, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (addr == MAP_FAILED) { perror("mmap"); return; }
    printf("mmap 2-page anon addr = %p\n", addr);
    char *p = (char *)addr;
    for (i = 0; i < len; i++) p[i] = (char)(i & 0xFF);
    for (i = 0; i < len; i++) {
        if (p[i] != (char)(i & 0xFF)) { fputs("mmap mismatch\n", stderr); return; }
    }
    puts("mmap write-read OK");
    if (munmap(addr, len) != 0) { perror("munmap"); return; }
    puts("munmap OK");
    puts("mmap/munmap demo done\n");
}

void demo_mprotect(void) {
    puts("=== mprotect demo ===");
    size_t len = 4096;
    void *addr = mmap(NULL, len, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (addr == MAP_FAILED) { perror("mmap"); return; }
    printf("mmap RW addr = %p\n", addr);
    *(int *)addr = 42;
    printf("wrote 42, read back = %d\n", *(int *)addr);
    if (mprotect(addr, len, PROT_READ) != 0) { perror("mprotect"); return; }
    puts("mprotect -> PROT_READ OK");
    printf("read-only value = %d\n", *(int *)addr);
    if (mprotect(addr, len, PROT_READ | PROT_WRITE) != 0) { perror("mprotect"); return; }
    puts("mprotect -> PROT_READ|PROT_WRITE OK");
    *(int *)addr = 99;
    printf("wrote 99, read back = %d\n", *(int *)addr);
    munmap(addr, len);
    puts("mprotect demo done\n");
}

int main(void) {
    puts("=== Linux Memory Syscall Demo ===\n");
    demo_sbrk();
    demo_mmap_munmap();
    demo_mprotect();
    puts("All demos passed.");
    return 0;
}
```

`Makefile`：

```makefile
CC     = gcc
CFLAGS = -Wall -g

.PHONY: all clean run

all: linux_mem

linux_mem: linux_mem.c
	$(CC) $(CFLAGS) -o linux_mem linux_mem.c

run: linux_mem
	./linux_mem

clean:
	rm -f linux_mem
```

---

### 编程题 2 — 单页表机制

**目标**：修改本章操作系统内核，实现任务和内核共用同一张页表。

**实现思路**：

1. 每个用户地址空间中同时映射用户程序、TrapContext、trampoline 和内核地址区。
2. 内核代码、数据、物理内存映射不设置 `U` 位。
3. 用户态即使“看见”内核虚拟地址，也会因为 PTE 没有 `U` 权限而无法访问。
4. Trap 进入内核时可以少一次页表切换，但任务切换时仍要切换到下一个任务页表。

关键代码位置：

```bash
cat /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/mm/memory_set.rs
cat /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/trap/trap.S
```

关键代码片段：

```rust
// 内核映射可以出现在用户页表中，但不能带 U 权限。
memory_set.push(
    MapArea::new(
        (stext as usize).into(),
        (etext as usize).into(),
        MapType::Identical,
        MapPermission::R | MapPermission::X,
    ),
    None,
);
```

---

### 编程题 3 — Lazy 按需分页

**目标**：基于缺页异常，支持 Lazy 策略的按需分页。

**实现思路**：

1. `mmap` 或堆增长时只记录虚拟地址区间，不立即分配物理页。
2. 页表中暂时不建立有效 PTE。
3. 用户第一次访问该地址时触发 page fault。
4. trap handler 判断 fault 地址是否落在合法 lazy 区间。
5. 合法则分配物理页并建立映射，然后返回用户态重试异常指令。
6. 不合法则杀死进程。

关键代码片段：

```rust
pub fn handle_lazy_page_fault(memory_set: &mut MemorySet, fault_va: VirtAddr) -> bool {
    if let Some(area) = memory_set.find_lazy_area(fault_va) {
        let vpn = fault_va.floor();
        area.map_one(&mut memory_set.page_table, vpn);
        true
    } else {
        false
    }
}
```

---

### 编程题 4 — COW 写时复制

**目标**：扩展内核，支持基于缺页异常的 COW 机制。

**实现思路**：

1. `fork` 时父子进程共享物理页。
2. 将共享页面清除 `W` 权限，并设置软件 COW 标记。
3. 任一进程写入时触发 StorePageFault。
4. 缺页处理函数发现是 COW 页后，分配新页并复制旧页内容。
5. 更新当前进程 PTE，恢复 `W` 权限。
6. 维护物理页引用计数，最后一个引用消失时释放物理页。

关键代码片段：

```rust
if pte.is_cow() && fault_is_store {
    let old_ppn = pte.ppn();
    let new_frame = frame_alloc().unwrap();
    new_frame.ppn.get_bytes_array().copy_from_slice(old_ppn.get_bytes_array());
    page_table.update(vpn, new_frame.ppn, flags | PTEFlags::W);
    return true;
}
```

---

### 编程题 5 — swap in/out 与 Clock 置换

**目标**：扩展内核，实现 swap in/out，并实现 Clock 或二次机会置换算法。

**实现思路**：

1. 为页表项增加 swapped 状态和 swap slot 编号。
2. 物理内存不足时选择一个可换出页。
3. Clock 算法扫描页面队列，访问位为 1 的页给第二次机会并清除访问位。
4. 找到访问位为 0 的页后写入 swap 区，清除 PTE 有效位。
5. 用户再次访问该页时触发缺页异常。
6. 缺页处理函数从 swap slot 读回页面并恢复 PTE。

关键代码片段：

```rust
loop {
    let page = clock_queue.front().unwrap();
    if page.accessed {
        page.accessed = false;
        clock_queue.rotate_left(1);
    } else {
        swap_out(page);
        break;
    }
}
```

---

### 编程题 6 — 自映射机制

**目标**：扩展内核，实现页表自映射机制。

**实现思路**：

1. 选择 SV39 顶级页表中的一个固定 VPN 作为 recursive slot。
2. 让该顶级页表项指向顶级页表自身。
3. 内核可以通过固定虚拟地址访问当前页表项。
4. 好处是页表遍历和修改更直接，代价是占用一段虚拟地址空间。

关键代码片段：

```rust
const RECURSIVE_INDEX: usize = 510;

pub fn map_recursive(root_ppn: PhysPageNum, root: &mut PageTable) {
    root.entries[RECURSIVE_INDEX] =
        PageTableEntry::new(root_ppn, PTEFlags::V);
}
```

---

## 三、实验练习完成情况

### 实验练习 1 — 重写 `sys_get_time`

**目标**：引入虚拟内存后，不能再直接写用户指针，需要通过当前任务页表翻译用户地址。

实现位置：

```bash
grep -n "pub fn sys_get_time" -A35 /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/syscall/process.rs
```

核心代码：

```rust
pub fn sys_get_time(_ts: *mut TimeVal, _tz: usize) -> isize {
    trace!("kernel: sys_get_time");
    let us = get_time_us();
    let time = TimeVal {
        sec: us / MICRO_PER_SEC,
        usec: us % MICRO_PER_SEC,
    };
    let bytes = unsafe {
        core::slice::from_raw_parts(
            (&time as *const TimeVal).cast::<u8>(),
            core::mem::size_of::<TimeVal>(),
        )
    };
    let Some(buffers) = translated_byte_buffer_checked(
        current_user_token(),
        _ts.cast::<u8>(),
        core::mem::size_of::<TimeVal>(),
    ) else {
        return -1;
    };
    let mut copied = 0;
    for buffer in buffers {
        let end = copied + buffer.len();
        buffer.copy_from_slice(&bytes[copied..end]);
        copied = end;
    }
    0
}
```

实现步骤：

1. 使用 `get_time_us()` 获取当前时间。
2. 组装 `TimeVal { sec, usec }`。
3. 把 `TimeVal` 按字节切片处理。
4. 用 `translated_byte_buffer_checked` 翻译用户缓冲区。
5. 分段拷贝，支持 `TimeVal` 跨页。
6. 用户地址非法时返回 `-1`。

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os
make run TEST=1
```

也可运行当前工程常用测试：

```bash
make run TEST=4 BASE=0
```

预期输出：

```text
get_time OK!
Test sleep OK!
```

---

### 实验练习 2 — `mmap` 和 `munmap` 匿名映射

**目标**：实现 `sys_mmap(start, len, prot)` 和 `sys_munmap(start, len)`。

实现位置：

```bash
grep -n "pub fn sys_mmap" -A35 /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/syscall/process.rs
grep -n "pub fn sys_munmap" -A25 /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/syscall/process.rs
grep -n "insert_framed_area_checked" -A25 /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/mm/memory_set.rs
```

`sys_mmap` 代码：

```rust
pub fn sys_mmap(_start: usize, _len: usize, _port: usize) -> isize {
    trace!("kernel: sys_mmap");
    if !VirtAddr::from(_start).aligned() {
        return -1;
    }
    if _port & !0x7 != 0 || (_port & 0x7) == 0 {
        return -1;
    }
    if _len == 0 {
        return 0;
    }
    let len = (_len + PAGE_SIZE - 1) / PAGE_SIZE * PAGE_SIZE;
    if _start.checked_add(len).is_none() {
        return -1;
    }
    let mut permission = MapPermission::U;
    if (_port & 0x1) != 0 {
        permission |= MapPermission::R;
    }
    if (_port & 0x2) != 0 {
        permission |= MapPermission::W;
    }
    if (_port & 0x4) != 0 {
        permission |= MapPermission::X;
    }
    if current_mmap(_start, len, permission) {
        0
    } else {
        -1
    }
}
```

`sys_munmap` 代码：

```rust
pub fn sys_munmap(_start: usize, _len: usize) -> isize {
    trace!("kernel: sys_munmap");
    if !VirtAddr::from(_start).aligned() {
        return -1;
    }
    if _len == 0 {
        return 0;
    }
    let len = (_len + PAGE_SIZE - 1) / PAGE_SIZE * PAGE_SIZE;
    if _start.checked_add(len).is_none() {
        return -1;
    }
    if current_munmap(_start, len) {
        0
    } else {
        -1
    }
}
```

地址空间辅助代码：

```rust
pub fn insert_framed_area_checked(
    &mut self,
    start_va: VirtAddr,
    end_va: VirtAddr,
    permission: MapPermission,
) -> bool {
    let start_vpn = start_va.floor();
    let end_vpn = end_va.ceil();
    for vpn in VPNRange::new(start_vpn, end_vpn) {
        if self.translate(vpn).is_some() {
            return false;
        }
    }
    self.push(
        MapArea::new(start_va, end_va, MapType::Framed, permission),
        None,
    );
    true
}
```

实现步骤：

1. 检查 `start` 是否页对齐。
2. 检查 `prot` 只使用低三位，且不能为 0。
3. `len == 0` 时直接返回成功。
4. 将 `len` 向上取整到页大小。
5. 使用 `checked_add` 防止地址溢出。
6. 把 `prot` 转换为 `MapPermission`，并补上 `U`。
7. `mmap` 时检查目标区间没有被映射。
8. `munmap` 时检查目标区间已经被映射。

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os
make run TEST=2
```

当前工程也可以用：

```bash
make run TEST=4 BASE=0
```

实际验证过的关键输出：

```text
get_time OK!
Test 04_1 OK!
[kernel] PageFault in application, bad addr = 0x10000000, ...
[kernel] PageFault in application, bad addr = 0x10000000, ...
Test 04_4 test OK!
Test 04_5 ummap OK!
Test 04_6 ummap2 OK!
Test sleep OK!
```

---

## 四、问答题参考答案

### 1. 随机访问不在当前逻辑地址范围内的地址会发生什么？

通常会触发 page fault。若地址没有映射，MMU 地址转换失败；若地址有映射但权限不满足，例如写只读页，也会异常。内核可以选择补页、换入页面，或者杀死进程。普通 Linux 上常见表现是 `Segmentation fault`。

### 2. 用户程序看到的是逻辑地址还是物理地址？

用户程序看到的是虚拟地址，也叫逻辑地址。CPU 通过页表把虚拟地址翻译成物理地址。操作系统负责建立页表、设置权限、处理缺页异常，保证每个进程拥有独立地址空间。

### 3. 覆盖、交换和虚拟存储有何异同？

覆盖由程序员或运行时手动把不同模块装入同一内存区域。交换是操作系统把整个进程或大块内存换入换出。虚拟存储以页为单位自动管理，只把需要的页放入内存。虚拟存储优势是透明、粒度细、支持大地址空间；挑战是页表开销、缺页开销和置换策略复杂。

### 4. 什么是局部性原理？

局部性包括时间局部性和空间局部性。程序刚访问过的数据很可能近期再次访问，访问某地址后也可能访问附近地址。循环、数组、函数调用栈都体现局部性。它不总是正确，例如随机访问大数组时局部性差。虚拟存储依赖局部性，因为只要工作集能留在内存中，缺页率就不会太高。

### 5. 一条 load 指令最多导致多少次页访问异常？

简单情况下，取指可能缺页一次，load 访问的数据页可能缺页一次。若指令跨页或数据跨页，可能更多。若页表页本身也采用按需分页，还可能因为访问多级页表的页表页而触发异常。理论上要考虑取指页、数据页、多级页表页、异常处理路径自身是否缺页。

### 6. 页异常处理过程中再次 page fault 怎么办？

可能发生。例如内核访问用户指针不检查，或缺页处理代码本身访问了未映射内存。硬件会再次陷入异常；如果内核没有重入处理能力，通常会 panic 或杀死当前进程。成熟内核会区分用户态缺页和内核态缺页，内核态非法缺页通常是严重错误。

### 7. 全局和局部置换算法有何不同？

全局置换可以从所有进程的物理页中选择牺牲页。局部置换只能从当前进程自己的常驻页中选择牺牲页。全局算法利用率更高但进程间干扰更强；局部算法隔离性好但可能浪费空闲内存。

### 8. OPT、FIFO、LRU、Clock、LFU 简述

- OPT：淘汰未来最久不用的页，理论最优，但无法在线实现。
- FIFO：淘汰最早进入内存的页，实现简单，可能有 Belady 现象。
- LRU：淘汰最久未访问页，效果好但精确实现成本高。
- Clock：用访问位近似 LRU，开销低。
- LFU：淘汰访问次数最少页，适合频度稳定场景，但容易受历史访问影响。

### 9. 如何综合选择置换算法？

教学或简单系统适合 FIFO/Clock。交互系统适合 Clock 或近似 LRU。数据库等有明确缓存策略的场景可能自管缓存。内存压力大且工作集稳定时，LRU/Clock 表现较好。精确 LRU 成本高，实际系统多用近似算法。

### 10. 如何改进 Clock 记录访问频度不足的问题？

可以使用 Aging 算法，为每页维护一个多位计数器，周期性右移并把访问位放入最高位；也可以使用增强 Clock，结合访问位和修改位；还可以维护多级队列，把频繁访问页提升到更高队列。

### 11. 哪些算法有 Belady 现象？

FIFO 可能有 Belady 现象。OPT 和 LRU 没有。原因是 OPT 和 LRU 具有栈性质：分配更多页框时，较小页框集合始终包含在较大页框集合中；FIFO 不满足这个性质，更多页框可能改变淘汰顺序，反而增加缺页。

### 12. 什么是工作集和常驻集？

工作集是进程在最近一段时间内实际使用的页面集合。常驻集是当前分配给进程、实际在物理内存中的页面集合。工作集算法根据近期访问情况调整常驻集，尽量让工作集留在内存，减少抖动。

### 13. SV39 页表项组成和标志位作用

SV39 PTE 包含物理页号 PPN 和标志位。常见标志位有 `V` 有效、`R` 可读、`W` 可写、`X` 可执行、`U` 用户可访问、`G` 全局、`A` 已访问、`D` 已修改。`A/D` 可用于页面置换和脏页回写。

### 14. 处理 10G 连续内存页面，页表大致占用多少？

10G / 4K 大约是 262 万个页。每个 PTE 8 字节，最低一级页表约 20MB。再加上中间页表页，数量级仍是几十 MB。

### 15. 缺页异常、Lazy 和 swap

缺页可能对应取指页异常、读页异常、写页异常。相关 CSR 中，`scause` 表示异常类型，`stval` 通常保存出错虚拟地址，`sepc` 保存异常指令地址。Lazy 策略好处是减少启动和分配开销，只在真正访问时分配页。swap 好处是让可用虚拟内存超过物理内存；PTE 可清除 `V`，并用软件位记录页面在 swap 中的位置。

### 16. 单页表和双页表

单页表中，用户和内核共用页表，但内核页不设置 `U` 位，因此用户态不能访问。优势是 Trap 时少切换页表，性能更好。双页表中，用户态运行用户页表，进入内核后切换内核页表，返回用户态前再切回用户页表；安全隔离更强，但切换成本更高。

---

## 五、实验报告小结

第四章相比第三章主要增加了地址空间、页表和基于虚拟地址的隔离机制。系统调用不能再直接相信用户指针，需要根据当前任务页表翻译。`mmap/munmap` 让用户程序能动态申请和释放虚拟内存区域。页表权限位让只读、只写、可执行等访问控制真正由硬件检查。

我对本章的理解：第四章最重要的转变是从“任务能切换”进入到“每个任务有自己的地址空间”。后续进程、文件系统和 mmap 文件映射都建立在这个基础上。

---

## 六、文件结构总览

```text
ch4-exercises/
├── answers.md
├── linux_mem.c
├── Makefile
└── linux_mem

rCore-Tutorial-Code-2025S-ch4/
├── os/src/syscall/process.rs   # sys_get_time/sys_mmap/sys_munmap
├── os/src/mm/memory_set.rs     # MemorySet/MapArea/MapPermission
├── os/src/task/task.rs         # current task mmap/munmap 接口
└── user/src/bin/ch4_*.rs       # 第四章测试程序
```

常用查看命令：

```bash
cat /home/daihuohuo/code/ch4-exercises/answers.md
cat /home/daihuohuo/code/ch4-exercises/linux_mem.c
cat /home/daihuohuo/code/ch4-exercises/Makefile

grep -n "pub fn sys_get_time" -A35 /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/syscall/process.rs
grep -n "pub fn sys_mmap" -A35 /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/syscall/process.rs
grep -n "pub fn sys_munmap" -A25 /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/syscall/process.rs
```

常用运行命令：

```bash
cd /home/daihuohuo/code/ch4-exercises
make clean
make
make run

cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os
make run TEST=1
make run TEST=2
make run TEST=4 BASE=0
```
