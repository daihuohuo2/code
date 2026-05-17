# rCore 第四章练习完成稿

## 一、编程题完成情况

### 1. 实验环境

跑在 WSL 里的 Ubuntu 24.04 上：
- 实验目录：`/home/daihuohuo/code/ch4-exercises`
- rCore 第四章工程：`/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4`
- Rust 编译目标：`riscv64gc-unknown-none-elf`
- 用 QEMU 模拟 RISC-V 硬件，`-bios default -kernel` 方式启动

本章需要的配置命令：

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

如果 `cargo install cargo-binutils` 已经装过，会提示已存在；不影响后续实验。

### 2. 课后编程题 1：Linux 内存相关系统调用示例

在 Linux 下写一个 C 程序，把 `sbrk`、`mmap`、`munmap`、`mprotect` 这几个内存相关系统调用都演示一遍，对照理解 rCore 里同类机制的作用。

相关文件：
- `/home/daihuohuo/code/ch4-exercises/linux_mem.c`
- `/home/daihuohuo/code/ch4-exercises/Makefile`

怎么跑：

```bash
cd /home/daihuohuo/code/ch4-exercises
make clean
make
make run
```

可以用下面命令直接看代码：

```bash
cat /home/daihuohuo/code/ch4-exercises/linux_mem.c
cat /home/daihuohuo/code/ch4-exercises/Makefile
```

`linux_mem.c` 代码如下：

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <errno.h>

/* Demo of sbrk / mmap / munmap / mprotect */

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

`Makefile` 代码如下：

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

实现思路：
- `sbrk(0)` 先读当前堆顶地址，`sbrk(4096)` 把堆扩大一页，然后往里写数据读回来验证。
- `mmap` 用 `MAP_PRIVATE | MAP_ANONYMOUS` 申请两页匿名内存，读写验证后用 `munmap` 还回去。
- `mprotect` 先把页面改成只读，确认仍然能读；再改回读写，确认可以继续写。

### 3. 实验练习 1：重写 `sys_get_time`

第三章里内核和用户共用同一块物理内存，`*ts = time` 直接写就能把时间交给用户。第四章开启了页表隔离，用户传来的指针是**用户虚拟地址**，内核不能直接当物理地址写，否则会写到错误的地方。所以要先通过当前任务的页表翻译成内核能访问的地址，再写进去。

改动的文件：
- `/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/syscall/process.rs`

查看代码：

```bash
grep -n "pub fn sys_get_time" -A35 /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/syscall/process.rs
```

关键代码：

```rust
pub fn sys_get_time(_ts: *mut TimeVal, _tz: usize) -> isize {
    trace!("kernel: sys_get_time");
    let us = get_time_us();
    // 先在内核栈上构造好 TimeVal，分秒和微秒部分分开存
    let time = TimeVal {
        sec: us / MICRO_PER_SEC,
        usec: us % MICRO_PER_SEC,
    };
    // 把 TimeVal 结构体视作字节切片，方便后面分段拷贝
    let bytes = unsafe {
        core::slice::from_raw_parts(
            (&time as *const TimeVal).cast::<u8>(),
            core::mem::size_of::<TimeVal>(),
        )
    };
    // 关键：通过当前任务的页表，把用户虚拟地址翻译成内核可访问的缓冲区列表
    // TimeVal 可能跨两个页，所以返回的是 Vec<&mut [u8]>
    let Some(buffers) = translated_byte_buffer_checked(
        current_user_token(),
        _ts.cast::<u8>(),
        core::mem::size_of::<TimeVal>(),
    ) else {
        return -1; // 用户传的指针非法，直接拒绝
    };
    // 分段把 TimeVal 字节拷贝进用户内存
    let mut copied = 0;
    for buffer in buffers {
        let end = copied + buffer.len();
        buffer.copy_from_slice(&bytes[copied..end]);
        copied = end;
    }
    0
}
```

