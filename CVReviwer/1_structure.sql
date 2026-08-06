-- ---------------------------------------------------------------------
-- 1_structure.sql — the CVision database, tables only, no rows
--
--   mysqlsh --sql -u root -p -h localhost --file 1_structure.sql
--
-- Creates the database and all nine tables for Feature 1 (job fetching),
-- Feature 2 (job matching) and the Feature 5 groundwork. Inserts nothing:
-- run 2_data.sql afterwards, or the app will have no admin account to log
-- in with and no provider profile to create a scraper from.
--
-- *** DESTRUCTIVE — DROPS EVERY TABLE ***
-- Scraped listings, the activity log, match results and, most expensively,
-- the LLM extractions and embeddings in job_enrichment (roughly one
-- gpt-4o-mini call per listing to regenerate). Feature 3's CVs are not
-- affected: they live in cvs.json and uploads/, not in MySQL.
--
-- To add the Feature 2 tables to a database that already holds Feature 1
-- data, use schema_f2.sql instead — it touches only those three tables.
--
-- Definitions here are identical to schema_all.sql and to
-- schema.sql / schema_f2.sql; they were extracted from those files rather
-- than retyped. Change a column in one and you must change it in the
-- others, or delete the files you are not using.
-- ---------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS cvision
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE cvision;

-- Dropped children-first so the foreign keys unwind cleanly. The
-- FOREIGN_KEY_CHECKS guard makes the order academic, but an order that
-- would work without it is easier to reason about.
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS job_match;
DROP TABLE IF EXISTS job_enrichment;
DROP TABLE IF EXISTS jobseeker_cv;
DROP TABLE IF EXISTS log_entry;
DROP TABLE IF EXISTS job_listing;
DROP TABLE IF EXISTS schedule;
DROP TABLE IF EXISTS scraper;
DROP TABLE IF EXISTS provider_profile;
DROP TABLE IF EXISTS admin;
SET FOREIGN_KEY_CHECKS = 1;


-- =====================================================================
-- FEATURE 1 — Job fetching from external APIs
-- Tables defined by CVision_Data_Dictionary.docx.
-- =====================================================================

-- Admin -----------------------------------------------------------------
-- The password column is plaintext because admin.py's login gate is an
-- acknowledged stand-in: authentication is Feature #5 and outside this
-- refactor. The seeded password below is "123" for local development.
-- Replace the column, the gate, and that password before this is
-- reachable by anyone else.
CREATE TABLE admin (
    id        VARCHAR(36)  NOT NULL PRIMARY KEY,
    username  VARCHAR(100) NOT NULL UNIQUE,
    password  VARCHAR(255) NOT NULL
) ENGINE=InnoDB;


-- ProviderProfile -------------------------------------------------------
-- The five JSON columns are read back by scraper_service._decode_json_columns,
-- which handles either a JSON-typed value or a plain string, so TEXT works
-- equally well if your MySQL predates 5.7.
CREATE TABLE provider_profile (
    id             VARCHAR(36)  NOT NULL PRIMARY KEY,
    profile_name   VARCHAR(150) NOT NULL UNIQUE,
    url            TEXT         NOT NULL,
    query_params   JSON         NULL,
    headers        JSON         NULL,
    body_template  JSON         NULL,
    fields         JSON         NULL,
    field_map      JSON         NULL
) ENGINE=InnoDB;


-- Scraper ---------------------------------------------------------------
-- last_request_date is NULL until the first run. It is a real DATETIME,
-- never the "-" or "2026-06-09 20:12 UTC" strings the test cases show --
-- those are produced at the read boundary by
-- scraper_service.format_display_datetime().
CREATE TABLE scraper (
    id                 VARCHAR(36)  NOT NULL PRIMARY KEY,
    source_profile_id  VARCHAR(36)  NULL,
    website_name       VARCHAR(200) NOT NULL,
    description        TEXT         NULL,
    request            LONGTEXT     NOT NULL,
    field_map          JSON         NULL,
    last_request_date  DATETIME(3)  NULL,
    CONSTRAINT fk_scraper_profile FOREIGN KEY (source_profile_id)
        REFERENCES provider_profile (id) ON DELETE SET NULL
) ENGINE=InnoDB;


