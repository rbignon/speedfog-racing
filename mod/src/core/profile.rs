//! Profiling helpers for opt-in Tracy instrumentation.
//!
//! All symbols here are `pub(crate)`. When the `profile-tracy` feature is
//! disabled they are zero-cost no-ops (the macro expands to an empty block,
//! and `frame_mark()` becomes an empty function the compiler inlines away).
//!
//! When the feature is enabled, `profile_span!` expands to a `debug_span!`
//! that is guarded-entered, and `frame_mark()` forwards to Tracy.

/// Enter a profiling span scoped to the surrounding block.
///
/// Usage:
/// ```ignore
/// fn hot_path() {
///     crate::profile_span!("hot_path");
///     // ... work ...
/// }
/// ```
///
/// The guard is bound to a hidden local, so the span stays active until the
/// enclosing block ends. Use this form inside inner loops where you do not
/// want to write an explicit `let _g = ...;` line.
#[cfg(feature = "profile-tracy")]
#[macro_export]
macro_rules! profile_span {
    ($name:expr) => {
        let _profile_span_guard = ::tracing::debug_span!($name).entered();
    };
    ($name:expr, $($field:tt)*) => {
        let _profile_span_guard = ::tracing::debug_span!($name, $($field)*).entered();
    };
}

#[cfg(not(feature = "profile-tracy"))]
#[macro_export]
macro_rules! profile_span {
    ($name:expr) => {};
    ($name:expr, $($field:tt)*) => {};
}

/// Mark the end of a rendered frame for Tracy's timeline.
///
/// Call this once per DX12 present (i.e. at the end of `ImguiRenderLoop::render`).
#[cfg(all(feature = "profile-tracy", target_os = "windows"))]
#[inline]
pub fn frame_mark() {
    tracy_client::Client::running()
        .expect("tracy client not started")
        .frame_mark();
}

#[cfg(not(all(feature = "profile-tracy", target_os = "windows")))]
#[inline]
pub fn frame_mark() {}