实现思路：
1. 用 `get_time_us()` 取得当前微秒数，拆成秒和微秒两部分，组成 `TimeVal`。
2. 把这个 `TimeVal` 在内核栈上构造好，转成字节切片准备拷贝。
3. 用 `translated_byte_buffer_checked` 查当前任务页表，把用户虚拟地址翻译成内核能访问的物理地址缓冲区列表（一个 `TimeVal` 大小是 16 字节，可能刚好跨在两个页的边界，所以要分段处理）。
4. 逐段把字节拷贝进用户内存。
5. 用户地址非法或页面未映射时，返回 `-1`。

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os
make run TEST=3 BASE=0
```

测试输出中应能看到类似内容：

```text
get_time OK! 22
Test sleep OK!
```

### 4. 实验练习 2：实现 `mmap`

实现匿名内存映射（syscall ID = 222）：把虚拟地址区间 `[start, start + len)` 映射到新分配的物理页，按 `prot` 参数设置读/写/执行权限。

改动的文件：
- `os/src/syscall/process.rs`
- `os/src/mm/memory_set.rs`
- `os/src/task/task.rs`
- `os/src/task/mod.rs`

**系统调用实现（syscall/process.rs）：**

```rust
pub fn sys_mmap(_start: usize, _len: usize, _port: usize) -> isize {
    // 1. 地址必须页对齐（4KB 对齐），否则拒绝
    if !VirtAddr::from(_start).aligned() { return -1; }
    // 2. port 只能用低 3 位，且不能全 0（至少要有一种权限）
    if _port & !0x7 != 0 || (_port & 0x7) == 0 { return -1; }
    if _len == 0 { return 0; }
    // 3. len 向上取整到页大小
    let len = (_len + PAGE_SIZE - 1) / PAGE_SIZE * PAGE_SIZE;
    // 4. 防止 start + len 整数溢出
    if _start.checked_add(len).is_none() { return -1; }
    // 5. 把用户的 prot 标志位转成内核的 MapPermission，并加上 U 权限
    let mut permission = MapPermission::U;
    if _port & 0x1 != 0 { permission |= MapPermission::R; }
    if _port & 0x2 != 0 { permission |= MapPermission::W; }
    if _port & 0x4 != 0 { permission |= MapPermission::X; }
    // 6. 检查区间是否已经有映射，没有则建立 Framed 映射（每页分配新物理帧）
    if current_mmap(_start, len, permission) { 0 } else { -1 }
}
```

**地址空间层检查（mm/memory_set.rs）：**

```rust
pub fn insert_framed_area_checked(
    &mut self,
    start_va: VirtAddr,
    end_va: VirtAddr,
    permission: MapPermission,
) -> bool {
    let start_vpn = start_va.floor();
    let end_vpn = end_va.ceil();
    // 遍历区间内每个虚拟页号，如果已经有 PTE 就拒绝（不允许重叠映射）
    for vpn in VPNRange::new(start_vpn, end_vpn) {
        if self.translate(vpn).is_some() { return false; }
    }
    // 插入新的 MapArea 并立即分配物理页帧建立映射
    self.push(MapArea::new(start_va, end_va, MapType::Framed, permission), None);
    true
}
```

**任务接口（task/task.rs）：**

```rust
pub fn mmap(&mut self, start: usize, len: usize, permission: MapPermission) -> bool {
    self.memory_set.insert_framed_area_checked(
        VirtAddr(start),
        VirtAddr(start + len),
        permission,
    )
}
```

实现思路：先检查参数合法性（对齐、权限位不能为 0、长度不溢出），然后把用户的 prot 标志转成内核权限标志，调用 `MemorySet` 层检查区间是否已有映射，没有冲突就建立 `Framed` 映射（每个虚拟页分配一个独立物理页帧）。

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os
make run TEST=4 BASE=0
```

测试输出中应能看到：

```text
Test 04_1 OK!
[kernel] PageFault in application, bad addr = 0x10000000, ...
[kernel] PageFault in application, bad addr = 0x10000000, ...
Test 04_4 test OK!
```

其中两个 `PageFault` 是预期现象：
- `ch4_mmap1` 映射只读页后写入，应被内核杀死。
- `ch4_mmap2` 映射只写页后读取，由于 RISC-V 不允许 `W=1,R=0` 的普通可读语义，也会触发异常。

### 5. 实验练习 3：实现 `munmap`

解除内存映射（syscall ID = 215）：取消虚拟地址区间 `[start, start + len)` 的映射，把物理页帧归还给系统。

**系统调用实现（syscall/process.rs）：**

```rust
pub fn sys_munmap(_start: usize, _len: usize) -> isize {
    if !VirtAddr::from(_start).aligned() { return -1; }
    if _len == 0 { return 0; }
    let len = (_len + PAGE_SIZE - 1) / PAGE_SIZE * PAGE_SIZE;
    if _start.checked_add(len).is_none() { return -1; }
    if current_munmap(_start, len) { 0 } else { -1 }
}
```

