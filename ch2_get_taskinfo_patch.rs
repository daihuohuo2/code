// Kernel side patch sketch for rCore chapter 2 get_taskinfo.
// Suggested files:
// - os/src/batch.rs
// - os/src/syscall/mod.rs
// - os/src/syscall/process.rs
// User side:
// - user/src/syscall.rs
// - user/src/lib.rs
// - user/src/bin/ch2b_get_taskinfo.rs

// ---------- shared layout ----------
#[repr(C)]
#[derive(Copy, Clone)]
pub struct TaskInfo {
    pub id: usize,
    pub name: [u8; 32],
}

// ---------- os/src/batch.rs ----------
pub fn get_current_app() -> usize {
    APP_MANAGER.exclusive_access().current_app
}

pub fn get_current_app_name() -> &'static str {
    // In a minimal ch2 implementation there may be no app-name table yet.
    // The simplest stable name is app_{id}. If loader has names, return those.
    match get_current_app() {
        0 => "app_0",
        1 => "app_1",
        2 => "app_2",
        3 => "app_3",
        4 => "app_4",
        5 => "app_5",
        6 => "app_6",
        _ => "unknown",
    }
}

// ---------- os/src/syscall/mod.rs ----------
const SYSCALL_GET_TASKINFO: usize = 410;

pub fn syscall(syscall_id: usize, args: [usize; 3]) -> isize {
    match syscall_id {
        SYSCALL_GET_TASKINFO => sys_get_taskinfo(args[0] as *mut TaskInfo),
        // existing syscall branches:
        // SYSCALL_WRITE => sys_write(args[0], args[1] as *const u8, args[2]),
        // SYSCALL_EXIT => sys_exit(args[0] as i32),
        _ => panic!("Unsupported syscall_id: {}", syscall_id),
    }
}

// ---------- os/src/syscall/process.rs ----------
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

// ---------- user/src/syscall.rs ----------
pub const SYSCALL_GET_TASKINFO: usize = 410;

pub fn sys_get_taskinfo(info: *mut TaskInfo) -> isize {
    syscall(SYSCALL_GET_TASKINFO, [info as usize, 0, 0])
}

// ---------- user/src/lib.rs ----------
pub fn get_taskinfo() -> Option<TaskInfo> {
    let mut info = TaskInfo {
        id: 0,
        name: [0; 32],
    };
    if sys_get_taskinfo(&mut info as *mut TaskInfo) == 0 {
        Some(info)
    } else {
        None
    }
}

// ---------- user/src/bin/ch2b_get_taskinfo.rs ----------
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
