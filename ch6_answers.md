# rCore 第六章练习完成稿

## 一、编程题完成情况

### 1. 实验环境

实验环境：
- 操作系统：Ubuntu 24.04 on WSL
- 实验目录：`/home/daihuohuo/code/ch6-exercises`
- rCore 第六章工程：`/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6`
- Rust 目标平台：`riscv64gc-unknown-none-elf`
- QEMU 启动方式：`-bios default -kernel`

本章需要的配置命令：

```bash
cd /home/daihuohuo/code
mkdir -p ch6-exercises

# 如果第六章工程目录还不存在，先从已有 rCore 仓库创建 ch6 worktree
git -C /home/daihuohuo/code/rCore-Tutorial-Code-2025S worktree add \
  /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6 origin/ch6

# 这个 ch6 分支只带 os/easy-fs；如果没有 user 目录，就从 ch5 复制一份用户程序
cp -a /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch5/user \
  /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/user

rustup target add riscv64gc-unknown-none-elf
cargo install cargo-binutils
rustup component add rust-src
rustup component add llvm-tools-preview

sudo apt update
sudo apt install -y build-essential qemu-system-misc
```

如果 `cargo install cargo-binutils` 已经安装过，会提示已存在，不影响后续实验。
如果 `rCore-Tutorial-Code-2025S-ch6` 目录已经存在，`git worktree add` 会提示路径已存在，这一步可以直接跳过。
如果 `rCore-Tutorial-Code-2025S-ch6/user` 已经存在，复制 user 目录这一步也可以跳过。

### 2. 课后编程题 1：扩大单个文件大小，支持三重间接 inode

扩展 easy-fs，在 DiskInode 里加一个 `indirect3` 字段，让单个文件可以通过三级索引访问更大的空间。

**改动文件**：`easy-fs/src/layout.rs`、`easy-fs/src/vfs.rs`

**核心代码：**

```rust
const INODE_DIRECT_COUNT: usize = 28;
const BLOCK_SZ: usize = 512;
const INODE_INDIRECT_COUNT: usize = BLOCK_SZ / 4;
const INODE_DOUBLE_INDIRECT_COUNT: usize = INODE_INDIRECT_COUNT * INODE_INDIRECT_COUNT;
const INODE_TRIPLE_INDIRECT_COUNT: usize =
    INODE_DOUBLE_INDIRECT_COUNT * INODE_INDIRECT_COUNT;

#[repr(C)]
pub struct DiskInode {
    pub size: u32,
    pub direct: [u32; INODE_DIRECT_COUNT],
    pub indirect1: u32,
    pub indirect2: u32,
    pub indirect3: u32,
    pub type_: DiskInodeType,
}

impl DiskInode {
    pub fn get_block_id(&self, inner_id: u32, block_device: &Arc<dyn BlockDevice>) -> u32 {
        let inner_id = inner_id as usize;
        if inner_id < INODE_DIRECT_COUNT {
            return self.direct[inner_id];
        }
        let inner_id = inner_id - INODE_DIRECT_COUNT;
        if inner_id < INODE_INDIRECT_COUNT {
            return get_block_cache(self.indirect1 as usize, Arc::clone(block_device))
                .lock()
                .read(0, |indirect_block: &IndirectBlock| indirect_block[inner_id]);
        }
        let inner_id = inner_id - INODE_INDIRECT_COUNT;
        if inner_id < INODE_DOUBLE_INDIRECT_COUNT {
            let first = inner_id / INODE_INDIRECT_COUNT;
            let second = inner_id % INODE_INDIRECT_COUNT;
            let indirect1 = get_block_cache(self.indirect2 as usize, Arc::clone(block_device))
                .lock()
                .read(0, |indirect_block: &IndirectBlock| indirect_block[first]);
            return get_block_cache(indirect1 as usize, Arc::clone(block_device))
                .lock()
                .read(0, |indirect_block: &IndirectBlock| indirect_block[second]);
        }
        let inner_id = inner_id - INODE_DOUBLE_INDIRECT_COUNT;
        let first = inner_id / INODE_DOUBLE_INDIRECT_COUNT;
        let rest = inner_id % INODE_DOUBLE_INDIRECT_COUNT;
        let second = rest / INODE_INDIRECT_COUNT;
        let third = rest % INODE_INDIRECT_COUNT;
        let indirect2 = get_block_cache(self.indirect3 as usize, Arc::clone(block_device))
            .lock()
            .read(0, |indirect_block: &IndirectBlock| indirect_block[first]);
        let indirect1 = get_block_cache(indirect2 as usize, Arc::clone(block_device))
            .lock()
            .read(0, |indirect_block: &IndirectBlock| indirect_block[second]);
        get_block_cache(indirect1 as usize, Arc::clone(block_device))
            .lock()
            .read(0, |indirect_block: &IndirectBlock| indirect_block[third])
    }
}
```

