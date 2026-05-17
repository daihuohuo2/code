// Syscall statistics patch sketch for rCore chapter 2.
// Suggested files:
// - os/src/syscall/mod.rs
// - os/src/batch.rs
// - os/src/syscall/process.rs

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

pub fn print_syscall_counts(app_id: usize) {
    if app_id >= MAX_APP_NUM {
        return;
    }
    println!("[kernel] syscall statistics for app_{}:", app_id);
    unsafe {
        for id in 0..MAX_SYSCALL_ID {
            let count = SYSCALL_COUNTS[app_id][id];
            if count != 0 {
                println!("  syscall {} -> {} time(s)", id, count);
            }
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

pub fn sys_exit(exit_code: i32) -> ! {
    let app_id = crate::batch::get_current_app();
    println!("[kernel] Application exited with code {}", exit_code);
    print_syscall_counts(app_id);
    crate::batch::run_next_app()
}
