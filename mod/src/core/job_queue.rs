//! The scheduling of a shell worker thread, apart from the thread: one job
//! runs at a time, the jobs asked meanwhile wait in order. A job asked while
//! a job of the same kind (enum variant) waits takes its place when that kind
//! is replaceable (`QueuedJob::replaceable`); a job of a kind that is not is
//! never dropped and waits until it runs. Pure: the shell starts each
//! running job on its thread and reports its end (`JobQueue::finish`).

use std::collections::VecDeque;
use std::mem::discriminant;

/// What the queue needs to know of a job.
pub trait QueuedJob {
    /// Whether a job of this kind (enum variant), while it waits, is replaced
    /// by a newer job of the same kind: its asker only asks again once it
    /// has given it up. The same answer for every job of a kind. A kind that
    /// is not replaceable is never dropped.
    fn replaceable(&self) -> bool;
}

/// Where a job asked went.
#[derive(Debug, PartialEq, Eq)]
pub enum Asked<J> {
    /// Nothing was running: it runs now (`JobQueue::running`).
    Runs,
    /// Another job runs: it waits, in the place of `replaced` when it
    /// replaced a job waiting (dropped, never run).
    Queued { replaced: Option<J> },
}

/// The job running and the jobs waiting, oldest first.
#[derive(Debug)]
pub struct JobQueue<J> {
    running: Option<J>,
    waiting: VecDeque<J>,
}

impl<J> Default for JobQueue<J> {
    fn default() -> Self {
        Self {
            running: None,
            waiting: VecDeque::new(),
        }
    }
}

impl<J: QueuedJob> JobQueue<J> {
    /// Ask for `job`: it runs at once when nothing runs, else it waits,
    /// replacing a waiting job of its kind when that kind is replaceable
    /// (it keeps that job's place in the order).
    pub fn ask(&mut self, job: J) -> Asked<J> {
        if self.running.is_none() {
            self.running = Some(job);
            return Asked::Runs;
        }
        let replaced = self
            .waiting
            .iter_mut()
            .find(|waiting| discriminant(*waiting) == discriminant(&job) && waiting.replaceable());
        match replaced {
            Some(slot) => Asked::Queued {
                replaced: Some(std::mem::replace(slot, job)),
            },
            None => {
                self.waiting.push_back(job);
                Asked::Queued { replaced: None }
            }
        }
    }

    /// The job running: the one the shell's thread is doing, or has to start.
    pub fn running(&self) -> Option<&J> {
        self.running.as_ref()
    }

    /// The job running, to update what it carries.
    pub fn running_mut(&mut self) -> Option<&mut J> {
        self.running.as_mut()
    }

    /// Every job, the running one first, then those waiting in order: to
    /// update what each carries while it waits.
    pub fn jobs_mut(&mut self) -> impl Iterator<Item = &mut J> {
        self.running.iter_mut().chain(self.waiting.iter_mut())
    }

    /// The running job ended (answered, failed or never started): it is
    /// returned, for its answer, and the oldest waiting job runs next.
    pub fn finish(&mut self) -> Option<J> {
        let done = self.running.take();
        self.running = self.waiting.pop_front();
        done
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, PartialEq, Eq)]
    enum Job {
        Capture(u32),
        Probe(u32),
        Apply(u32),
    }

    impl QueuedJob for Job {
        fn replaceable(&self) -> bool {
            !matches!(self, Job::Apply(_))
        }
    }

    #[test]
    fn a_newer_job_replaces_the_one_waiting() {
        let mut queue = JobQueue::default();
        assert_eq!(queue.ask(Job::Capture(1)), Asked::Runs);
        assert_eq!(queue.ask(Job::Capture(2)), Asked::Queued { replaced: None });
        assert_eq!(
            queue.ask(Job::Capture(3)),
            Asked::Queued {
                replaced: Some(Job::Capture(2))
            }
        );
        assert_eq!(queue.running(), Some(&Job::Capture(1)));
        assert_eq!(queue.finish(), Some(Job::Capture(1)));
        assert_eq!(queue.running(), Some(&Job::Capture(3)));
        assert_eq!(queue.finish(), Some(Job::Capture(3)));
        assert_eq!(queue.running(), None);
    }

    #[test]
    fn an_empty_queue_runs_nothing() {
        let mut queue = JobQueue::<Job>::default();
        assert_eq!(queue.running(), None);
        assert_eq!(queue.finish(), None);
        assert_eq!(queue.running(), None);
        // Once emptied, the next job runs at once.
        assert_eq!(queue.ask(Job::Capture(1)), Asked::Runs);
        assert_eq!(queue.finish(), Some(Job::Capture(1)));
        assert_eq!(queue.finish(), None);
    }

    #[test]
    fn a_job_of_a_kind_not_replaceable_is_never_dropped() {
        let mut queue = JobQueue::default();
        assert_eq!(queue.ask(Job::Capture(1)), Asked::Runs);
        for job in [Job::Apply(2), Job::Apply(3), Job::Capture(4)] {
            assert_eq!(queue.ask(job), Asked::Queued { replaced: None });
        }
        // A capture replaces the capture waiting, in its place behind the
        // applies; another kind of job replaces nothing.
        assert_eq!(
            queue.ask(Job::Capture(5)),
            Asked::Queued {
                replaced: Some(Job::Capture(4))
            }
        );
        assert_eq!(queue.ask(Job::Probe(6)), Asked::Queued { replaced: None });
        let order: Vec<_> = std::iter::from_fn(|| queue.finish()).collect();
        assert_eq!(
            order,
            [
                Job::Capture(1),
                Job::Apply(2),
                Job::Apply(3),
                Job::Capture(5),
                Job::Probe(6)
            ]
        );
    }

    #[test]
    fn every_job_can_be_updated_in_place_in_its_order() {
        let mut queue = JobQueue::default();
        assert!(queue.running_mut().is_none());
        assert_eq!(queue.jobs_mut().count(), 0);
        queue.ask(Job::Apply(1));
        queue.ask(Job::Capture(2));
        queue.ask(Job::Apply(3));
        for job in queue.jobs_mut() {
            let (Job::Apply(n) | Job::Capture(n) | Job::Probe(n)) = job;
            *n *= 10;
        }
        if let Some(Job::Apply(n)) = queue.running_mut() {
            *n += 1;
        }
        let order: Vec<_> = std::iter::from_fn(|| queue.finish()).collect();
        assert_eq!(order, [Job::Apply(11), Job::Capture(20), Job::Apply(30)]);
    }

    #[test]
    fn the_running_job_is_never_replaced() {
        let mut queue = JobQueue::default();
        assert_eq!(queue.ask(Job::Capture(1)), Asked::Runs);
        assert_eq!(queue.ask(Job::Capture(2)), Asked::Queued { replaced: None });
        assert_eq!(queue.running(), Some(&Job::Capture(1)));
    }
}