实现思路：先算出每个索引块能放多少个 `u32` 块号（512/4 = 128），然后按直接块 → 一级间接 → 二级间接 → 三级间接的顺序查找。扩容和回收时同步分配/释放对应的索引块。

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/easy-fs
cargo test
cd ../os
make run TEST=6 BASE=1
```

### 3. 课后编程题 2：支持 `stat/fstat` 系统调用

查询文件元数据 `stat/fstat`：通过 fd 拿到文件类型、inode 编号、硬链接数。

**改动文件**：`os/src/syscall/fs.rs`、`os/src/fs/inode.rs`

**核心结构和实现：**

```rust
bitflags! {
    pub struct StatMode: u32 {
        const NULL = 0;
        const DIR  = 0o040000;
        const FILE = 0o100000;
    }
}

#[repr(C)]
pub struct Stat {
    pub dev: u64,
    pub ino: u64,
    pub mode: StatMode,
    pub nlink: u32,
    pad: [u64; 7],
}
```

内核实现示例：

```rust
pub fn sys_fstat(fd: usize, st: *mut Stat) -> isize {
    let task = current_task().unwrap();
    let inner = task.inner_exclusive_access();
    if fd >= inner.fd_table.len() {
        return -1;
    }
    let Some(file) = &inner.fd_table[fd] else {
        return -1;
    };
    let stat = file.stat();
    drop(inner);
    copy_to_user(current_user_token(), st, &stat)
}
```

实现思路：用户态和内核态定义一致的 `Stat` 结构，文件对象加 `stat()` 接口，`OSInode::stat()` 从 easy-fs inode 取元数据，`sys_fstat` 根据 fd 找到打开的文件对象，最后把 `Stat` 复制回用户空间。

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/os
make run TEST=6 BASE=1
```

预期输出里应包含 `ch6_file*` 或 `ch6_usertest` 相关测试通过信息。

### 4. 课后编程题 3：支持 `mmap` 文件映射

把文件内容映射到用户虚拟地址，用户直接通过内存指针读写文件。

**改动文件**：`os/src/mm/memory_set.rs`、`os/src/trap/mod.rs`、`os/src/syscall/process.rs`

**核心结构和缺页处理：**

```rust
pub enum MapType {
    Identical,
    Framed,
    File {
        file: Arc<dyn File + Send + Sync>,
        offset: usize,
    },
}
```

缺页处理示例：

```rust
pub fn handle_file_page_fault(
    memory_set: &mut MemorySet,
    fault_va: VirtAddr,
) -> Result<(), ()> {
    let area = memory_set.find_area(fault_va).ok_or(())?;
    if let MapType::File { file, offset } = &area.map_type {
        let frame = frame_alloc().ok_or(())?;
        let page_offset = fault_va.floor().0 - area.vpn_range.get_start().0;
        let file_offset = offset + page_offset * PAGE_SIZE;
        let buf = frame.ppn.get_bytes_array();
        file.read_at(file_offset, buf);
        memory_set.map_one_existing(fault_va.floor(), frame, area.map_perm);
        Ok(())
    } else {
        Err(())
    }
}
```

