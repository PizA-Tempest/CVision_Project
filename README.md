# CVision

A CV-matching system with a jobseeker panel and an admin panel in a single Streamlit app.

- **Jobseeker panel** — `http://localhost:8501` — upload a CV and get ranked job matches.
- **Admin panel** — `http://localhost:8501/?page=admin` — login `admin` / `123` — manage scrapers, providers, schedules, and activity logs.

The project code lives in the [`CVReviwer/`](CVReviwer/) folder.

---

## Prerequisites

| Tool | Requirement |
|---|---|
| **Python** | **3.10, 3.11 or 3.12** (not 3.13+ — `pikepdf` / `sentence-transformers` lack wheels and pip will try to compile them) |
| **MySQL Server** | Port 3306, installed as a Windows service |
| **Node.js** | Only if you need the `@xenova/transformers` / `pdf-parse` packages from `package.json` — the Python app itself does not use them |

---

## 1. Clone

```powershell
git clone https://github.com/PizA-Tempest/CVision_Project.git
cd CVision_Project\CVReviwer
```

## 2. Virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the activation script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Re-activate the environment in every new terminal.

## 3. Install Python packages

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

This pulls in streamlit, mysql-connector-python, pikepdf, PyPDF2, openai, python-dotenv, sentence-transformers (with PyTorch), tqdm, requests, and torchvision — expect a few hundred MB.

Verify:

```powershell
python -c "import pikepdf, PyPDF2, streamlit, mysql.connector, openai; print('all imports OK')"
```

If `pikepdf` fails to install, see [`CVReviwer/SETUP.md`](CVReviwer/SETUP.md) §3.

## 4. Node packages (optional)

Only needed if you use the JS packages from `package.json`; the Python app does not require them.

```powershell
npm install
```

## 5. Start MySQL and create the database

Make sure the MySQL service is running and port 3306 is open:

```powershell
Get-Service *mysql* | Select-Object Name, Status
Test-NetConnection -ComputerName localhost -Port 3306
```

Then create the schema and seed data:

```powershell
mysqlsh --sql -u root -p -h localhost --file 1_structure.sql
mysqlsh --sql -u root -p -h localhost --file 2_data.sql
```

Both files are destructive (they drop/clear tables). **`2_data.sql` contains live API credentials — do not share it.**

## 6. Configure `.env`

Create a file named `.env` beside `app.py`:

```
OPENAI_API_KEY=sk-your-key-here

DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your-mysql-root-password
DB_NAME=cvision
```

**Never commit this file** — it holds a billable API key and your DB password.

Also create `.streamlit/config.toml` (20 MB upload limit):

```toml
[server]
maxUploadSize = 20
```

## 7. Enrich listings so matching works

```powershell
python enrich_jobs.py
```

This calls OpenAI once per listing to extract skills/education/experience, then embeds each listing. Re-run it after scraping new listings; it only processes ones without enrichment.

## 8. Verify and run

```powershell
python verify_integration.py --no-ai
streamlit run app.py
```

Full step-by-step setup, troubleshooting, tests, and known limitations: [`CVReviwer/SETUP.md`](CVReviwer/SETUP.md).

| Panel | URL | Login |
|---|---|---|
| Jobseeker | http://localhost:8501 | none |
| Admin | http://localhost:8501/?page=admin | `admin` / `123` |
