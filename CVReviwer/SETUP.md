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
cd E:\MyProject\CVReviwer
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
python -c "import pikepdf, PyPDF2, streamlit, mysql.connector, openai; print('all imports OK')"
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

## 4. MySQL

You need the **server**, not just Workbench or Shell — those are clients.
Check what is running:

```powershell
Get-Service *mysql* | Select-Object Name, Status
```

- A service listed as `Running` → continue.
- Listed but `Stopped` → `Start-Service MySQL80` from an elevated PowerShell.
- Nothing listed → install the MySQL Server component from
  dev.mysql.com/downloads/installer/. Keep port **3306**, set a root
  password, and let it install as a Windows service.

Confirm the port is actually open:

```powershell
Test-NetConnection -ComputerName localhost -Port 3306
```

`TcpTestSucceeded : True` means you are ready.

---

## 5. Create the database

Two files: tables first, then the data.

```powershell
mysqlsh --sql -u root -p -h localhost --file 1_structure.sql
mysqlsh --sql -u root -p -h localhost --file 2_data.sql
```

`1_structure.sql` creates nine tables and inserts nothing.

`2_data.sql` fills them with a working system: the admin account, the
LinkedIn and Indeed provider profiles, two already-configured scrapers, 20
real job listings captured from those providers, and 22 activity-log
entries. You do not have to scrape anything to have data to work with.

> **`2_data.sql` contains live API credentials.** Each scraper's stored curl
> command includes the BrightData key — that is what makes the scrapers work
> on restore. Do not commit the file or send it to anyone. To share the
> project, run `python export_sample.py`, which redacts the keys and reports
> how many it redacted so you can check the result.

**Both files are destructive.** `1_structure.sql` drops every table.
`2_data.sql` clears each table it fills — including `job_enrichment`, which
is cleared explicitly at the top because `job_listing` cascades to it. That
enrichment costs an OpenAI call per listing to regenerate (step 7), so
re-running `2_data.sql` afterwards is not free.

Verify:

```powershell
mysqlsh --sql -u root -p -h localhost -e "USE cvision; SHOW TABLES; SELECT COUNT(*) AS listings FROM job_listing;"
```

Nine tables — `admin`, `provider_profile`, `scraper`, `schedule`,
`job_listing`, `log_entry`, `job_enrichment`, `job_match`, `jobseeker_cv` —
and 20 listings.

## 6. Configuration

Create a file named `.env` beside `app.py`:

```
OPENAI_API_KEY=sk-your-key-here

DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your-mysql-root-password
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

## 7. Enrich the listings so matching works

You already have 20 listings from step 5, but the jobseeker panel will show
no matches yet. Matching compares a CV against each listing's **extracted
skills**, and those are produced separately from scraping — a listing with no
enrichment row is invisible to matching by design, because there is nothing
to compare against.

```powershell
python enrich_jobs.py
```

That calls OpenAI once per listing (20 calls) to extract skills, education and
experience requirements, then embeds each one. It takes a couple of minutes.

Now upload a CV on the jobseeker panel and you will get ranked matches.

**Making this free next time.** Once enrichment has run, re-dump the data file
with `job_enrichment` included and future restores need no API calls at all —
the embeddings come back from SQL:

```powershell
mysqldump -u root -p --no-create-info --default-character-set=utf8mb4 `
    cvision admin provider_profile scraper job_listing log_entry job_enrichment `
    --result-file=2_data.sql
```

**Scraping more listings.** Use the admin panel: **Create** to build a scraper
from a provider profile, then **▶ Run** on the Scrapers tab. Any newly scraped
listing needs `python enrich_jobs.py` again — it only processes listings that
have no enrichment yet, so re-running it is cheap and safe.

## 8. Check the wiring

```powershell
python verify_integration.py --no-ai
```

Fifteen checks from database connectivity to the CV pipeline, each naming the
method it exercises. `--no-ai` skips the steps that cost API calls; drop it to
test the OpenAI path too.

Everything should pass, including **enrichment coverage** at `20/20` and
**active listings for matching** at 19 — the twentieth listing is more than
365 days old and is filtered out by the SRS-029 rule, which is correct.

If the database checks fail, the `DB_*` values in `.env` are wrong or MySQL is
not running. If enrichment coverage is below 20, step 7 did not finish — run
`python enrich_jobs.py` again; it only picks up what is still missing.

## 9. Run it

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

## 10. Pin what works

Once everything runs, capture the exact versions:

```powershell
pip freeze > requirements.lock.txt
```

This matters most for `sentence-transformers`: a different release can produce
different embeddings, and vectors from two models are not comparable — scores
would shift quietly rather than fail.

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