-- Schedule --------------------------------------------------------------
-- NOT IN THE DATA DICTIONARY: the UNIQUE (scraper_id) constraint. It is
-- required, not cosmetic -- scraper_service.persist_schedule() upserts with
-- INSERT ... ON DUPLICATE KEY UPDATE, which silently inserts a second row
-- instead of updating if scraper_id is not unique, and list_scrapers()'s
-- LEFT JOIN would then return duplicate scrapers. Every use of a schedule
-- in the code and the test cases treats it as one-per-scraper.
CREATE TABLE schedule (
    id             VARCHAR(36) NOT NULL PRIMARY KEY,
    scraper_id     VARCHAR(36) NOT NULL,
    mode           ENUM('fixed','recurring') NOT NULL,
    run_at         DATETIME(3) NULL,
    interval_type  ENUM('weekly','biweekly','monthly') NULL,
    enabled        BOOLEAN     NOT NULL DEFAULT TRUE,
    last_auto_run  DATETIME(3) NULL,
    UNIQUE KEY uq_schedule_scraper (scraper_id),
    CONSTRAINT fk_schedule_scraper FOREIGN KEY (scraper_id)
        REFERENCES scraper (id) ON DELETE CASCADE
) ENGINE=InnoDB;


-- JobListing ------------------------------------------------------------
-- DATETIME(3), not plain DATETIME: job_posted_date round-trips through
-- ISO-8601 with milliseconds ("2026-06-09T20:12:48.473Z" in UT-1-16-001),
-- and plain DATETIME would truncate the .473 away.
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
    job_details          LONGTEXT     NULL,
    job_employment_type  VARCHAR(100) NULL,
    job_posted_date      DATETIME(3)  NULL,
    salary               VARCHAR(200) NULL,
    outdated_manual      BOOLEAN      NOT NULL DEFAULT FALSE,
    KEY idx_listing_scraper (scraper_id),
    CONSTRAINT fk_listing_scraper FOREIGN KEY (scraper_id)
        REFERENCES scraper (id) ON DELETE SET NULL
) ENGINE=InnoDB;


-- LogEntry --------------------------------------------------------------
-- action mirrors the Data Dictionary's enum exactly (and log_service
-- .VALID_ACTIONS). Note "configure", "profile_create" and "profile_delete"
-- are in the enum but no M-method implements them -- see
-- TBD_and_Conflicts.md Part 3.
CREATE TABLE log_entry (
    id           VARCHAR(36) NOT NULL PRIMARY KEY,
    user_id      VARCHAR(36) NOT NULL,
    action       ENUM('add','edit','delete','configure','schedule','run','auto_run',
                      'profile_create','profile_delete','job_edit','job_mark','job_delete')
                 NOT NULL,
    target_name  VARCHAR(300) NULL,
    detail       TEXT         NULL,
    timestamp    DATETIME(3)  NOT NULL,
    KEY idx_log_time (timestamp),
    CONSTRAINT fk_log_admin FOREIGN KEY (user_id)
        REFERENCES admin (id) ON DELETE RESTRICT
) ENGINE=InnoDB;


-- =====================================================================
-- FEATURE 2 — Job matching  (+ Feature 5 groundwork)
-- job_enrichment and job_match hold data derived from Feature 1's
-- listings; jobseeker_cv is the CV-ownership index Feature 5 will own.
-- Created after the Feature 1 tables because two of them reference
-- job_listing.
-- =====================================================================