**地址空间解除映射（mm/memory_set.rs）：**

```rust
pub fn remove_framed_area(&mut self, start_va: VirtAddr, end_va: VirtAddr) -> bool {
    let start_vpn = start_va.floor();
    let end_vpn = end_va.ceil();
    // 检查区间内每个页都已经映射，没映射的话说明参数有误
    for vpn in VPNRange::new(start_vpn, end_vpn) {
        if self.translate(vpn).is_none() { return false; }
    }
    // 找到对应的 MapArea（要求完整匹配，不允许解除半个区域）
    if let Some(index) = self.areas.iter().position(|area| {
        area.vpn_range.get_start() == start_vpn && area.vpn_range.get_end() == end_vpn
    }) {
        let mut area = self.areas.remove(index);
        area.unmap(&mut self.page_table); // 逐页删除 PTE，释放物理帧
        true
    } else {
        false
    }
}
```

**任务接口（task/task.rs）：**

```rust
pub fn munmap(&mut self, start: usize, len: usize) -> bool {
    self.memory_set.remove_framed_area(VirtAddr(start), VirtAddr(start + len))
}
```

实现思路：参数检查和 mmap 类似。核心是从 `areas` 列表里找到完全匹配（起止虚拟页号都对上）的 `MapArea`，找到后调 `unmap` 逐页删掉页表项，`FrameTracker` 被 drop 时自动把物理页帧还给分配器。

运行命令：
    }
    if let Some(index) = self.areas.iter().position(|area| {
        area.vpn_range.get_start() == start_vpn && area.vpn_range.get_end() == end_vpn
    }) {
        let mut area = self.areas.remove(index);
        area.unmap(&mut self.page_table);
        true
    } else {
        false
    }
}
```

### 6. 第四章完整验证

我已在 WSL 下执行：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os
timeout 120 make run TEST=4 BASE=0
```

关键输出：

```text
get_time OK! 22
Test 04_1 OK!
[kernel] PageFault in application, bad addr = 0x10000000, bad instruction = 0x42e, kernel killed it.
[kernel] PageFault in application, bad addr = 0x10000000, bad instruction = 0x42c, kernel killed it.
Test 04_4 test OK!
Test trace_1 OK!
Test 04_5 ummap OK!
Test 04_6 ummap2 OK!
Test sleep1 passed!
Test trace OK!
Test sleep OK!
```

说明：构建时出现的 `static_mut_refs`、`unused import` 等 warning 来自后续章节用户程序，不影响第四章练习通过。

## 二、课后编程题扩展说明

第四章课后编程题 2 到 6 是扩展题，下面给出每道题的核心实现代码和思路。

### 1. 单页表机制

把内核映射和用户映射放在同一张页表里。内核页不设置 `U` 权限位，所以用户态即使"看到"内核虚拟地址，也会被硬件挡掉。好处是 Trap 时不用切页表，省掉了 `sfence.vma` 的开销。

**核心改动（memory_set.rs）：**

```rust
// 在构建用户地址空间时，把内核代码/数据也映射进来，但不加 U 位
// 内核代码段：只读可执行
memory_set.push(
    MapArea::new(
        (stext as usize).into(),
        (etext as usize).into(),
        MapType::Identical,
        MapPermission::R | MapPermission::X, // 没有 U，用户态无法访问
    ),
    None,
);
// 内核数据段：只读
memory_set.push(
    MapArea::new(
        (srodata as usize).into(),
        (erodata as usize).into(),
        MapType::Identical,
        MapPermission::R,
    ),
    None,
);
// 内核可读写数据段
memory_set.push(
    MapArea::new(
        (sdata as usize).into(),
        (edata as usize).into(),
        MapType::Identical,
        MapPermission::R | MapPermission::W,
    ),
    None,
);
```

**Trap 路径简化（trap.S）：**
```asm
# 单页表下不需要切换 satp，Trap 进内核后直接用当前页表
# 只需要切换到内核栈，保存上下文即可
__alltraps:
    csrrw sp, sscratch, sp   # 切换到内核栈（sscratch 存着内核栈顶）
    # 保存通用寄存器、sstatus、sepc...（和双页表版本一致）
    # 关键区别：不需要 csrw satp, ... / sfence.vma
    call trap_handler
```

### 2. Lazy 按需分页

`mmap` 或堆扩大时只记录虚拟地址区间，先不分配物理页。用户第一次访问某页时触发缺页异常，缺页处理函数再去分配物理页并建立映射，然后让用户重试刚才的指令。

