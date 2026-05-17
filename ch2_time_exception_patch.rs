// Completion-time and exception-statistics patch sketch for rCore chapter 2.
// Suggested files:
// - os/src/timer.rs
// - os/src/batch.rs
// - os/src/trap/mod.rs
// - os/src/syscall/process.rs

// ---------- os/src/timer.rs ----------
use riscv::register::time;

pub fn get_time() -> usize {
    time::read()
}

// If QEMU timebase is 10MHz, one tick is 0.1us. Keep this as a display helper.
pub fn get_time_ms() -> usize {
    get_time() / 10_000
}

// ---------- os/src/batch.rs ----------
pub const MAX_APP_NUM: usize = 16;

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

// Call `mark_app_start(current_app)` just before entering user mode in
// `run_next_app`.

// ---------- os/src/syscall/process.rs ----------
pub fn sys_exit(exit_code: i32) -> ! {
    let app_id = crate::batch::get_current_app();
    println!("[kernel] Application exited with code {}", exit_code);
    crate::batch::print_app_finish_time(app_id);
    crate::batch::run_next_app()
}

// ---------- os/src/trap/mod.rs ----------
pub fn report_bad_app(scause: usize, stval: usize, sepc: usize) {
    let app_id = crate::batch::get_current_app();
    println!(
        "[kernel] app_{} exception: scause={:#x}, stval={:#x}, sepc={:#x}",
        app_id, scause, stval, sepc
    );
    crate::batch::print_app_finish_time(app_id);
}

// In trap_handler, call `report_bad_app(scause.bits(), stval, cx.sepc)` before
// killing the current bad application. Typical branches:
//
// Exception::StoreFault | Exception::StorePageFault => { ... }
// Exception::IllegalInstruction => { ... }
