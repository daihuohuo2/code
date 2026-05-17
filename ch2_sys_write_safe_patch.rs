// sys_write safety-check patch sketch for rCore chapter 2 lab.
// Suggested files:
// - os/src/config.rs
// - os/src/batch.rs
// - os/src/syscall/fs.rs

// ---------- os/src/config.rs ----------
pub const USER_STACK_SIZE: usize = 4096;
pub const APP_BASE_ADDRESS: usize = 0x8040_0000;
pub const APP_SIZE_LIMIT: usize = 0x20_000;

// ---------- os/src/batch.rs ----------
pub fn current_app_range() -> (usize, usize) {
    let app_id = get_current_app();
    let start = crate::config::APP_BASE_ADDRESS + app_id * crate::config::APP_SIZE_LIMIT;
    let end = start + crate::config::APP_SIZE_LIMIT;
    (start, end)
}

pub fn current_user_stack_range() -> (usize, usize) {
    // Adjust this function to match your chapter-2 stack layout.
    // The lab requires USER_STACK_SIZE = 4096 and 4096-byte alignment.
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

// ---------- os/src/syscall/fs.rs ----------
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
