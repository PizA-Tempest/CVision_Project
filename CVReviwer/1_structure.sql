-- ---------------------------------------------------------------------
-- 1_structure.sql — the CVision database, tables only, no rows
-- (PostgreSQL / Supabase)
--
--   psql "$DATABASE_URL" -f 1_structure.sql
--
-- Creates all ten tables for Feature 1 (job fetching), Feature 2 (job
-- matching), Feature 5 (authentication) and the Feature 5 groundwork.
-- Inserts nothing:
-- run 2_data.sql afterwards, or the app will have no admin account to log
-- in with and no provider profile to create a scraper from.
--
-- *** DESTRUCTIVE — DROPS EVERY TABLE ***
-- Scraped listings, the activity log, match results and, most expensively,
-- the LLM extractions and embeddings in job_enrichment (roughly one
-- gpt-4o-mini call per listing to regenerate). Feature 3's CVs are not
-- affected: they live in cvs.json and uploads/, not in the database.
--
-- Supabase tip: run this in the SQL Editor, or with psql using the
-- connection string from Project Settings → Database.
-- ---------------------------------------------------------------------

-- Dropped children-first so the foreign keys unwind cleanly.
DROP TABLE IF EXISTS job_match CASCADE;
DROP TABLE IF EXISTS job_enrichment CASCADE;
DROP TABLE IF EXISTS jobseeker_cv CASCADE;
DROP TABLE IF EXISTS jobseeker CASCADE;
DROP TABLE IF EXISTS log_entry CASCADE;
DROP TABLE IF EXISTS job_listing CASCADE;
DROP TABLE IF EXISTS schedule CASCADE;
DROP TABLE IF EXISTS scraper CASCADE;
DROP TABLE IF EXISTS provider_profile CASCADE;
DROP TABLE IF EXISTS admin CASCADE;


-- =====================================================================
-- FEATURE 1 — Job fetching from external APIs
-- Tables defined by CVision_Data_Dictionary.docx.
-- =====================================================================

-- Admin -----------------------------------------------------------------
-- Feature #5 (Authentication) stores a salted hash here (SRS-082):
--   pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex> (260k iterations)
-- The seed in 2_data.sql is still legacy plaintext ("123") so a fresh
-- install has a known login; auth_service.authenticate_admin() accepts it
-- once and transparently upgrades the row to a hash.
CREATE TABLE admin (
    id        VARCHAR(36)  NOT NULL PRIMARY KEY,
    username  VARCHAR(100) NOT NULL UNIQUE,
    password  VARCHAR(255) NOT NULL
);


-- Jobseeker ---------------------------------------------------------------
-- Feature #5 (Authentication). One row per registered account (URS-010).
-- jobseeker_cv.jobseeker_id references this logically (no FK: legacy rows
-- carry the "John Doe" stand-in and must keep loading). Passwords are
-- salted hashes only, never plaintext (SRS-082).
CREATE TABLE IF NOT EXISTS jobseeker (
    id            VARCHAR(36)  NOT NULL PRIMARY KEY,
    username      VARCHAR(100) NOT NULL UNIQUE,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMPTZ  NULL
);


-- ProviderProfile -------------------------------------------------------
-- The five JSON columns are read back by scraper_service._decode_json_columns,
-- which handles either a JSON-typed value or a plain string, so TEXT works
-- equally well here.
CREATE TABLE provider_profile (
    id             VARCHAR(36)  NOT NULL PRIMARY KEY,
    profile_name   VARCHAR(150) NOT NULL UNIQUE,
    url            TEXT         NOT NULL,
    query_params   TEXT         NULL,
    headers        TEXT         NULL,
    body_template  TEXT         NULL,
    fields         TEXT         NULL,
    field_map      TEXT         NULL
);


-- Scraper ---------------------------------------------------------------
-- last_request_date is NULL until the first run. It is a real timestamp,
-- never the "-" or "2026-06-09 20:12 UTC" strings the test cases show --
-- those are produced at the read boundary by
-- scraper_service.format_display_datetime().
CREATE TABLE scraper (
    id                 VARCHAR(36)  NOT NULL PRIMARY KEY,
    source_profile_id  VARCHAR(36)  NULL,
    website_name       VARCHAR(200) NOT NULL,
    description        TEXT         NULL,
    request            TEXT         NOT NULL,
    field_map          TEXT         NULL,
    last_request_date  TIMESTAMPTZ  NULL,
    CONSTRAINT fk_scraper_profile FOREIGN KEY (source_profile_id)
        REFERENCES provider_profile (id) ON DELETE SET NULL
);


-- Schedule --------------------------------------------------------------
-- NOT IN THE DATA DICTIONARY: the UNIQUE (scraper_id) constraint. It is
-- required, not cosmetic -- scraper_service.persist_schedule() upserts with
-- INSERT ... ON CONFLICT, which silently inserts a second row
-- instead of updating if scraper_id is not unique, and list_scrapers()'s
-- LEFT JOIN would then return duplicate scrapers. Every use of a schedule
-- in the code and the test cases treats it as one-per-scraper.
CREATE TABLE schedule (
    id             VARCHAR(36) NOT NULL PRIMARY KEY,
    scraper_id     VARCHAR(36) NOT NULL,
    mode           VARCHAR(20) NOT NULL CHECK (mode IN ('fixed','recurring')),
    run_at         TIMESTAMPTZ NULL,
    interval_type  VARCHAR(20) NULL CHECK (interval_type IS NULL OR interval_type IN ('weekly','biweekly','monthly')),
    enabled        BOOLEAN     NOT NULL DEFAULT TRUE,
    last_auto_run  TIMESTAMPTZ NULL,
    UNIQUE (scraper_id),
    CONSTRAINT fk_schedule_scraper FOREIGN KEY (scraper_id)
        REFERENCES scraper (id) ON DELETE CASCADE
);


