-- ============================================================================
-- QA-2026-08-13 production data cleanup (fix pack)
-- Findings covered: C-07, C-08, C-12, H-01, H-03, H-07 (backfill), M-01,
--                   M-03, M-09, L-05
--
-- HOW TO RUN (on the production host, against the production DB):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f cleanup/qa-2026-08-13/cleanup.sql
--
-- Design rules honoured:
--   * Single transaction — all-or-nothing.
--   * No schema changes; data-only. No DELETEs on rows referenced elsewhere.
--   * Prefers UPDATE (archive/reject/relabel) over DELETE.
--   * Never touches User rows; never touches admin credentials.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. C-08 / M-09: dedupe tailored resume versions.
--    Keep the HIGHEST version per (userId, sourceJobId); delete the rest
--    ONLY when nothing references them (Application.resumeId has no cascade).
--    Referenced duplicates are marked rejected instead of deleted.
-- ----------------------------------------------------------------------------
WITH ranked AS (
  SELECT id,
         ROW_NUMBER() OVER (
           PARTITION BY "userId", "sourceJobId"
           ORDER BY version DESC, "createdAt" DESC
         ) AS rn
  FROM "Resume"
  WHERE "sourceJobId" IS NOT NULL
),
dupes AS (SELECT id FROM ranked WHERE rn > 1),
deletable AS (
  SELECT d.id FROM dupes d
  WHERE NOT EXISTS (SELECT 1 FROM "Application" a WHERE a."resumeId" = d.id)
    AND NOT EXISTS (SELECT 1 FROM "Resume" c WHERE c."parentId" = d.id)
),
del AS (DELETE FROM "Resume" WHERE id IN (SELECT id FROM deletable) RETURNING id),
rej AS (
  UPDATE "Resume"
     SET "approvalStatus" = 'rejected'
   WHERE id IN (SELECT id FROM dupes)
     AND id NOT IN (SELECT id FROM deletable)
     AND "approvalStatus" = 'pending'
  RETURNING id
)
SELECT (SELECT COUNT(*) FROM del) AS duplicate_resumes_deleted,
       (SELECT COUNT(*) FROM rej) AS duplicate_resumes_rejected;

-- ----------------------------------------------------------------------------
-- 2. M-09 (kept versions): a pending resume whose approval request no longer
--    exists (expired/purged) can never be approved through the UI — approve
--    the kept latest version per job so Resume Studio stops showing an
--    all-pending wall. Versions still awaiting a live pending ApprovalRequest
--    are left pending (human-in-the-loop preserved).
-- ----------------------------------------------------------------------------
WITH kept AS (
  SELECT id, "userId",
         ROW_NUMBER() OVER (
           PARTITION BY "userId", "sourceJobId"
           ORDER BY version DESC, "createdAt" DESC
         ) AS rn
  FROM "Resume"
  WHERE "sourceJobId" IS NOT NULL AND "approvalStatus" = 'pending'
),
approvable AS (
  SELECT k.id FROM kept k
  WHERE k.rn = 1
    AND NOT EXISTS (
      SELECT 1 FROM "ApprovalRequest" ar
      WHERE ar."userId" = k."userId"
        AND ar.status = 'pending'
        AND ar.payload::text LIKE '%' || k.id || '%'
    )
),
appr AS (
  UPDATE "Resume" SET "approvalStatus" = 'approved'
  WHERE id IN (SELECT id FROM approvable)
  RETURNING id
)
SELECT COUNT(*) AS orphaned_pending_resumes_approved FROM appr;

-- ----------------------------------------------------------------------------
-- 3. C-07 / L-05: ensure exactly one clearly-labelled base resume per user.
--    The base is the oldest root (parentId IS NULL). Rename it "Base Resume"
--    when its label is missing or reads like a tailored version.
-- ----------------------------------------------------------------------------
WITH base AS (
  SELECT DISTINCT ON ("userId") id
  FROM "Resume"
  WHERE "parentId" IS NULL
  ORDER BY "userId", "createdAt" ASC
),
fix AS (
  UPDATE "Resume" r
     SET label = 'Base Resume', "approvalStatus" = 'approved'
   WHERE r.id IN (SELECT id FROM base)
     AND (r.label IS NULL OR r.label = '' OR r.label ILIKE 'tailored%')
  RETURNING r.id
)
SELECT COUNT(*) AS base_resumes_relabelled FROM fix;

-- ----------------------------------------------------------------------------
-- 4. M-01: typo "Prinicipal" → "Principal" (job titles + resume labels).
-- ----------------------------------------------------------------------------
WITH j AS (
  UPDATE "Job" SET title = REPLACE(title, 'Prinicipal', 'Principal')
  WHERE title LIKE '%Prinicipal%' RETURNING id
),
r AS (
  UPDATE "Resume" SET label = REPLACE(label, 'Prinicipal', 'Principal')
  WHERE label LIKE '%Prinicipal%' RETURNING id
)
SELECT (SELECT COUNT(*) FROM j) AS job_titles_typo_fixed,
       (SELECT COUNT(*) FROM r) AS resume_labels_typo_fixed;