**缺页处理（trap/mod.rs）：**

```rust
// Trap handler 里处理 LoadPageFault / StorePageFault
Trap::Exception(Exception::LoadPageFault)
| Trap::Exception(Exception::StorePageFault) => {
    let fault_va = VirtAddr(stval::read());
    let task = current_task().unwrap();
    let mut inner = task.inner_exclusive_access();
    if handle_lazy_page_fault(&mut inner.memory_set, fault_va) {
        // 合法的 lazy 区间，补完页后返回用户态重试
    } else {
        // 非法访问，杀死进程
        inner.task_status = TaskStatus::Zombie;
    }
}
```

**懒加载处理函数（mm/memory_set.rs）：**

```rust
pub fn handle_lazy_page_fault(memory_set: &mut MemorySet, fault_va: VirtAddr) -> bool {
    // 找到包含 fault_va 的 lazy MapArea
    if let Some(area) = memory_set.find_lazy_area_mut(fault_va) {
        let vpn = fault_va.floor();
        // 现在才真正分配物理页并建立 PTE
        area.map_one(&mut memory_set.page_table, vpn);
        true
    } else {
        false // 不在任何合法区间里，是真正的非法访问
    }
}
```

### 3. COW 写时复制

`fork` 时不复制物理页，父子进程共享同一批物理页，只把页表里的 `W` 位清掉，并打上软件 COW 标记。谁先写就触发 `StorePageFault`，缺页处理时给它分配新页、拷贝旧页内容、恢复 `W` 权限。

**COW 缺页处理（trap/mod.rs）：**

```rust
Trap::Exception(Exception::StorePageFault) => {
    let fault_va = VirtAddr(stval::read());
    let vpn = fault_va.floor();
    let task = current_task().unwrap();
    let mut inner = task.inner_exclusive_access();
    let pte = inner.memory_set.translate(vpn).unwrap();

    if pte.is_cow() {
        // 1. 分配一个新的物理页帧
        let new_frame = frame_alloc().unwrap();
        // 2. 把旧物理页的内容原样拷到新页
        let old_ppn = pte.ppn();
        new_frame.ppn.get_bytes_array()
            .copy_from_slice(old_ppn.get_bytes_array());
        // 3. 更新页表：指向新物理页，并恢复 W 权限，清除 COW 标记
        let flags = pte.flags() | PTEFlags::W & !PTEFlags::COW;
        inner.memory_set.page_table.update(vpn, new_frame.ppn, flags);
        // 引用计数减一（如果旧页没有其他引用，会被自动释放）
    } else {
        // 不是 COW 页的写异常：真正的非法访问
        inner.task_status = TaskStatus::Zombie;
    }
}
```

### 4. Swap in/out 与 Clock 置换

物理内存不够时，Clock 算法把访问位为 0 的页面换到磁盘上，等到再次访问触发缺页时从磁盘读回。

**Clock 换出算法（mm/frame_allocator.rs）：**

```rust
// Clock 算法找一个可换出的页
fn clock_evict(clock_queue: &mut VecDeque<PageMeta>) -> PageMeta {
    loop {
        let page = clock_queue.front_mut().unwrap();
        if page.accessed {
            // 近期访问过，给它第二次机会，清除访问位继续转圈
            page.accessed = false;
            clock_queue.rotate_left(1);
        } else {
            // 找到了：访问位为 0，可以换出
            let evicted = clock_queue.pop_front().unwrap();
            swap_out(&evicted); // 写入 swap 分区
            return evicted;
        }
    }
}
```

**缺页时换入（trap/mod.rs）：**

```rust
// 查页表，发现 Valid=0 但有 swap slot 号
if let Some(slot) = pte.swap_slot() {
    let new_frame = frame_alloc().unwrap();
    swap_in(slot, new_frame.ppn); // 从 swap 分区读回内容
    // 重建 PTE，恢复 Valid 位，释放 swap slot
    page_table.map(vpn, new_frame.ppn, flags | PTEFlags::V);
}
```

### 5. 自映射（Recursive Mapping）

让顶级页表的第 510 项指向顶级页表自身。这样内核就能用固定的虚拟地址公式访问当前页表的任意 PTE，不需要额外的物理地址映射。

**建立自映射（mm/page_table.rs）：**

