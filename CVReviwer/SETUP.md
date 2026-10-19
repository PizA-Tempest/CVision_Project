# CVision — first-time setup

Windows / PowerShell. Roughly 20 minutes, most of it waiting on downloads.

At the end you will have one Streamlit app serving two panels: the jobseeker
panel at `localhost:8501` and the admin panel at `localhost:8501/?page=admin`.

---

## 1. Python

Python **3.10, 3.11 or 3.12**. Not 3.13 or newer yet — `pikepdf` and
`sentence-transformers` do not always have prebuilt wheels for the newest
release, and without a wheel `pip` tries to compile `pikepdf` from source,
which needs the qpdf C++ library and a compiler you almost certainly do not
want to install.

```powershell
python --version
```

If that reports 3.13+, install 3.12 from python.org alongside it and use
`py -3.12` in place of `python` throughout this guide.

---

## 2. Virtual environment

Not strictly required, but it keeps this project's packages away from
everything else on the machine — `sentence-transformers` alone pulls in
PyTorch, which is large.

```powershell
cd CVReviwer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the activation script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Your prompt should now start with `(.venv)`. Re-activate it in every new
terminal before running anything below.

---

## 3. Python packages

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The upgrade first is not superstition: an old `pip` may not recognise the
wheel tags for your Python version, decide no wheel exists, and fall back to
building `pikepdf` from source. That is the usual cause of a `pikepdf`
install failure on Windows.

Expect a few hundred MB — `sentence-transformers` brings PyTorch with it.

**Check it worked:**

```powershell
python -c "import pikepdf, PyPDF2, streamlit, psycopg2, openai; print('all imports OK')"
```

<details>
<summary>If <code>pikepdf</code> fails to install</summary>

The error usually mentions `qpdf`, `cmake`, or "Microsoft Visual C++ 14.0 or
greater is required" — all of which mean pip is compiling instead of
downloading a wheel.

1. Confirm 64-bit Python: `python -c "import platform; print(platform.architecture())"` should say `64bit`. A 32-bit install has no wheels.
2. Confirm the version is 3.10–3.12.
3. Force a wheel so it fails loudly instead of trying to compile:
   `pip install --only-binary :all: pikepdf`

`pikepdf` is not optional — Feature 3 uses it to verify that an uploaded PDF
is not corrupt (M-03-04 `validateCVFile`), and CV upload will not work
without it.
</details>

---

## 4. Database (Supabase free tier)

The app uses **PostgreSQL** via Supabase (free). Aiven is no longer used.

1. Create a free project at [supabase.com](https://supabase.com).
2. Open **Project Settings → Database → Connection string → URI**.
3. Copy the URI into `.env` as `DATABASE_URL` (see section 6).

For local development without Supabase, install PostgreSQL and use the
`DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` fallbacks in
`.env` instead.

---

## 5. Create the database

Run the SQL files in the Supabase **SQL Editor**, or with `psql`:

```powershell
psql "$env:DATABASE_URL" -f 1_structure.sql
psql "$env:DATABASE_URL" -f 2_data.sql
```

`1_structure.sql` creates nine tables and inserts nothing.

`2_data.sql` fills them with a working system: the admin account, the
LinkedIn and Indeed provider profiles, two already-configured scrapers, 20
real job listings captured from those providers, 22 activity-log entries, and
the enrichment rows for all 20 listings. You do not have to scrape anything to
have data to work with, and you do not have to enrich anything to get matches
— **the setup below makes no OpenAI calls at all.**

> **`2_data.sql` contains live API credentials.** Each scraper's stored curl
> command includes the BrightData key — that is what makes the scrapers work
> on restore. Do not commit the file or send it to anyone. To share the
> project, run `python export_sample.py`, which redacts the keys and reports
> how many it redacted so you can check the result.

**Both files are destructive.** `1_structure.sql` drops every table.
`2_data.sql` clears each table it fills before refilling it, so re-running it
replaces rows rather than duplicating them. It also clears `job_match`, so any
stored rankings are discarded and recomputed on the next CV upload — free, but
worth knowing.

If you have scraped listings of your own, re-running `2_data.sql` throws them
away along with their enrichment. Bake yours into the file first — see
[Scraping and enriching new listings](#scraping-and-enriching-new-listings).

Verify:

```powershell
psql "$env:DATABASE_URL" -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
psql "$env:DATABASE_URL" -c "SELECT COUNT(*) AS listings FROM job_listing; SELECT COUNT(*) AS enriched FROM job_enrichment;"
```

Nine tables — `admin`, `provider_profile`, `scraper`, `schedule`,
`job_listing`, `log_entry`, `job_enrichment`, `job_match`, `jobseeker_cv` —
20 listings, and 20 enriched.

## 6. Configuration

Create a file named `.env` beside `app.py`:

```
OPENAI_API_KEY=sk-your-key-here

