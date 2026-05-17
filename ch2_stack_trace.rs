// Put this file at:
// /home/daihuohuo/code/rCore-Tutorial-Code-2025S/os/src/stack_trace.rs
//
// Also add `mod stack_trace;` in os/src/main.rs and call
// `crate::stack_trace::print_stack_trace();` from panic handler.
//
// The project should be built with:
// -Cforce-frame-pointers=yes

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

#[panic_handler]
fn panic(info: &core::panic::PanicInfo) -> ! {
    if let Some(location) = info.location() {
        println!(
            "[kernel] panicked at {}:{} {}",
            location.file(),
            location.line(),
            info.message().unwrap()
        );
    } else {
        println!("[kernel] panicked: {}", info.message().unwrap());
    }
    unsafe {
        print_stack_trace();
    }
    crate::sbi::shutdown(false)
}
