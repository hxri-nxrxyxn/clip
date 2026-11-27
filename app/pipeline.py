"""Pipeline compatibility module re-exporting storage, archive, stages, and orchestrator."""

# ruff: noqa: F401, F403
from app import analytics, archive, orchestrator, stages, storage
from app import jobs as jobs_module

# Core paths and directories
APP_DIR = storage.APP_DIR
ROOT = storage.ROOT
RUNS_DIR = jobs_module.RUNS_DIR
HISTORY_DIR = storage.HISTORY_DIR
CURRENT_JOB_PATH = storage.CURRENT_JOB_PATH
INGEST_OUTPUT = storage.INGEST_OUTPUT
CURRENT_RUN_POINTER = storage.CURRENT_RUN_POINTER
STAGE_IDS = stages.STAGE_IDS
STAGES = stages.STAGES
TRANSCRIBE_FILES = storage.TRANSCRIBE_FILES
TARGETED_DIR = storage.TARGETED_DIR
JOBS = jobs_module.JOBS
Jobs = jobs_module.Jobs

# Time and format helpers
now_iso = storage.now_iso
parse_iso = storage.parse_iso
read_json_path = storage.read_json_path
read_json = storage.read_json
slug = storage.slug
stage_output_dir = storage.stage_output_dir
stage_input_dir = storage.stage_input_dir
write_current_run_pointer = storage.write_current_run_pointer
read_current_run_pointer = storage.read_current_run_pointer
current_job = storage.current_job
set_current_job = storage.set_current_job
mark_current_run = storage.mark_current_run
update_current_job = storage.update_current_job
reconcile_current_job = storage.reconcile_current_job
clear_current_job = storage.clear_current_job
run_id_for_ingest = storage.run_id_for_ingest
resolve_run_id = storage.resolve_run_id
current_run_id = storage.current_run_id
ingest_for_run = storage.ingest_for_run
current_since = storage.current_since
file_after = storage.file_after
line_count_path = storage.line_count_path
transcribe_summary_from_path = storage.transcribe_summary_from_path
archive_files = storage.archive_files
archive_current_run = storage.archive_current_run
history = storage.history

# Stages and inspection helpers
file_info = stages.file_info
scan = stages.scan
line_count = stages.line_count
preview = stages.preview
outputs = stages.outputs
inputs = stages.inputs
status = stages.status
format_path = stages.format_path
clock = analytics.clock

# Orchestrator and archive
activity = orchestrator.activity
summary = orchestrator.summary
overview = orchestrator.overview
detail = orchestrator.detail
media = orchestrator.media
history_detail = orchestrator.history_detail
job_label = orchestrator.job_label
jobs_list = orchestrator.jobs_list
jobs = orchestrator.jobs_fn
job_detail = orchestrator.job_detail
prepare_stage_workspace = archive.prepare_stage_workspace
update_job_after_stage = archive.update_job_after_stage
start_targeted_extract_run = archive.start_targeted_extract_run
update_targeted_extract_after_run = archive.update_targeted_extract_after_run
mark_targeted_extract_failed = archive.mark_targeted_extract_failed
targeted_extract_detail = archive.targeted_extract_detail
run_targeted_extract = archive.run_targeted_extract
start_selection_run = archive.start_selection_run
update_selection_after_run = archive.update_selection_after_run
mark_selection_failed = archive.mark_selection_failed
selection_detail = archive.selection_detail
run_selection = archive.run_selection
start_visual_run = archive.start_visual_run
update_visual_after_run = archive.update_visual_after_run
mark_visual_failed = archive.mark_visual_failed
visual_detail = archive.visual_detail
run_visual = archive.run_visual
validate_target = orchestrator.validate_target
handoff = orchestrator.handoff
