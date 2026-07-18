"""
Orchestration — job execution, scheduling, and (Phase 6) the weekly review.

Phase 1 ships the job core: a registry of runnable pipeline jobs, a jobs
table in trading.db, and a single-worker executor that runs each job in a
FRESH SUBPROCESS. Subprocess execution is deliberate:

  - each run imports fresh, so it picks up the latest parameter registry
    versions (config facade binds at import time);
  - pipeline writes to DuckDB happen in exactly one child process at a time
    (single-writer discipline);
  - a crashing pipeline cannot take the API down.
"""
from .jobs import JOB_SPECS, JobManager, get_job, list_jobs

__all__ = ["JOB_SPECS", "JobManager", "get_job", "list_jobs"]
