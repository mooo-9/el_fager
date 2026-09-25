"""
The job-application pipeline: find → score → tailor → Mo approves → apply →
track replies.

Each night `pipeline.prepare_batch` gathers jobs (the job boards plus the
Big 4's own career sites), scores each against Mo's CV, and drafts a tailored
application for the ones worth sending. In the morning Mo reviews the batch
on the dashboard's /jobs page and approves it with one click; only then does
`pipeline.run_approved` send anything. Until Mo turns practice mode off
(`settings()["live"]`), approved applications are marked as "would have
sent" and nothing leaves the machine.

State lives in data/career/ (gitignored): profile.json, applications.json,
settings.json.
"""