-- ----------------------------------------------------------------------------
-- 5. H-01 / M-03: "Copy of ..." duplicate/test jobs.
--    a) If an unprefixed twin exists and the copy is unreferenced → delete.
--    b) Otherwise strip the "Copy of " prefix (keeps referenced rows intact).
-- ----------------------------------------------------------------------------
WITH copies AS (
  SELECT id, "userId", company, SUBSTRING(title FROM 9) AS clean_title
  FROM "Job" WHERE title LIKE 'Copy of %'
),
deletable AS (
  SELECT c.id FROM copies c
  WHERE EXISTS (
          SELECT 1 FROM "Job" t
          WHERE t."userId" = c."userId" AND t.company = c.company
            AND t.title = c.clean_title AND t.id <> c.id)
    AND NOT EXISTS (SELECT 1 FROM "Application" a WHERE a."jobId" = c.id)
    AND NOT EXISTS (SELECT 1 FROM "Resume" r WHERE r."sourceJobId" = c.id)
),
del AS (DELETE FROM "Job" WHERE id IN (SELECT id FROM deletable) RETURNING id),
ren AS (
  UPDATE "Job" SET title = SUBSTRING(title FROM 9)
  WHERE title LIKE 'Copy of %' AND id NOT IN (SELECT id FROM deletable)
  RETURNING id
)
SELECT (SELECT COUNT(*) FROM del) AS copy_jobs_deleted,
       (SELECT COUNT(*) FROM ren) AS copy_jobs_renamed;

-- ----------------------------------------------------------------------------
-- 6. C-12: SEEK removal — archive every job sourced from seek/seek-alert so
--    the Settings "Job Board Integrations" list stops showing SEEK as a
--    connected source. (The seek adapter is already gated off in code behind
--    AETHER_ENABLE_SEEK; this clears the residual data.) Rows are archived,
--    not deleted, so historical applications stay intact.
-- ----------------------------------------------------------------------------
WITH s AS (
  UPDATE "Job" SET status = 'archived', saved = false
  WHERE LOWER(source) IN ('seek', 'seek-alert') AND status <> 'archived'
  RETURNING id
)
SELECT COUNT(*) AS seek_jobs_archived FROM s;

-- ----------------------------------------------------------------------------
-- 7. H-07 backfill: archive stale discovered jobs (>30 days, unsaved, never
--    applied to). Forward-looking archival now runs inside the Scout agent
--    (JobRepository.archive_stale, AETHER_JOB_STALE_DAYS).
-- ----------------------------------------------------------------------------
WITH stale AS (
  UPDATE "Job" j SET status = 'archived'
  WHERE j.status = 'discovered' AND j.saved = false
    AND j."updatedAt" < NOW() - INTERVAL '30 days'
    AND NOT EXISTS (SELECT 1 FROM "Application" a WHERE a."jobId" = j.id)
  RETURNING id
)
SELECT COUNT(*) AS stale_jobs_archived FROM stale;

-- ----------------------------------------------------------------------------
-- 8. H-03: duplicate pending approvals — keep the NEWEST pending request per
--    (userId, type, applicationId) and reject the older duplicates.
-- ----------------------------------------------------------------------------
WITH ranked AS (
  SELECT id,
         ROW_NUMBER() OVER (
           PARTITION BY "userId", type, "applicationId"
           ORDER BY "createdAt" DESC
         ) AS rn
  FROM "ApprovalRequest"
  WHERE status = 'pending' AND "applicationId" IS NOT NULL
),
rej AS (
  UPDATE "ApprovalRequest"
     SET status = 'rejected', "resolvedAt" = NOW()
   WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
  RETURNING id
)
SELECT COUNT(*) AS duplicate_pending_approvals_rejected FROM rej;

-- ----------------------------------------------------------------------------
-- Final report
-- ----------------------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM "Job")                                            AS jobs_total,
  (SELECT COUNT(*) FROM "Job" WHERE status = 'archived')                  AS jobs_archived,
  (SELECT COUNT(*) FROM "Job" WHERE title LIKE 'Copy of %')               AS jobs_copy_prefix_remaining,
  (SELECT COUNT(*) FROM "Job" WHERE LOWER(source) IN ('seek','seek-alert')
                                AND status <> 'archived')                 AS seek_jobs_active_remaining,
  (SELECT COUNT(*) FROM "Resume")                                         AS resumes_total,
  (SELECT COUNT(*) FROM "Resume" WHERE "approvalStatus" = 'pending')      AS resumes_pending_remaining,
  (SELECT COUNT(*) FROM "ApprovalRequest" WHERE status = 'pending')       AS approvals_pending_remaining;

COMMIT;