```rust
const RECURSIVE_INDEX: usize = 510; // SV39 顶级页表的第 510 项

pub fn setup_recursive_mapping(root_ppn: PhysPageNum, root_table: &mut PageTable) {
    // 让第 510 项指向顶级页表自己，形成"镜子"
    root_table.entries[RECURSIVE_INDEX] =
        PageTableEntry::new(root_ppn, PTEFlags::V);
    // 之后内核就能用公式：
    // VPN[2]=510, VPN[1]=510, VPN[0]=vpn2 → 访问三级页表页
    // VPN[2]=510, VPN[1]=vpn2, VPN[0]=vpn1 → 访问二级页表页
    // VPN[2]=vpn2, VPN[1]=vpn1, VPN[0]=vpn0 → 访问数据页
}
```

## 三、问答题参考答案

### 1. 随机访问不在当前程序逻辑地址范围内的地址会发生什么？

如果用户程序读写一个没有映射到当前地址空间的虚拟地址，CPU 地址转换会失败并触发缺页异常；如果该地址有映射但权限不满足，例如写只读页，也会触发 page fault。异常进入内核后，内核会判断这个异常能否修复：如果是合法的 lazy allocation 或 COW，可以补页后返回用户态继续执行；如果是非法访问，通常杀死当前进程。

在 Linux 下常见表现是 `Segmentation fault`；在本章 rCore 测试中，可以看到内核输出 `PageFault in application ... kernel killed it.`

### 2. 用户程序运行时看到的是逻辑地址还是物理地址？

用户程序看到的是逻辑地址，也就是虚拟地址。程序中的指针值、函数地址、栈地址、堆地址都是虚拟地址。CPU 通过页表把虚拟地址翻译成物理地址，应用程序通常不能直接知道真实物理地址。

### 3. 单页表情况下，如何控制用户态无法访问内核页面？

单页表可以同时映射用户页面和内核页面，但内核页面的页表项不能设置 `U` 位。RISC-V 的分页权限检查会阻止 U-mode 访问没有 `U` 权限的页面。也就是说，用户态虽然和内核态共用页表，但硬件权限位仍然提供隔离。

同时还要正确设置 `R/W/X` 权限，例如内核代码页只读可执行，内核只读数据页不可写，内核数据页不可执行。

### 4. 相对于双页表，单页表有何优势？

单页表最大的优势是减少 Trap 进入和返回时的页表切换成本。双页表模式下，从用户态进入内核态后通常要切换到内核页表，返回用户态前再切回用户页表，并执行 `sfence.vma` 刷新地址转换缓存。单页表模式下，内核映射已经在当前页表中，Trap 路径可以更短。

代价是安全边界更依赖 PTE 权限配置：只要某个内核页错误设置了 `U` 位，就可能被用户态访问。

### 5. 单页表和双页表分别在什么时候切换页表？

双页表模式：
- 用户态运行时使用用户页表。
- 发生 Trap 后，跳板代码先保存必要上下文，然后切换到内核页表。
- 内核处理完成后，返回用户态前切回该任务的用户页表。
- 切换页表通常通过写 `satp`，然后执行 `sfence.vma`。

单页表模式：
- 用户态和内核态使用同一张页表。
- Trap 进入内核时通常不需要切换页表，只需要切换特权级、栈和上下文。
- 任务切换时仍然需要切换到下一个任务对应的页表，因为不同任务的用户地址空间不同。

## 四、实验报告小结

本章相对第三章新增了基于 Sv39 的地址空间、页表映射、用户地址翻译和页面权限检查。系统调用不能再直接访问用户指针，而要先通过当前任务页表转换。`mmap/munmap` 的实现把用户虚拟地址区间、物理页帧分配和 `MapPermission` 权限连接起来。测试中只读/只写非法访问能触发 page fault，说明页表权限生效。

我对本次实验的感受：难点不在写几行 syscall 分发，而在“用户传来的地址不是内核能直接用的地址”这个观念转换。把 `TimeVal` 跨页拷贝和 `mmap` 区间冲突检查做好后，第四章的地址空间模型就清晰很多。

## 五、文件位置

本次整理文件位于：

```text
/home/daihuohuo/code/ch4-exercises
```

其中包括：
- `answers.md`
- `linux_mem.c`
- `Makefile`
- 编译后生成的 `linux_mem`

本次 rCore 第四章工程位于：

```text
/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4
```

核心代码可用以下命令查看：

```bash
cat /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/syscall/process.rs
cat /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/mm/memory_set.rs
cat /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/task/task.rs
cat /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch4/os/src/task/mod.rs
```