-- JobEnrichment ---------------------------------------------------------
-- The seven fields Feature 2 needs that Feature 1's job_listing does not
-- carry, because they are *derived* rather than scraped: an LLM reads the
-- job description and returns structured fields, then a SentenceTransformer
-- turns title+skills into a vector.
--
-- This lives in its own table rather than as new columns on job_listing
-- for two reasons: Feature 1's Data Dictionary is approved and adding
-- columns would reopen it, and the separation states plainly that this
-- data is inferred and can be regenerated, while job_listing holds what
-- the provider actually returned.
--
-- One row per job listing (job_listing_id is the primary key), so a
-- re-enrichment is an upsert, not a duplicate.
CREATE TABLE job_enrichment (
    job_listing_id          VARCHAR(36)  NOT NULL PRIMARY KEY,

    -- SRS-049: the skills each listing requires, compared against the CV's.
    -- JSON array of strings. Observed: up to 15 entries, longest 28 chars.
    skills                  JSON         NULL,

    -- SRS-050: qualification requirement, free text as the LLM returns it
    -- ("Bachelor's degree in Computer Engineering..."). Observed max ~100
    -- chars but TEXT since it is model output, not a bounded field.
    -- Populated for 9 of 14 sample listings -- SRS-058's weighting
    -- adjustment exists precisely because this is often absent.
    -- Kept for display and as a fallback: rows imported from the legacy
    -- jobs_with_embeddings.json have this and nothing structured.
    education               TEXT         NULL,

    -- The same requirement, parsed into structure at enrichment time:
    --   {"min_degree_level": "bachelor",
    --    "fields": ["computer science", "information technology"]}
    --
    -- NOT in the Feature 2 document -- see TBD_and_Conflicts.md. Added
    -- because parsing that free text at *match* time was measurably wrong:
    -- "Degree in Computer Sciences or equivalent" failed to match a
    -- Computer Science degree on a singular/plural mismatch, and a list of
    -- acceptable alternatives ("A, B, or C") was being scored as though all
    -- three were required at once. The model reads the sentence far better
    -- than a regex does, and it only runs once per listing rather than once
    -- per match. NULL for rows enriched before this column existed;
    -- compare_education falls back to parsing `education` in that case.
    education_requirement   JSON         NULL,

    -- SRS-051: minimum years of experience. Observed 1-3, or NULL when the
    -- listing does not state one (7 of 14 samples).
    experience_years        INT          NULL,

    -- onsite / remote / hybrid in every sample, but left VARCHAR rather
    -- than ENUM: the value is whatever the LLM returns, and an unexpected
    -- string should be stored and visible, not rejected mid-pipeline.
    work_mode               VARCHAR(50)  NULL,

    -- JSON array of strings; empty array in all current samples.
    benefits                JSON         NULL,

    -- English translation of the description, used for the fit explanation.
    -- Observed max 2,651 chars; LONGTEXT because Thai listings translated
    -- to English can run long and this is not a field to truncate.
    translated_description  LONGTEXT     NULL,

    -- The 384-float SentenceTransformer vector, ~8 KB of JSON per row.
    -- JSON rather than a vector type: MySQL 8.0 has none, the comparison
    -- is done in Python anyway, and at this scale a full scan is fine.
    embedding               JSON         NULL,

    -- NOT in the Feature 2 document -- see TBD_and_Conflicts.md.
    -- Cosine similarity between vectors from *different* models is
    -- meaningless, so the model that produced the vector has to travel
    -- with it. Without this, changing MODEL_NAME in embed.py would
    -- silently produce nonsense scores against previously embedded rows
    -- instead of an error. embedding_dim is stored for the same reason:
    -- a dimension mismatch is a cheap, definitive check before comparing.
    embedding_model         VARCHAR(100) NULL,
    embedding_dim           SMALLINT     NULL,

    enriched_at             DATETIME(3)  NULL,

    CONSTRAINT fk_enrichment_listing FOREIGN KEY (job_listing_id)
        REFERENCES job_listing (id) ON DELETE CASCADE
) ENGINE=InnoDB;