实现思路：`mmap` 时只建 VMA（记录来源文件和偏移），不立即读文件；用户第一次访问时触发 page fault，缺页处理函数分配物理页并把文件对应内容读入，然后建立 PTE 让用户重试。

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/os
make run TEST=6 BASE=1
```

### 5. 课后编程题 4：支持二级目录结构

扩展 easy-fs 支持 `/dir/file` 形式的路径，按 `/` 分段逐级查找目录项。

**改动文件**：`easy-fs/src/vfs.rs`、`os/src/fs/inode.rs`、`os/src/syscall/fs.rs`

**路径解析和创建：**

```rust
pub fn find_path(root: Arc<Inode>, path: &str) -> Option<Arc<Inode>> {
    let mut current = root;
    for name in path.split('/').filter(|name| !name.is_empty()) {
        current = current.find(name)?;
    }
    Some(current)
}
```

创建文件示例：

```rust
pub fn create_path(root: Arc<Inode>, path: &str) -> Option<Arc<Inode>> {
    let mut parts = path.rsplitn(2, '/');
    let name = parts.next()?;
    let parent_path = parts.next().unwrap_or("/");
    let parent = find_path(root, parent_path)?;
    parent.create(name)
}
```

实现思路：目录文件内容就是目录项数组，从根目录按 `/` 逐级查找；创建文件时先定位父目录，再在父目录中插入新目录项。

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/os
make run TEST=6 BASE=1
```

测试建议：
- 创建 `/dir/a.txt`。
- 创建 `/dir/b.txt`。
- 读写 `/dir/a.txt`。
- 删除 `/dir/a.txt` 后确认 `/dir/b.txt` 仍可访问。

### 6. 课后编程题 5：通过日志机制支持 crash 一致性

在文件系统里加入日志机制，用「先写日志再改数据」的方式保证崩溃后能恢复到一致状态。

**改动文件**：`easy-fs/src/efs.rs`、`easy-fs/src/block_cache.rs`

**日志结构和提交流程：**

```rust
#[repr(C)]
pub struct JournalHeader {
    pub magic: u32,
    pub committed: u32,
    pub block_count: u32,
    pub blocks: [u32; 32],
}

pub struct Journal {
    start_block: u32,
    header: JournalHeader,
}
```

提交流程：

```rust
pub fn commit_transaction(journal: &mut Journal, modified_blocks: &[u32]) {
    journal.write_data_blocks(modified_blocks);
    journal.write_header(false);
    journal.flush();
    journal.header.committed = 1;
    journal.write_header(true);
    journal.flush();
    journal.install_to_home_locations();
    journal.clear();
}
```

实现思路：先写日志数据块，再写 commit 标记；commit 成功后把日志里的块安装回真实位置。崩溃重启时，有完整 commit 的就重放，没有的就丢弃。可以在写入中途手动 panic 来模拟崩溃，重启后检查 inode/位图/目录项是否一致。

运行命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/easy-fs
cargo test
```

### 7. Linux 文件系统示例程序

演示 Linux 下 `open/write/link/unlink/stat/fstat` 的完整流程，方便和 rCore 的 ch6 实现对比。

相关文件：`file_link_demo.c`、`Makefile`

运行命令：
`file_link_demo.c` 代码如下：

```c
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
```

`Makefile` 代码如下：

```makefile
CC := gcc
CFLAGS := -Wall -Wextra -O2 -std=c11

.PHONY: all clean run

all: file_link_demo

file_link_demo: file_link_demo.c
	$(CC) $(CFLAGS) -o $@ $<

run: file_link_demo
	./file_link_demo

clean:
	rm -f file_link_demo ch6_origin.txt ch6_hardlink.txt