# Supabase (preferred)
DATABASE_URL=postgresql://postgres:[password]@aws-0-xxx.pooler.supabase.com:5432/postgres

# Or local Postgres fallback
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your-postgres-password
DB_NAME=cvision
```

**Never commit this file.** Add `.env` to `.gitignore` before the first
commit — it holds a billable API key and your database password.

Create `.streamlit/config.toml` so uploads match the 20 MB limit Feature 3
enforces server-side:

```toml
[server]
maxUploadSize = 20
```

---

## 7. Check the wiring

```powershell
python verify_integration.py --no-ai
```

Fifteen checks from database connectivity to the CV pipeline, each naming the
method it exercises. `--no-ai` skips the steps that cost API calls; drop it to
test the OpenAI path too.

Everything should pass, including **enrichment coverage** at `20/20` and
**active listings for matching** at 19 — the twentieth listing is more than
365 days old and is filtered out by the SRS-029 rule, which is correct.

If the database checks fail, `DATABASE_URL` (or the `DB_*` values) in `.env` are wrong or the database is unreachable. If enrichment coverage is below 20, `2_data.sql` did not finish —
re-run it rather than reaching for `enrich_jobs.py`, which would spend API
calls regenerating rows the file already contains.

## 8. Run it

```powershell
streamlit run app.py
```

| Panel | URL | Login |
|---|---|---|
| Jobseeker | http://localhost:8501 | none |
| Admin | http://localhost:8501/?page=admin | `admin` / `123` |

One process serves both — `app.py` checks the `page` query parameter and hands
off to the admin panel when it sees `page=admin`.

To run the admin panel on its own port instead, useful for keeping both open
side by side:

```powershell
streamlit run admin.py --server.port 8502
```

The password `123` is stored and compared in plaintext. Authentication is
Feature 5 and does not exist yet; this is a local-development stand-in and
must not survive to anything reachable by anyone else.

---

## 9. Pin what works

Once everything runs, capture the exact versions:

```powershell
pip freeze > requirements.lock.txt
```

This matters most for `sentence-transformers`: a different release can produce
different embeddings, and vectors from two models are not comparable — scores
would shift quietly rather than fail.

That is the whole setup. Everything below is optional — none of it is needed
to run the system, and both sections cost nothing to skip.

---

## Running the tests

```powershell
python tests/run_all_tests.py
```

Expect **Feature 2: 110 pass**, **Feature 3: 123 pass, 1 fail, 1 skip**. That
one failure and one skip are known, pre-existing issues in Feature 3
(UT-3-11-004 and UT-3-12-003, a US-centric phone regex) and are its recorded
baseline — the runner warns if Feature 3 moves away from it, which would mean
approved code was disturbed.

---

## Scraping and enriching new listings

The 20 seeded listings arrive already enriched, so this is only for listings
**you** scrape. It is the one part of the project that spends OpenAI credit.

### 1. Scrape — enrichment usually happens for you

Admin panel → **Create** to build a scraper from a provider profile, then
**▶ Run** on the Scrapers tab.

**A manual ▶ Run enriches the new listings automatically.** The Scrapers tab
carries an *Enrich new listings automatically after a run* toggle, on by
default, and the run fires it once the "N new jobs" message is on screen. You
normally have nothing to do at this step beyond waiting.

Why it matters that it happens at all: a listing with no enrichment row is
**invisible to matching**. Matching compares a CV against each listing's
extracted skills, qualification and experience requirements, and those are
derived by a separate AI pass — scraping only stores the listing's raw text,
so there is nothing to compare against until enrichment has run.

Two cases where it does *not* happen on its own:

- **Scheduled auto-runs.** A run started by a schedule saves its listings but
  does not enrich them.
- **The toggle turned off**, or an enrichment that failed part-way — a bad API
  key, no credit, a network drop. The listings are still saved either way;
  only the enrichment is missing.

Whenever listings are outstanding, the Scrapers tab says so — *"N job
listing(s) have not been enriched yet"* — with a button to run it there and
then. That panel is the thing to watch, not the run message.

### 2. Enrich anything left over

Only needed when the panel reports a backlog:

```powershell
python enrich_jobs.py
```

One `gpt-4o-mini` call per listing to extract skills, education and experience
requirements, then a local embedding pass over each. It only processes
listings that have no enrichment yet, so re-running it is cheap and safe —
nothing already enriched is paid for twice. Add `--force` to redo everything,
`--limit 5` to try a handful first.

The script and the admin button do the same work; the script is the one to
reach for when you are not sitting in front of the panel, or when a run left
a backlog you would rather clear from the terminal.

### 3. Bake the result into `2_data.sql`

Otherwise the next `2_data.sql` restore wipes both the listings and the
enrichment you just paid for.

```powershell
python refresh_enrichment_data.py --check    # report only, writes nothing
python refresh_enrichment_data.py            # rewrite 2_data.sql
```

It dumps three tables — `job_listing`, `log_entry`, `job_enrichment` — and
rewrites only those three regions of `2_data.sql`, each delimited by
`>>> BEGIN <table>` / `<<< END <table>` markers. The hand-written seed rows
(`admin`, `provider_profile`, `scraper`) and their comments are left alone.
The previous version is kept as `2_data.sql.bak`.

**Safe to re-run as often as you like.** Regions are matched by marker and
replaced, never appended twice, so the tenth run produces the same shape as
the first.

**The three tables are refreshed together, and have to be.**
`job_enrichment.job_listing_id` is a foreign key to `job_listing.id`, and
`2_data.sql` re-enables `FOREIGN_KEY_CHECKS` before any INSERT runs. Dumping
the enrichment on its own would give you a file whose enrichment rows point at
listings the file does not contain — which restores fine on your machine,
because those listings are already in your database, and fails on a clean
install. `log_entry` comes along because scraping writes to it.

The full loop, then:

```powershell
# scrape in the admin panel — a manual run enriches as it goes
python enrich_jobs.py            # only if the panel still reports a backlog
python verify_integration.py --no-ai
python refresh_enrichment_data.py --check
python refresh_enrichment_data.py
```

Note `enrich_jobs.py` without `--force`. It only processes listings that have
no enrichment row, so it picks up exactly the new ones and does nothing at all
when the admin panel has already enriched them. `--force` re-does every
listing — paid API calls to regenerate rows you already have — and is only for
when the prompt or the schema has changed.

### 4. Prove the new file works

The point of the exercise, and free:

```powershell
psql "$env:DATABASE_URL" -f 1_structure.sql
psql "$env:DATABASE_URL" -f 2_data.sql
python verify_integration.py --no-ai
```

Enrichment coverage should come back full with no API calls made.

### Two guards worth knowing about

The script refuses to write, rather than writing something that breaks later:

- **Schema drift.** If your database's columns do not match `1_structure.sql`,
  nothing is written. The case this was built for: a database created before
  `translated_description` was dropped still has that column, and a dump
  carrying it restores cleanly on your machine and fails everywhere else. Run
  `drop_translated_description.sql`, then `python enrich_jobs.py --force`.
- **More enrichment rows than listings**, which means the two are out of step
  and a restore would hit the foreign key error described above.

It also *warns* — but still writes — when some listings have no enrichment
row, since shipping them un-enriched is occasionally what you want. They will
be invisible to matching until enriched.

### If `refresh_enrichment_data.py` cannot reach the database

The script dumps rows through `db.query()` using `DATABASE_URL` / `DB_*`
from `.env`. There is no separate dump binary to install.

---

## Known limitations

- **Masking is partial.** CV text is masked before being sent to OpenAI, but
  Feature 3's detection only reliably catches emails and ID numbers. Thai
  phone numbers and addresses pass through unmasked. Feature 3's own test
  results record part of this; see `TBD_and_Conflicts.md` Part 4.
- **No authentication.** Every upload is attributed to a stand-in jobseeker,
  so the "My CVs" list shows everyone's uploads. Feature 5.
- **Two approved methods are placeholders.** M-03-07 and M-03-14 return empty
  results; `app.py` performs the real AI call in their place and feeds the
  result into the rest of the documented chain.