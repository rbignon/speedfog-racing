//! On-disk copy of the event flags the server has not acknowledged yet
//! (`core::flag_buffer::UnackedFlags`), next to the DLL. Read once at
//! startup; written by a background thread, so a frame never waits on the
//! disk.

use std::fs;
use std::io::{ErrorKind, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

use crossbeam_channel::{unbounded, Receiver, Sender};
use tracing::{info, warn};

use crate::core::flag_buffer::UnackedFlags;

const WRITE_ATTEMPTS: u32 = 3;
const WRITE_RETRY_DELAY: Duration = Duration::from_millis(100);

pub struct UnackedStore {
    tx: Sender<UnackedFlags>,
}

impl UnackedStore {
    /// What a previous launch saved in `dir`, if anything readable.
    pub fn load(dir: &Path) -> Option<UnackedFlags> {
        let path = dir.join(UnackedFlags::FILENAME);
        let text = match fs::read_to_string(&path) {
            Ok(text) => text,
            Err(e) if e.kind() == ErrorKind::NotFound => return None,
            Err(e) => {
                warn!(error = %e, "[RACE] Could not read saved event flags");
                return None;
            }
        };
        match serde_json::from_str::<UnackedFlags>(&text) {
            Ok(saved) => {
                info!(
                    count = saved.flags.len(),
                    participant_id = %saved.participant_id,
                    "[RACE] Saved event flags found"
                );
                Some(saved)
            }
            Err(e) => {
                warn!(error = %e, "[RACE] Saved event flags unreadable, ignored");
                None
            }
        }
    }

    /// Start the writer thread for `dir`.
    pub fn spawn(dir: PathBuf) -> Self {
        let (tx, rx) = unbounded();
        std::thread::spawn(move || writer_loop(&dir, &rx));
        Self { tx }
    }

    /// Queue a save without blocking the caller.
    pub fn save(&self, flags: UnackedFlags) {
        let _ = self.tx.send(flags);
    }
}

fn writer_loop(dir: &Path, rx: &Receiver<UnackedFlags>) {
    let path = dir.join(UnackedFlags::FILENAME);
    let tmp = dir.join(format!("{}.tmp", UnackedFlags::FILENAME));
    while let Ok(mut flags) = rx.recv() {
        // Only the latest state matters.
        while let Ok(newer) = rx.try_recv() {
            flags = newer;
        }
        // A virus scanner or a sync client can hold the file for a moment.
        let mut attempt = 1;
        while let Err(e) = write(&path, &tmp, &flags) {
            if attempt == WRITE_ATTEMPTS {
                warn!(error = %e, "[RACE] Could not save unacknowledged event flags");
                break;
            }
            attempt += 1;
            std::thread::sleep(WRITE_RETRY_DELAY);
        }
    }
}

fn write(path: &Path, tmp: &Path, flags: &UnackedFlags) -> std::io::Result<()> {
    if flags.flags.is_empty() {
        return match fs::remove_file(path) {
            Err(e) if e.kind() != ErrorKind::NotFound => Err(e),
            _ => Ok(()),
        };
    }
    let json = serde_json::to_string(flags).map_err(std::io::Error::other)?;
    // Write then rename, so a crash mid-write never leaves a torn file.
    let mut file = fs::File::create(tmp)?;
    file.write_all(json.as_bytes())?;
    file.sync_all()?;
    drop(file);
    fs::rename(tmp, path)
}