```

## 二、实验练习完成情况

第六章实验主线是 `linkat`、`unlinkat`、`fstat` 三个系统调用。

### 1. 实现 `linkat`

让两个文件名指向同一个 inode，并增加硬链接计数。

**核心实现：**

```rust
pub fn sys_linkat(
    old_dirfd: isize,
    old_path: *const u8,
    new_dirfd: isize,
    new_path: *const u8,
    flags: usize,
) -> isize {
    if flags != 0 || old_dirfd != AT_FDCWD || new_dirfd != AT_FDCWD {
        return -1;
    }
    let token = current_user_token();
    let old_path = translated_str(token, old_path);
    let new_path = translated_str(token, new_path);
    if old_path == new_path {
        return -1;
    }
    if open_file(new_path.as_str(), OpenFlags::RDONLY).is_some() {
        return -1;
    }
    ROOT_INODE.link(old_path.as_str(), new_path.as_str())
}
```

easy-fs 层示例：

```rust
pub fn link(&self, old_name: &str, new_name: &str) -> isize {
    let old_inode_id = match self.find_inode_id(old_name) {
        Some(id) => id,
        None => return -1,
    };
    if self.find_inode_id(new_name).is_some() {
        return -1;
    }
    self.modify_disk_inode(|root_inode| {
        let file_count = (root_inode.size as usize) / DIRENT_SZ;
        let new_size = (file_count + 1) * DIRENT_SZ;
        self.increase_size(new_size as u32, root_inode, &mut self.fs.lock());
        let dirent = DirEntry::new(new_name, old_inode_id);
        root_inode.write_at(file_count * DIRENT_SZ, dirent.as_bytes(), &self.block_device);
    });
    self.modify_inode(old_inode_id, |inode| {
        inode.nlink += 1;
    });
    0
}
```

### 2. 实现 `unlinkat`

删除目录项，减少硬链接计数。只有 `nlink == 0` 时才真正释放 inode 和数据块。

**核心实现：**
```

核心实现示例：

```rust
pub fn sys_unlinkat(dirfd: isize, path: *const u8, flags: usize) -> isize {
    if flags != 0 || dirfd != AT_FDCWD {
        return -1;
    }
    let token = current_user_token();
    let path = translated_str(token, path);
    ROOT_INODE.unlink(path.as_str())
}
```

easy-fs 层示例：

```rust
pub fn unlink(&self, name: &str) -> isize {
    let inode_id = match self.find_inode_id(name) {
        Some(id) => id,
        None => return -1,
    };
    self.remove_dirent(name);
    let nlink = self.modify_inode(inode_id, |inode| {
        inode.nlink -= 1;
        inode.nlink
    });
    if nlink == 0 {
        self.clear_inode(inode_id);
    }
    0
}
```

### 3. 实现 `fstat`

通过 fd 查询文件状态。

**核心实现：**

```rust
pub fn sys_fstat(fd: usize, st: *mut Stat) -> isize {
    let task = current_task().unwrap();
    let inner = task.inner_exclusive_access();
    if fd >= inner.fd_table.len() {
        return -1;
    }
    let Some(file) = &inner.fd_table[fd] else {
        return -1;
    };
    let stat = file.stat();
    drop(inner);
    translated_refmut(current_user_token(), st).write(stat);
    0
}
```

复现命令：

```bash
cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/os
make run TEST=6 BASE=1
```

预期输出：

```text
link/unlink/fstat related tests passed
ch6_usertest passed
```

## 三、问答题参考答案

### 1. 文件系统的功能是什么？

文件系统负责把块设备上的原始块组织成文件、目录、链接和元数据等抽象，并提供命名、持久化、空间分配、权限控制和一致性维护。

### 2. 如何支持多级目录？

目录本身也是一种文件，内容是目录项。每个目录项保存“名字 -> inode”的映射。路径解析时从根目录或当前目录出发，按 `/` 分段逐级查找，直到找到目标文件或目录。

### 3. 软链接和硬链接的区别是什么？删除时会怎样？

硬链接是多个目录项指向同一个 inode，删除一个硬链接只会减少 `nlink`，直到 `nlink == 0` 才真正释放文件。软链接是一个特殊文件，内容是目标路径；删除软链接只删除路径文件本身，不影响目标文件。

### 4. 多级目录下文件树是否可能出现环路？如何处理？

可能。软链接可以构造路径环，目录硬链接也会制造环。常见处理方法是禁止普通用户给目录建立硬链接，解析软链接时限制递归深度，遍历目录树时记录已经访问过的 inode。

### 5. 目录是一类特殊文件，存放什么内容？用户能直接修改吗？

目录存放目录项，也就是文件名和 inode 编号的映射。普通用户不能像普通文件一样直接写目录字节流，而是通过 `create/link/unlink/rename/mkdir` 等系统调用间接修改。

### 6. 为什么会有大量文件系统类型？

不同场景需求不同。例如 ext4 注重通用性，xfs 适合大文件和高并发，btrfs 支持快照和校验，fat/ntfs 用于跨系统兼容，tmpfs 用内存模拟文件系统，NFS 面向网络共享。性能、可靠性、容量、延迟、闪存友好性和兼容性都会影响文件系统设计。

