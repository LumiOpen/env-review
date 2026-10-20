CREATE TABLE people (
  person_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('person','service_account')),
  organization_name TEXT NOT NULL,
  active_flag INTEGER NOT NULL CHECK (active_flag IN (0,1))
);

CREATE TABLE intake_requests (
  intake_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL UNIQUE,
  process_id TEXT NOT NULL,
  submitted_by_id TEXT NOT NULL,
  received_ts TEXT NOT NULL,
  validation_status TEXT NOT NULL CHECK (validation_status IN ('validated','rework_required','rejected','test_fixture')),
  validation_outcome TEXT NOT NULL,
  change_version TEXT NOT NULL CHECK (change_version IN ('pre_change','post_change','sandbox')),
  cohort_case_count INTEGER NOT NULL CHECK (cohort_case_count >= 0),
  validated_rework_case_count INTEGER NOT NULL DEFAULT 0 CHECK (validated_rework_case_count >= 0),
  cached_handoff_count INTEGER,
  source_record_key TEXT NOT NULL UNIQUE,
  FOREIGN KEY (submitted_by_id) REFERENCES people(person_id)
);
CREATE INDEX idx_intake_case ON intake_requests(case_id);
CREATE INDEX idx_intake_cohort_status ON intake_requests(change_version, validation_status);
CREATE INDEX idx_intake_received ON intake_requests(received_ts);

CREATE TABLE intake_rework_items (
  rework_id TEXT PRIMARY KEY,
  intake_id TEXT NOT NULL,
  rework_reason_code TEXT NOT NULL,
  opened_ts TEXT NOT NULL,
  resolved_ts TEXT,
  resolution_status TEXT NOT NULL CHECK (resolution_status IN ('validated','resolved','reopened','rejected','test_fixture')),
  validation_status TEXT NOT NULL CHECK (validation_status IN ('validated','unvalidated','test_fixture')),
  validated_case_count INTEGER NOT NULL DEFAULT 0 CHECK (validated_case_count >= 0),
  resubmission_number INTEGER NOT NULL DEFAULT 1 CHECK (resubmission_number >= 1),
  source_event_key TEXT NOT NULL UNIQUE,
  FOREIGN KEY (intake_id) REFERENCES intake_requests(intake_id)
);
CREATE INDEX idx_rework_intake ON intake_rework_items(intake_id);
CREATE INDEX idx_rework_status ON intake_rework_items(validation_status, resolution_status);

CREATE TABLE stakeholder_handoffs (
  handoff_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  from_role_label TEXT NOT NULL,
  to_role_label TEXT NOT NULL,
  from_role_code TEXT NOT NULL CHECK (from_role_code IN ('requester','travel_admin','budget_owner','supervisor','director','payment_team','fixture')),
  to_role_code TEXT NOT NULL CHECK (to_role_code IN ('requester','travel_admin','budget_owner','supervisor','director','payment_team','fixture')),
  handoff_ts TEXT NOT NULL,
  handoff_reason TEXT NOT NULL,
  change_version TEXT NOT NULL CHECK (change_version IN ('pre_change','post_change','sandbox')),
  canonical_handoff_count INTEGER NOT NULL CHECK (canonical_handoff_count >= 0),
  case_count INTEGER NOT NULL CHECK (case_count >= 0),
  ingestion_key TEXT NOT NULL,
  is_ingestion_retry INTEGER NOT NULL CHECK (is_ingestion_retry IN (0,1)),
  source_record_key TEXT NOT NULL UNIQUE
);
CREATE INDEX idx_handoff_case ON stakeholder_handoffs(case_id);
CREATE INDEX idx_handoff_cohort ON stakeholder_handoffs(change_version, is_ingestion_retry);
CREATE INDEX idx_handoff_roles ON stakeholder_handoffs(from_role_code, to_role_code);
