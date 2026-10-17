// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
//! Scoped planning mathematics. Native callers keep their original functions.
use std::cell::Cell;

pub type TwiddleProvider = fn(f64) -> (f64, f64);
thread_local! {
    static PROVIDER: Cell<Option<TwiddleProvider>> = const { Cell::new(None) };
}

/// Planning is synchronous. A thread-local guard isolates nested/concurrent
/// planners and restores the previous choice even if planning unwinds.
pub fn with_twiddle_provider<R>(provider: TwiddleProvider, body: impl FnOnce() -> R) -> R {
    with_optional_provider(Some(provider), body)
}

/// A nested native factory must not accidentally inherit portable planning.
pub fn with_native_twiddle_math<R>(body: impl FnOnce() -> R) -> R {
    with_optional_provider(None, body)
}

fn with_optional_provider<R>(provider: Option<TwiddleProvider>, body: impl FnOnce() -> R) -> R {
    PROVIDER.with(|cell| {
        struct Restore<'a> {
            cell: &'a Cell<Option<TwiddleProvider>>,
            previous: Option<TwiddleProvider>,
        }
        impl Drop for Restore<'_> {
            fn drop(&mut self) { self.cell.set(self.previous); }
        }
        let _restore = Restore { cell, previous: cell.replace(provider) };
        body()
    })
}

/// Return (sin, cos). Preserve the native separate cos/sin operations unless
/// a portable planner explicitly installed a provider on this thread.
pub fn sin_cos(angle: f64) -> (f64, f64) {
    PROVIDER.with(|cell| match cell.get() {
        Some(provider) => provider(angle),
        None => { let cos = angle.cos(); let sin = angle.sin(); (sin, cos) }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn first(x: f64) -> (f64, f64) { (x + 10.0, x - 10.0) }
    fn second(x: f64) -> (f64, f64) { (x + 20.0, x - 20.0) }
    fn native(x: f64) -> (f64, f64) { (x.sin(), x.cos()) }
    #[test]
    fn native_and_scoped_restore() {
        assert_eq!(sin_cos(0.25), native(0.25));
        with_twiddle_provider(first, || assert_eq!(sin_cos(0.25), first(0.25)));
        assert_eq!(sin_cos(0.25), native(0.25));
    }
    #[test]
    fn native_factory_isolates_ambient_provider() {
        with_twiddle_provider(first, || {
            with_native_twiddle_math(|| assert_eq!(sin_cos(0.25), native(0.25)));
            assert_eq!(sin_cos(0.25), first(0.25));
        });
        assert_eq!(sin_cos(0.25), native(0.25));
    }
    #[test]
    fn nested_and_unwind_restore() {
        with_twiddle_provider(first, || {
            let result = std::panic::catch_unwind(|| {
                with_twiddle_provider(second, || {
                    assert_eq!(sin_cos(0.25), second(0.25));
                    panic!("owned planning failure");
                });
            });
            assert!(result.is_err());
            assert_eq!(sin_cos(0.25), first(0.25));
        });
        assert_eq!(sin_cos(0.25), native(0.25));
    }
    #[test]
    fn concurrent_plans_are_isolated() {
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(3));
        let mut workers = Vec::new();
        for provider in [first as TwiddleProvider, second as TwiddleProvider] {
            let barrier = barrier.clone();
            workers.push(std::thread::spawn(move || {
                with_twiddle_provider(provider, || {
                    barrier.wait();
                    for _ in 0..1000 { assert_eq!(sin_cos(0.25), provider(0.25)); }
                });
                assert_eq!(sin_cos(0.25), native(0.25));
            }));
        }
        barrier.wait();
        assert_eq!(sin_cos(0.25), native(0.25));
        for worker in workers { worker.join().unwrap(); }
    }
}