### 7. 可以把文件控制块放到目录项中吗？

可以，但不常见。这样查到目录项后能立刻得到元数据，访问路径短；缺点是目录项变大，重命名和移动成本高，也不适合多个硬链接共享同一个 inode。现代文件系统通常把目录项和 inode 分离。

### 8. 为什么既要进程打开文件表，又要系统打开文件表？

进程打开文件表保存每个进程自己的 fd 到打开文件对象的映射。系统打开文件表保存真正的打开实例，例如文件偏移、访问模式、引用计数。这样 `fork` 后父子进程可以共享同一个打开文件对象，而不同 fd 也可以指向同一个系统打开文件表项。

### 9. 文件分配的三种方式及特点。

连续分配：顺序和随机访问都简单，但容易产生外部碎片，文件扩展困难。

链式分配：扩展灵活，没有外部碎片，但随机访问很差，一个指针损坏可能影响后续数据。

索引分配：随机访问较好，文件扩展灵活，但需要额外索引块，空间和实现复杂度更高。

### 10. 打开文件写入后不及时关闭会有什么后果？读文件时各组件如何协作？

不及时关闭可能导致用户态或内核缓冲区未刷盘、引用计数不释放、锁和资源占用过久，异常断电时可能丢数据。读文件时，用户程序调用 `read`，内核根据 fd 找到打开文件对象，再定位 inode 和文件偏移，通过块缓存或块设备读取数据，最后把数据复制回用户缓冲区。

### 11. 文件系统是否一定在内核态？能否放到用户态？

不一定。文件系统可以放在用户态，例如 FUSE。用户态文件系统更容易开发、调试和隔离错误，但通常多一次上下文切换和数据拷贝。内核需要提供块设备访问、缓存、权限检查、IPC 或请求转发机制。

## 四、解题思路解析

### 1. 第六章主线

第六章从“进程和地址空间”推进到“持久化存储”。核心变化是：应用不再只依赖内存里的数据，而是通过文件系统把数据长期保存下来。OS 需要维护 inode、目录项、数据块、位图、打开文件表和系统调用接口。

### 2. 硬链接实现思路

硬链接的关键是多个名字共享同一个 inode。因此 `linkat` 不能复制文件数据，只能新增目录项，并让目标 inode 的 `nlink` 加一。`unlinkat` 删除目录项时减少 `nlink`，只有 `nlink` 归零才释放数据块。

### 3. `fstat` 实现思路

`fstat` 的入口是 fd，不是路径。内核先在当前进程 fd 表里找到打开文件对象，再从文件对象关联的 inode 中取元数据，最后把 `Stat` 结构写回用户空间。这个流程体现了进程打开文件表和 inode 元数据的分工。

### 4. Linux 示例程序思路

`file_link_demo.c` 先创建原文件，再建立硬链接。建立硬链接后，两个路径的 inode 应相同，`nlink` 增加。删除原路径后，硬链接路径仍然可以读到文件内容。最后删除硬链接，文件数据才真正没有名字引用。

## 五、文件位置

本次答案与 Linux 示例程序位于：

```text
/home/daihuohuo/code/ch6-exercises
```

其中包括：
- `answers.md`
- `file_link_demo.c`
- `Makefile`
- 编译后生成的 `file_link_demo`

第六章 rCore 工程位于：

```text
/home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6
```

常用查看命令：

```bash
cat /home/daihuohuo/code/ch6-exercises/answers.md
cat /home/daihuohuo/code/ch6-exercises/file_link_demo.c
cat /home/daihuohuo/code/ch6-exercises/Makefile

grep -R "sys_linkat\|sys_unlinkat\|sys_fstat" -n /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/os/src
grep -R "nlink\|link\|unlink" -n /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/easy-fs/src
```

常用复现命令：

```bash
cd /home/daihuohuo/code/ch6-exercises
make clean
make
make run

cd /home/daihuohuo/code/rCore-Tutorial-Code-2025S-ch6/os
make run TEST=6 BASE=1
```

参考资料：
- rCore Tutorial Book v3 第六章练习：`https://rcore-os.cn/rCore-Tutorial-Book-v3/chapter6/4exercise.html`