-- JobListing ------------------------------------------------------------
-- TIMESTAMP(3), not plain TIMESTAMP: job_posted_date round-trips through
-- ISO-8601 with milliseconds ("2026-06-09T20:12:48.473Z" in UT-1-16-001),
-- and plain TIMESTAMP would truncate the .473 away.
--
-- No UNIQUE on url: duplicate detection is done in Python by
-- scraper_service.execute() so it can count skips, and job_service
-- .save_listings() rewrites the whole table on every save -- a UNIQUE
-- constraint here would turn a routine save into a hard failure.
CREATE TABLE job_listing (
    id                   VARCHAR(36)  NOT NULL PRIMARY KEY,
    scraper_id           VARCHAR(36)  NULL,
    url                  TEXT         NULL,
    job_title            VARCHAR(300) NULL,
    company_name         VARCHAR(300) NULL,
    job_location         VARCHAR(300) NULL,
    job_details          TEXT         NULL,
    job_employment_type  VARCHAR(100) NULL,
    job_posted_date      TIMESTAMPTZ  NULL,
    salary               VARCHAR(200) NULL,
    outdated_manual      BOOLEAN      NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_listing_scraper FOREIGN KEY (scraper_id)
        REFERENCES scraper (id) ON DELETE SET NULL
);
CREATE INDEX idx_listing_scraper ON job_listing (scraper_id);


-- LogEntry --------------------------------------------------------------
-- action mirrors the Data Dictionary's enum exactly (and log_service
-- .VALID_ACTIONS). Note "configure", "profile_create" and "profile_delete"
-- are in the enum but no M-method implements them -- see
-- TBD_and_Conflicts.md Part 3.
CREATE TABLE log_entry (
    id           VARCHAR(36) NOT NULL PRIMARY KEY,
    user_id      VARCHAR(36) NOT NULL,
    action       VARCHAR(30) NOT NULL CHECK (action IN (
                      'add','edit','delete','configure','schedule','run','auto_run',
                      'profile_create','profile_delete','job_edit','job_mark','job_delete')),
    target_name  VARCHAR(300) NULL,
    detail       TEXT         NULL,
    timestamp    TIMESTAMPTZ  NOT NULL,
    CONSTRAINT fk_log_admin FOREIGN KEY (user_id)
        REFERENCES admin (id) ON DELETE RESTRICT
);
CREATE INDEX idx_log_time ON log_entry (timestamp);


-- =====================================================================
-- FEATURE 2 — Job matching  (+ Feature 5 groundwork)
-- job_enrichment and job_match hold data derived from Feature 1's
-- listings; jobseeker_cv is the CV-ownership index Feature 5 will own.
-- Created after the Feature 1 tables because two of them reference
-- job_listing.
-- =====================================================================

-- JobEnrichment ---------------------------------------------------------
-- The six fields Feature 2 needs that Feature 1's job_listing does not
-- carry, because they are *derived* rather than scraped: an LLM reads the
-- job description and returns structured fields, then a SentenceTransformer
-- turns title+skills into a vector.
--
-- One row per job listing (job_listing_id is the primary key), so a
-- re-enrichment is an upsert, not a duplicate.
-- JSON columns are TEXT so the Python layer keeps treating values as strings.
CREATE TABLE job_enrichment (
    job_listing_id          VARCHAR(36)  NOT NULL PRIMARY KEY,
    skills                  TEXT         NULL,
    education               TEXT         NULL,
    education_requirement   TEXT         NULL,
    experience_years        INT          NULL,
    work_mode               VARCHAR(50)  NULL,
    benefits                TEXT         NULL,
    embedding               TEXT         NULL,
    embedding_model         VARCHAR(100) NULL,
    embedding_dim           SMALLINT     NULL,
    enriched_at             TIMESTAMPTZ  NULL,
    CONSTRAINT fk_enrichment_listing FOREIGN KEY (job_listing_id)
        REFERENCES job_listing (id) ON DELETE CASCADE
);


-- JobMatch --------------------------------------------------------------
-- Named JobMatch in M-02-09's description. One row per CV/listing pair.
CREATE TABLE job_match (
    id                  VARCHAR(36) NOT NULL PRIMARY KEY,
    cv_id               VARCHAR(36) NOT NULL,
    job_listing_id      VARCHAR(36) NOT NULL,
    match_score         DECIMAL(4,3) NOT NULL,
    matched_skills      TEXT        NULL,
    missing_categories  TEXT        NULL,
    rank_position       INT         NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL,
    UNIQUE (cv_id, job_listing_id),
    CONSTRAINT chk_match_score_range
        CHECK (match_score >= 0.000 AND match_score <= 1.000),
    CONSTRAINT chk_match_rank_positive
        CHECK (rank_position >= 1),
    CONSTRAINT fk_match_listing FOREIGN KEY (job_listing_id)
        REFERENCES job_listing (id) ON DELETE CASCADE
);
CREATE INDEX idx_match_cv_rank ON job_match (cv_id, rank_position);


-- JobseekerCV -----------------------------------------------------------
-- Maps a Jobseeker to the CVs they uploaded, so a "My CVs" picker can list
-- one person's uploads instead of everyone's.
CREATE TABLE jobseeker_cv (
    id                  VARCHAR(36)  NOT NULL PRIMARY KEY,
    jobseeker_id        VARCHAR(100) NOT NULL,
    cv_id               VARCHAR(36)  NOT NULL,
    original_filename   VARCHAR(500) NULL,
    uploaded_at         TIMESTAMPTZ  NOT NULL,
    UNIQUE (cv_id)
);
CREATE INDEX idx_jobseeker_recent ON jobseeker_cv (jobseeker_id, uploaded_at);