-- JobMatch --------------------------------------------------------------
-- Named JobMatch in M-02-09's description: "Persists the calculated and
-- ranked job match results to the JobMatch table, recording the match
-- score, matched skill tags, and any missing CV categories for each job
-- listing evaluated against the given CV."
--
-- Those three things are exactly what the columns below record. Per-category
-- sub-scores (skill/education/experience) were considered and deliberately
-- left out: no requirement asks for them, SRS-053 defines the displayed
-- breakdown as the matched skill tags, and adding unrequested columns to a
-- table the document names explicitly would be scope creep. They can be
-- added later if the UI needs a finer breakdown.
CREATE TABLE job_match (
    id                  VARCHAR(36) NOT NULL PRIMARY KEY,

    -- NOT a foreign key, deliberately. Feature 3 stores CVs in cvs.json,
    -- not MySQL, so there is no cvs table to reference. This is the visible
    -- cost of keeping Feature 3 untouched (see TBD_and_Conflicts.md Part 4):
    -- the database cannot enforce that a cv_id exists, and deleting a CV
    -- from cvs.json leaves orphaned matches behind. Feature 2's service
    -- layer is responsible for the integrity the schema cannot provide.
    -- Sized 36 to fit a UUID; Feature 3 currently writes 32-char hex.
    cv_id               VARCHAR(36) NOT NULL,

    job_listing_id      VARCHAR(36) NOT NULL,

    -- SRS-052: "a decimal value between 0.000 and 1.000". DECIMAL(4,3)
    -- gives exactly three decimals, and the CHECK enforces the range --
    -- DECIMAL(4,3) alone would happily store 9.999, so the precision
    -- expresses the requirement but does not enforce it. MySQL has
    -- enforced CHECK constraints since 8.0.16.
    -- Not FLOAT: the score is displayed and ranked on, so exact stored
    -- values beat binary rounding.
    match_score         DECIMAL(4,3) NOT NULL,

    -- SRS-053: the matched skills, rendered as tags on the job card.
    matched_skills      JSON        NULL,

    -- M-02-09's "missing CV categories": which of skills / education /
    -- experience the CV had no data for. This is also what drove the
    -- SRS-058 weighting adjustment for this score, so storing it makes a
    -- stored score explainable after the fact rather than a bare number.
    missing_categories  JSON        NULL,

    -- SRS-054: descending rank by score. Derivable with ORDER BY, but
    -- stored so a persisted result set reproduces the exact ordering the
    -- Jobseeker saw, including however ties happened to be broken.
    rank_position       INT         NOT NULL,

    computed_at         DATETIME(3) NOT NULL,

    -- One row per CV/listing pair. Makes re-running a match an upsert
    -- rather than an accumulation of duplicates, and lets the service
    -- layer replace a CV's results atomically.
    UNIQUE KEY uq_match_cv_listing (cv_id, job_listing_id),

    -- Ranked retrieval for one CV (M-02-10 displayJobMatchResults) is the
    -- only read pattern Feature 2 has.
    KEY idx_match_cv_rank (cv_id, rank_position),

    -- SRS-052's range, enforced rather than merely expressed.
    CONSTRAINT chk_match_score_range
        CHECK (match_score >= 0.000 AND match_score <= 1.000),

    -- SRS-054 ranks from highest to lowest; position 1 is the best match,
    -- so a zero or negative rank is a bug in the caller, not valid data.
    CONSTRAINT chk_match_rank_positive
        CHECK (rank_position >= 1),

    CONSTRAINT fk_match_listing FOREIGN KEY (job_listing_id)
        REFERENCES job_listing (id) ON DELETE CASCADE
) ENGINE=InnoDB;


-- JobseekerCV -----------------------------------------------------------
-- Maps a Jobseeker to the CVs they uploaded, so a "My CVs" picker can list
-- one person's uploads instead of everyone's.
--
-- A PLACEHOLDER FOR FEATURE 5. There is no authentication yet, so every
-- upload is currently attributed to the same stand-in jobseeker id
-- ("John Doe"). The table exists now so the rows accumulate from the first
-- upload onward and Feature 5 inherits a populated index rather than
-- starting empty. Feature 5 should own this table and add the FK to
-- whatever jobseeker/account table it introduces.
--
-- Neither column can be a foreign key today: jobseeker_id has no table to
-- reference until Feature 5 exists, and cv_id lives in Feature 3's cvs.json
-- rather than MySQL (see TBD_and_Conflicts.md Part 4). M-03-05 storeCVFile
-- already writes jobseekerId into the JSON record; this table is the
-- queryable index over the same fact, not a second source of truth -- if
-- they ever disagree, cvs.json is authoritative.
CREATE TABLE jobseeker_cv (
    id                  VARCHAR(36)  NOT NULL PRIMARY KEY,
    jobseeker_id        VARCHAR(100) NOT NULL,
    cv_id               VARCHAR(36)  NOT NULL,
    original_filename   VARCHAR(500) NULL,
    uploaded_at         DATETIME(3)  NOT NULL,

    -- One owner per CV; re-uploading the same file produces a new cv_id and
    -- therefore a new row.
    UNIQUE KEY uq_jobseeker_cv (cv_id),
    KEY idx_jobseeker_recent (jobseeker_id, uploaded_at)
) ENGINE=InnoDB;
