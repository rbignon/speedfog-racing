// Build script for SpeedFog Racing Mod
// - Copies the config file to the output directory after build
// - Embeds build metadata (timestamp, git commit, rustc version) for the
//   startup log, so a user's mod log can be traced back to an exact artifact.

use std::env;
use std::fs;
use std::path::Path;
use std::process::Command;

fn main() {
    // Tell Cargo to rerun this script if the config file changes
    println!("cargo:rerun-if-changed=speedfog_racing.toml");

    copy_config();
    emit_build_metadata();
}

fn copy_config() {
    // Get the output directory from Cargo
    let out_dir = env::var("OUT_DIR").unwrap();

    // The OUT_DIR is something like target/release/build/speedfog-racing-mod-xxx/out
    // We need to go up to target/release or target/debug
    let out_path = Path::new(&out_dir);

    // Navigate up to find the profile directory (release/debug)
    // OUT_DIR = target/<profile>/build/<crate>-<hash>/out
    let target_dir = out_path
        .ancestors()
        .nth(3) // Go up 3 levels from 'out'
        .expect("Could not find target directory");

    // Copy config file
    let config_src = Path::new("speedfog_racing.toml");
    let config_dst = target_dir.join("speedfog_racing.toml");

    if config_src.exists() {
        fs::copy(config_src, &config_dst).expect("Failed to copy config file");
        println!(
            "cargo:warning=Copied config file to {}",
            config_dst.display()
        );
    }
}

/// Embed build metadata as compile-time env vars for the startup log.
///
/// The rerun triggers refresh the values whenever the checked-out commit
/// changes; the timestamp and rustc version piggyback on the same reruns.
/// Local incremental builds with uncommitted changes may therefore carry
/// slightly stale metadata; CI builds always start from a fresh commit, so
/// artifact metadata is exact. Values fall back to "unknown" rather than
/// failing the build (e.g. building from a source archive without .git).
///
/// Any rerun of this script changes the timestamp and thus recompiles the
/// whole crate (including a speedfog_racing.toml edit, which previously
/// only re-copied the file). Triggers are only emitted for paths that
/// exist: cargo treats a missing tracked path as always-dirty and would
/// otherwise rerun, and therefore rebuild, on every single build.
fn emit_build_metadata() {
    emit_rerun_if_exists("../.git/HEAD");
    if let Some(head_ref) = git_head_ref() {
        let loose_ref = format!("../.git/{head_ref}");
        if Path::new(&loose_ref).exists() {
            println!("cargo:rerun-if-changed={loose_ref}");
        } else {
            // After `git gc`/`git pack-refs` the branch ref lives here.
            emit_rerun_if_exists("../.git/packed-refs");
        }
    }

    let timestamp = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ");
    println!("cargo:rustc-env=SPEEDFOG_BUILD_TIMESTAMP={timestamp}");

    let commit = command_stdout("git", &["rev-parse", "--short=10", "HEAD"]);
    println!(
        "cargo:rustc-env=SPEEDFOG_GIT_COMMIT={}",
        commit.as_deref().unwrap_or("unknown")
    );

    let rustc = env::var("RUSTC")
        .ok()
        .and_then(|rustc| command_stdout(&rustc, &["--version"]))
        .map(|v| v.trim_start_matches("rustc ").to_string());
    println!(
        "cargo:rustc-env=SPEEDFOG_RUSTC_VERSION={}",
        rustc.as_deref().unwrap_or("unknown")
    );
}

fn emit_rerun_if_exists(path: &str) {
    if Path::new(path).exists() {
        println!("cargo:rerun-if-changed={path}");
    }
}

/// Branch ref path from `.git/HEAD` (e.g. `refs/heads/master`), or `None`
/// on a detached HEAD or outside a git checkout.
fn git_head_ref() -> Option<String> {
    let head = fs::read_to_string("../.git/HEAD").ok()?;
    Some(head.strip_prefix("ref: ")?.trim().to_string())
}

/// Trimmed stdout of a command, or `None` if it fails or prints nothing.
fn command_stdout(program: &str, args: &[&str]) -> Option<String> {
    let output = Command::new(program).args(args).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8(output.stdout).ok()?;
    let trimmed = stdout.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}
