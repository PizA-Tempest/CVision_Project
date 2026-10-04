# Feature #5: Authentication — URS / SRS / Use Case UC-008

> Synced 2026-10-04 to `URS Feature#5.md` (URS-010→017 / SRS-077→091) and to the
> current code (`auth_service.py`, `app.py`, `admin.py`, `cv_data_adapter.py`,
> `1_structure.sql`). The SRS-063→087 numbering used previously is superseded.
> Persistent login (`auth_session`, `auth_token`/`admin_token`) is retained as an
> implemented extension — it is not in SRS-077→091 but logout revokes it per SRS-088.

## 1. User Requirements (URS)

**URS-010:** Jobseekers can register their own account, with the system checking that the chosen username or email is not already taken, so their CVs and results are saved under their own account.

* SRS-077: The system shall validate registration format before checking for duplicates: username 3–30 characters (`[A-Za-z0-9_.-]`), email in standard email format with maximum 255 characters, and password 8–64 characters (length only — no blocklist, no forced complexity mix).
* SRS-078: The system shall check at registration that the submitted username and email do not already exist in the Jobseeker records before creating the account, and shall display an inline error without submitting the form if either is already registered.

**URS-011:** Jobseekers and administrators can log in with their own credentials to access their account or the admin page.

* SRS-079: The system shall provide an administrator login with its own username and password credentials, verified independently of any Jobseeker credentials. The dedicated admin login page shall not expose Jobseeker-facing navigation. The Jobseeker login form never checks admin credentials.
* SRS-080: The system shall authenticate a Jobseeker login by matching the supplied identifier (username or email in the same field) and verifying the password against its stored hash, and shall authenticate an Administrator login by verifying the submitted credentials against the stored administrator credential hash.
* SRS-081: The system shall show "Log in" and "Sign up" options to an unauthenticated Guest, and once authenticated shall replace them with the Jobseeker's profile, which opens a popover showing the display name, email, "Change name", "Change password" and "Log out".

**URS-012:** Jobseekers and administrators want the system to keep their passwords private and protected.

* SRS-082: The system shall store every Jobseeker and Administrator password as a salted hash (`pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`, 260k iterations) and shall never store or log a plaintext password.
* SRS-083: The system shall verify passwords with constant-time comparison and shall return a generic failure (no account-enumeration detail) on mismatch.

**URS-013:** Guests can view the CV upload section without creating an account, but must log in or register before they can upload a CV.

* SRS-084: The system shall keep the CV upload section visible to a Guest, but selecting the upload control shall open the login/register popup instead of accepting the file, and the picked file shall be discarded and never processed.
* SRS-085: The system shall reject a CV upload request that lacks a valid authenticated Jobseeker session, regardless of what the UI displayed (`require_jobseeker()` + `process_cv()` guard).

**URS-014:** Jobseekers can view their own uploaded CVs, analysis results, and job matches, kept under their own account and not visible to other users.

* SRS-086: The system shall show the "My CVs" view only the CVs uploaded by the currently authenticated Jobseeker, newest first, limited to the 20 most recent, and only CVs that actually parsed.
* SRS-087: The system shall record the authenticated Jobseeker's ID as the owner of every uploaded CV, shall use that ID to filter the CVs, analysis results, and match results returned to that Jobseeker, and shall reject any CV ID owned by another Jobseeker.

**URS-015:** Jobseekers and administrators can log out of their account to end their session securely.

* SRS-088: The system shall end the active session when a Jobseeker or Administrator logs out and shall clear the session state (Jobseeker: `jobseeker_id/name/email`, CV/view keys, `auth_token` revoked via `delete_session()`; Admin: `admin_authenticated/admin_user`, `page`/`admin_token` cleared).

**URS-016:** Jobseekers can change their password while signed in and reset a forgotten password without an email server.

* SRS-089: The system shall allow a signed-in Jobseeker to change their password by supplying the correct current password and a new password (8–64 characters, not on the blocklist, different from the old one), and shall store only the new salted hash. Wrong current password yields a generic failure and changes nothing.
* SRS-090: The system shall provide a forgotten-password reset that requires the username and the matching account email on the same account, plus new-password confirmation that must match, and on success shall store only the new salted hash. Confirmation is enforced in the service (`reset_jobseeker_password(..., new_password_confirmation)`), not only in the UI.

**URS-017:** Jobseekers can change their username while signed in.

* SRS-091: The system shall allow a signed-in Jobseeker to change their username via "Change name". The new name shall follow the registration rule (3–30 characters, `[A-Za-z0-9_.-]`), must not duplicate another account, and shall update the session display name immediately on success. Submitting the current unchanged username shall succeed without a database write and return the existing account.

> Deliberate deltas vs the previous revision: registration enforces length-only
> (blocklist applies to change/reset new passwords only); email max-255 is enforced;
> reset confirmation is a required service parameter; the Jobseeker login popup no
> longer accepts administrator credentials (strict SRS-079 — admins use `?page=admin`).

---

## 2. Outbound / Out-of-Scope

### 2.1 Outbound interfaces (what this feature sends out)

| ID | Outbound target | Content | Notes |
|----|-----------------|---------|-------|
| OUB-01 | MySQL `jobseeker` table | `id, username, email, password_hash, created_at` | Created by `1_structure.sql` and `ensure_auth_tables()`; `username` + `email` UNIQUE |
| OUB-02 | MySQL `admin` table | Upgraded `password` hash on legacy login | Best-effort `UPDATE`; login succeeds even if upgrade fails |
| OUB-03 | MySQL `jobseeker_cv` index + `cvs.json` | `jobseeker_id` as CV owner | Authoritative owner = `cvs.json:jobseekerId`; index is queryable copy |
| OUB-04 | Streamlit session state + URL query params | `jobseeker_id/name/email`, `admin_authenticated/admin_user`, `auth_token` / `admin_token` | Cleared on logout per SRS-088 (implemented extension for refresh persistence) |
| OUB-05 | Admin activity log (`log_service.set_current_user`) | Admin id/username on admin login | Best-effort; failure does not block login |
| OUB-06 | MySQL `auth_session` table | `token, jobseeker_id, admin_id, created_at, expires_at` (30-day expiry) | Created by `ensure_auth_tables()` only (not in `1_structure.sql`); expired rows deleted best-effort (implemented extension) |

### 2.2 Out of scope — explicitly NOT in Feature #5

| ID | Exclusion | Rationale |
|----|-----------|-----------|
| OUT-01 | No emailed reset links / SMTP | Reset uses username+email match + confirmation (SRS-090) |
| OUT-02 | No OAuth / SSO / social login | Username-or-email + password only (SRS-080) |
| OUT-03 | No MFA / CAPTCHA / account lockout / password expiry | Generic failure only (SRS-083) |
| OUT-04 | No role-based permissions beyond Jobseeker vs Admin | Admin routes gated by `admin_authenticated` only |
| OUT-05 | No plaintext password logging or recovery | Hashes only; forgotten password = reset, never retrieval (SRS-082) |
| OUT-06 | No cross-account visibility | Enforced server-side (SRS-085/087), not just UI hiding |
| OUT-07 | No password-policy change from strength meter | Register-form meter (`_pw_strength`) is UI-only; policy is SRS-077 |

---

## 3. Traceability (URS → SRS → code)

| URS | SRS | Implements |
|-----|-----|------------|
| URS-010 | SRS-077, SRS-078 | `auth_service.validate_registration()`, `check_registration_password()`, `is_username_taken()`, `is_email_taken()`, `register_jobseeker()`, `app._render_register_form()` |
| URS-011 | SRS-079, SRS-080, SRS-081 | `auth_service.authenticate_jobseeker()`, `authenticate_admin()`, `app._render_login_form()`, `admin.show_admin_page()` / `admin._authenticate()` |
| URS-012 | SRS-082, SRS-083 | `auth_service.hash_password()`, `verify_password()` |
| URS-013 | SRS-084, SRS-085 | `app` uploader guest-popup + discard, `auth_service.require_jobseeker()`, `app.process_cv()` guard |
| URS-014 | SRS-086, SRS-087 | `cv_data_adapter.list_cv_ids_for()`, `record_cv_ownership()`, `app` My-CVs list + foreign-ID reject |
| URS-015 | SRS-088 | `app._login_success()`, `app._logout()`, `admin` logout block, `auth_service.delete_session()` (+ persistent-token revocation) |
| URS-016 | SRS-089, SRS-090 | `auth_service.change_jobseeker_password()`, `reset_jobseeker_password()` (with confirmation), `app._change_password_dialog()`, `app._render_forgot_form()` |
| URS-017 | SRS-091 | `auth_service.change_jobseeker_username()`, `app._change_name_dialog()` (profile popover → Edit profile) |

---

## 4. Use Case UC-008 — Register, Log In, and Manage Session Access

**Use Case ID:** UC-008

**Use Case Name:** Register, Log In, and Manage Session Access

**Date Created:** 25/09/2026

**Last Revision Date:** 04/10/2026 — renumbered to SRS-077→091 per `URS Feature#5.md`; registration length-only + email max-255; reset confirmation enforced in service; Jobseeker login no longer accepts admin credentials (strict SRS-079)

**Actors:** Jobseeker, Guest, Administrator, System

**Description:** An unauthenticated Guest can view the CV upload section but must register or log in before uploading a CV (URS-013). A Guest registers with username, email, password; the system validates format first, then checks username/email uniqueness (URS-010). Jobseekers log in with username-or-email; administrators log in separately on the dedicated admin page (URS-011). Passwords are salted hashes verified in constant time (URS-012). A Jobseeker sees only their own CVs, analysis, and matches (URS-014), can log out securely (URS-015), change/reset passwords (URS-016), and change their username (URS-017).

**Trigger:** A Guest chooses to register, log in, or attempts to upload a CV without an account; or an Administrator chooses to log in through the admin login page.

**Preconditions:**

1. The system is available and reachable.
2. For login, the user already holds a registered Jobseeker account or valid administrator credentials.

**Use Case Input Specification:**

| Input | Type | Constraint | Example |
| ----- | ---- | ---------- | ------- |
| username | String | Required for registration; 3–30 chars `[A-Za-z0-9_.-]`; must not already exist [SRS-077, SRS-078] | "alice_j" |
| email | String | Required for registration; valid email format, max 255 chars; must not already exist [SRS-077, SRS-078] | "alice@example.com" |
| password | String | Required for registration; 8–64 chars (length only); stored only as salted hash [SRS-077, SRS-082] | "••••••••" |
| identifier | String | Required for Jobseeker login; username or email, same field [SRS-080] | "alice_j" |
| admin_username | String | Required for administrator login; dedicated page only, never the Jobseeker form [SRS-079] | "admin" |
| admin_password | String | Required for administrator login; verified against stored admin hash [SRS-080] | "••••••••" |
| current_password | String | Required for password change; must verify against stored hash [SRS-089] | "••••••••" |
| new_password | String | Required for change/reset; 8–64 chars, not blocklisted; must differ from old on change [SRS-089, SRS-090] | "••••••••" |
| new_password_confirmation | String | Required for reset; must match new_password — enforced in service [SRS-090] | "••••••••" |
| new_username | String | Required for name change; 3–30 chars `[A-Za-z0-9_.-]`, must not duplicate; unchanged accepted without write [SRS-091] | "alice_j2" |

**Postconditions:**

1. A new Jobseeker account is created only if format is valid and username/email were not already taken [SRS-077, SRS-078].
2. Every Jobseeker and Administrator password is stored only as a salted hash [SRS-082].
3. An authenticated Jobseeker session is scoped so CVs, analysis, and matches return only to the owner; foreign CV IDs are rejected [SRS-087].
4. An Administrator is authenticated only through administrator credentials on the dedicated page [SRS-079, SRS-080].
5. A CV upload is accepted only with a valid Jobseeker session; a Guest-picked file is discarded, never processed [SRS-084, SRS-085].
6. On logout the session ends and session state is cleared (tokens revoked) [SRS-088].
7. A changed/reset password replaces the old hash with a new salted hash [SRS-089, SRS-090].
8. A username change follows registration rules and updates the session display name immediately [SRS-091].

**Normal Flows:**

| Jobseeker / Guest | System |
| ----------------- | ------ |
| 1. Guest views the CV upload section without an account. | 2. Displays the upload section to the Guest [SRS-084]. |
| 3. Guest selects the upload control. | 4. Opens the login/register popup instead of accepting the file; discards the picked file, never processes it [SRS-084]. |
| 5. Guest submits username, email, password on the registration form. | 6. Validates format first [SRS-077]; then checks username/email uniqueness [SRS-078]. |
|  | 7. Creates the account, storing only a salted hash [SRS-082]. |
| 8. Enters username or email + password in the Jobseeker login form [SRS-080]. | 9. Matches the identifier and verifies against the stored hash with constant-time comparison; generic failure on mismatch [SRS-080, SRS-083]. |
|  | 10. Establishes the Jobseeker session; replaces "Log in"/"Sign up" with the profile popover (display name, email, Change name / Change password / Log out) [SRS-081]. |
| 11. Uploads a CV and views "My CVs". | 12. Records the Jobseeker ID as owner; filters "My CVs" (newest first, max 20, parsed only), analysis, and matches to that ID; rejects foreign CV IDs [SRS-086, SRS-087]. |
| 13. Selects Log Out. | 14. Ends the session, revokes the token, clears state; restores "Log in"/"Sign up" [SRS-088]. |

**Alternative Flows:**

[A6: Duplicate Username or Email]
A7: Submitted username or email already exists.
A8: Form shows an inline error without submitting; no account created [SRS-078].
A9: Returns to Step 5.

[A5b: Bad Format]
A5b-1: Username, email, or password fails format/length (incl. email >255) [SRS-077].
A5b-2: Form shows a validation message; no duplicate check runs; no account created.
A5b-3: Returns to Step 5.

[B1: Administrator Login]
B2: Administrator opens the dedicated admin login page (no Jobseeker navigation) [SRS-079].
B3: Submits admin_username + admin_password.
B4: System verifies against the stored admin hash, independently of Jobseeker credentials, with constant-time comparison [SRS-080, SRS-083]; upgrades legacy plaintext once.
B5: Establishes an admin session restricted to admin routes [SRS-079].
B6: Administrator selects Log Out; system ends the session and clears state [SRS-088].

[C1: Change Password]
C2: Signed-in Jobseeker submits current + new password.
C3: System verifies current hash, rejects new outside 8–64 / blocklisted / same-as-old, stores new hash only [SRS-089]. Wrong current → generic failure, changes nothing.
C4: Returns to Step 11.

[D1: Forgot-Password Reset]
D2: Guest submits username + account email + new password + confirmation.
D3: System requires username and email on the same account and confirmation match, then stores the new hash only [SRS-090]. Mismatch → generic failure, changes nothing.
D4: Returns to Step 8.

[H1: Change Display Name] (URS-017)
H2: Signed-in Jobseeker opens profile popover → "Change name" and submits a new name.
H3: System validates format [SRS-091], accepts the unchanged name without a write, rejects duplicates, otherwise updates the row and the session display name immediately.
H4: Returns to Step 11.

**Exception Flows:**

[E9: Invalid Login Credentials]
E10: No matching account, or password does not match the stored hash.
E11: System shows "invalid username/email or password" with no enumeration detail [SRS-083].
E12: Returns to Step 8.

[F4: Upload Bypasses the UI Prompt]
F5: A CV upload request arrives without a valid authenticated Jobseeker session.
F6: System rejects it at the server level, independent of the popup in Step 4 [SRS-085].
F7: Use case ends.

[G12: Foreign CV ID]
G13: Session holds a CV ID owned by another Jobseeker.
G14: System refuses to render it and warns "That CV belongs to another account" [SRS-087].
G15: Use case ends.

---

## 5. Method Description — Feature #5: Authentication (`auth_service.py`)

### 5.0 Method summary (table)

`auth_service.py`

| Method Name | Description |
|---|---|
| `hash_password(password: str)` | Hashes plaintext with random 16-byte salt via PBKDF2-HMAC-SHA256 (260k iters); returns `pbkdf2_sha256$<iter>$<salt>$<hash>`, never plaintext |
| `verify_password(password: str, stored: str \| None)` | Constant-time compare against stored hash (SRS-083); False for missing/legacy/malformed, never raises |
| `ensure_auth_tables()` | Creates `jobseeker` and `auth_session` if missing; safe on every startup; `admin` not created here |
| `check_registration_password(password: str)` | Registration rule (SRS-077): 8–64 chars, length only; raises `AuthValidationException` |
| `check_password_policy(password: str)` | Change/reset rule (SRS-089/090): 8–64 chars + blocklist; raises `AuthValidationException` |
| `validate_registration(username: str, email: str, password: str)` | Format only, no DB (SRS-077): username 3–30 `[A-Za-z0-9_.-]`, email standard max 255, registration password rule; returns `(username, email)` |
| `is_username_taken(username: str)` | Inline duplicate check without submitting (SRS-078); true if username exists |
| `is_email_taken(email: str)` | Inline duplicate check without submitting (SRS-078); true if email exists |
| `register_jobseeker(username: str, email: str, password: str)` | Creates account: validate format, then uniqueness check, store salted hash only (SRS-077/078/082) |
| `authenticate_jobseeker(identifier: str, password: str)` | Login with username OR email in one field (SRS-080); generic None on failure (SRS-083) |
| `get_jobseeker_by_id(jobseeker_id: str)` | Direct id lookup; returns `{id, username, email}` or None, never the hash |
| `require_jobseeker(jobseeker_id: str \| None)` | Server-side upload guard (SRS-085); returns id or raises `UnauthenticatedUploadException` |
| `change_jobseeker_password(jobseeker_id: str, current_password: str, new_password: str)` | Signed-in change (SRS-089): verify current, reject weak/same-as-old, store new hash only |
| `reset_jobseeker_password(username: str, email: str, new_password: str, new_password_confirmation: str)` | Reset (SRS-090): username + matching email on same account plus confirmation; store new hash only |
| `change_jobseeker_username(jobseeker_id: str, new_username: str)` | Rename (SRS-091): registration rule, reject duplicates, unchanged succeeds without write |
| `authenticate_admin(username: str, password: str)` | Admin check independent of jobseeker creds (SRS-079/080/082/083); legacy plaintext upgraded once |
| `create_jobseeker_session(jobseeker_id: str)` | Mints `auth_token` (`token_urlsafe(32)`, 30-day expiry) in `auth_session` |
| `create_admin_session(admin_id: str)` | Mints `admin_token` (`token_urlsafe(32)`, 30-day expiry) in `auth_session` |
| `get_jobseeker_by_session(token: str \| None)` | Validates `auth_token`; returns `{id, username, email}` or None; expired rows deleted best-effort |
| `get_admin_by_session(token: str \| None)` | Validates `admin_token`; returns `{id, username}` or None; expired rows deleted best-effort |
| `delete_session(token: str \| None)` | Revokes token on logout (SRS-088); never raises |

`cv_data_adapter.py` (ownership half of URS-014)

| Method Name | Description |
|---|---|
| `record_cv_ownership(jobseeker_id, cv_id, original_filename, uploaded_at)` | Writes `jobseeker_cv` index row (SRS-087); best-effort, never blocks upload |
| `list_cv_ids_for(jobseeker_id)` | One Jobseeker's CVs, newest-first (SRS-086/087); drops ids deleted from `cvs.json` |

### 5.1 Full method details

M-05-01
hash_password(password: string): string
Description:
Hashes a plaintext password with a random 16-byte salt using PBKDF2-HMAC-SHA256 (260,000 iterations). Output format is `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>` (SRS-082). Never returns or logs plaintext.
Parameters:
password: string – The plaintext password to hash.
Returns: string — salted password hash for storage.
Throws: AuthValidationException – if the password is empty.

M-05-02
verify_password(password: string, stored: string | null): boolean
Description:
Compares a plaintext candidate against a stored salted hash using constant-time comparison (SRS-083). Returns False for missing, legacy, or malformed stored values instead of raising.
Parameters:
password: string – The plaintext candidate from the login form.
stored: string | null – The stored hash from the `jobseeker` / `admin` table.
Returns: boolean — true if the candidate matches, otherwise false.
Throws: none (returns false on any parse or decode failure).

M-05-03
ensure_auth_tables(): void
Description:
Creates the `jobseeker` table (`id, username UNIQUE, email UNIQUE, password_hash, created_at`) and the `auth_session` table (`token PK, jobseeker_id NULL, admin_id NULL, created_at, expires_at NOT NULL`, indexes on `jobseeker_id`/`admin_id`) if missing. Safe to call on every startup. The `admin` table is not created here (it lives in `1_structure.sql`); its passwords are upgraded lazily. `auth_session` exists only here — it is not in `1_structure.sql` (implemented extension for refresh persistence; revoked per SRS-088).
Parameters:
none.
Returns: void.
Throws: DatabaseException – if the DDL statement fails.

M-05-04
validate_registration(username: string, email: string, password: string): tuple[string, string]
Description:
Validates registration format only, without touching the database, before any duplicate check (SRS-077). Trims username, trims/lowercases email, requires username 3–30 chars `[A-Za-z0-9_.-]`, email standard format max 255 chars, and password 8–64 chars via `check_registration_password()` (length only — no blocklist at registration). Returns the cleaned values.
Parameters:
username: string – The requested username.
email: string – The requested email address.
password: string – The requested plaintext password (never stored).
Returns: tuple[string, string] — cleaned (username, email).
Throws: AuthValidationException – if any field is missing or malformed.

M-05-05
is_username_taken(username: string): boolean
Description:
Inline duplicate check for the registration form (SRS-078). Queries `jobseeker` for the cleaned username and reports whether it exists, without submitting the form.
Parameters:
username: string – The username typed in the form.
Returns: boolean — true if already registered, otherwise false.
Throws: none (returns false when input is empty; DB errors propagate).

M-05-06
is_email_taken(email: string): boolean
Description:
Inline duplicate check for the registration form (SRS-078). Lowercases/trims the email, queries `jobseeker`, and reports whether it exists, without submitting the form.
Parameters:
email: string – The email typed in the form.
Returns: boolean — true if already registered, otherwise false.
Throws: none (returns false when input is empty; DB errors propagate).

M-05-07
register_jobseeker(username: string, email: string, password: string): dict
Description:
Creates a Jobseeker account (SRS-077, SRS-078, SRS-082). Validates format first, checks username/email uniqueness before inserting, generates a UUID id, and stores only the salted hash with a UTC timestamp.
Parameters:
username: string – The requested username.
email: string – The requested email address.
password: string – The requested plaintext password.
Returns: dict — {id, username, email} of the new account.
Throws: AuthValidationException – format invalid. UsernameTakenException – username exists. EmailTakenException – email exists.

M-05-08
authenticate_jobseeker(identifier: string, password: string): dict | null
Description:
Jobseeker login with username OR email in one field (SRS-080, SRS-083). An identifier containing `@` matches `email` (lowercased); otherwise `username`. Verifies against the stored hash in constant time; returns null on any failure with no enumeration detail. Never checks admin credentials (SRS-079).
Parameters:
identifier: string – A username or an email address, same field.
password: string – The plaintext password attempt.
Returns: dict | null — {id, username, email} on success, null on failure.
Throws: none.

M-05-09
get_jobseeker_by_id(jobseeker_id: string): dict | null
Description:
Fetches a Jobseeker by id. Selects `id, username, email` only — never the hash. Direct id lookup helper (refresh restore uses token-based M-05-17 instead).
Parameters:
jobseeker_id: string – The session's stored Jobseeker id.
Returns: dict | null — {id, username, email} if found, otherwise null.
Throws: none.

M-05-10
require_jobseeker(jobseeker_id: string | null): string
Description:
Server-side upload guard (SRS-085). Enforces that a CV upload carries a valid authenticated Jobseeker session, independent of the UI.
Parameters:
jobseeker_id: string | null – The current session's Jobseeker id.
Returns: string — the Jobseeker id when authenticated.
Throws: UnauthenticatedUploadException – if the session id is missing.

M-05-11
change_jobseeker_password(jobseeker_id: string, current_password: string, new_password: string): void
Description:
Changes the password for a signed-in Jobseeker (SRS-089, SRS-082). Verifies the current password against the stored hash, rejects a new password outside 8–64 chars, on the blocklist, or identical to the old one, then stores only the new salted hash. Wrong current password yields a generic failure and changes nothing.
Parameters:
jobseeker_id: string – The signed-in Jobseeker's id.
current_password: string – The current plaintext password for verification.
new_password: string – The new plaintext password to store as a hash.
Returns: void.
Throws: AuthValidationException – not signed in, account not found, current incorrect, new weak, or new equals old.

M-05-12
reset_jobseeker_password(username: string, email: string, new_password: string, new_password_confirmation: string): dict
Description:
Resets a forgotten password without an email server (SRS-090, SRS-082). The username AND email must both match the same account, and the confirmation must match the new password — both enforced in the service, not only in the UI. Stores only the new salted hash (8–64 chars, not blocklisted).
Parameters:
username: string – The account username.
email: string – The account email; must belong to the same row as the username.
new_password: string – The new plaintext password.
new_password_confirmation: string – Must match new_password; required.
Returns: dict — {id, username, email} of the reset account.
Throws: AuthValidationException – fields missing, no account matches the pair, confirmation missing/mismatched, or new password weak.

M-05-13
authenticate_admin(username: string, password: string): dict | null
Description:
Verifies admin credentials against the stored hash (SRS-079, SRS-080, SRS-082, SRS-083). Independent of Jobseeker credentials with constant-time comparison. Legacy plaintext seeds are accepted once and transparently upgraded to a salted hash. Login still succeeds if the best-effort upgrade write fails.
Parameters:
username: string – The admin username.
password: string – The plaintext password attempt.
Returns: dict | null — {id, username} on success, null on failure.
Throws: none.

M-05-14
change_jobseeker_username(jobseeker_id: string, new_username: string): dict
Description:
Changes the display name for a signed-in Jobseeker (SRS-091). Validates with the registration rule, returns the existing account unchanged when the name is identical (no write), rejects duplicates, then updates the row. The caller writes the returned username into session state immediately.
Parameters:
jobseeker_id: string – The signed-in Jobseeker's id.
new_username: string – The requested display name.
Returns: dict — {id, username, email} after the change (or unchanged).
Throws: AuthValidationException – not signed in, not found, or format invalid. UsernameTakenException – name belongs to another account.

M-05-15
create_jobseeker_session(jobseeker_id: string): string
Description:
Mints a persistent login token for a Jobseeker (implemented extension; revoked per SRS-088). Best-effort ensures tables, generates `secrets.token_urlsafe(32)`, inserts (`token, jobseeker_id, NULL admin_id, created_at, expires_at = now + 30 days`) into `auth_session`, and returns the token. The caller echoes it in the URL as `auth_token`.
Parameters:
jobseeker_id: string – The authenticated Jobseeker's id.
Returns: string — the token to store in the URL.

M-05-16
create_admin_session(admin_id: string): string
Description:
Mints a persistent login token for an Administrator (implemented extension; revoked per SRS-088). Same shape as M-05-15 but with (`token, NULL jobseeker_id, admin_id, ...`). The caller echoes it in the URL as `admin_token`.
Parameters:
admin_id: string – The authenticated Admin's id.
Returns: string — the token to store in the URL.

M-05-17
get_jobseeker_by_session(token: string | null): dict | null
Description:
Validates a Jobseeker token on page load (implemented extension). Joins `auth_session` to `jobseeker`, returns null for unknown/expired tokens or rows whose jobseeker no longer exists, deletes expired rows best-effort, and never raises. Naive datetimes are treated as UTC.
Parameters:
token: string | null – The `auth_token` URL param.
Returns: dict | null — {id, username, email} on valid token, otherwise null.
Throws: none.

M-05-18
get_admin_by_session(token: string | null): dict | null
Description:
Validates an Admin token on page load (implemented extension). Same contract as M-05-17 but joining `auth_session` to `admin` and returning {id, username}.
Parameters:
token: string | null – The `admin_token` URL param.
Returns: dict | null — {id, username} on valid token, otherwise null.
Throws: none.

M-05-19
delete_session(token: string | null): void
Description:
Revokes a persistent token on logout (SRS-088). Deletes the `auth_session` row and never raises — logout always succeeds locally even if the DB write fails. Callers also remove the token (and `page` for admin) from the URL.
Parameters:
token: string | null – The URL token to revoke.
Returns: void.
Throws: none.

M-05-20 (UI-only, no service method)
_pw_strength(password: string): tuple[int, string, string]
Description:
Renders the register-form password-strength meter (Weak/Okay/Good/Strong). Display-only; enforcement stays SRS-077 for registration and SRS-089/090 for change/reset (OUT-07).
Parameters:
password: string – The typed password.
Returns: tuple — (percent, label, colour) for the meter bar.
Throws: none.

---

## 6. File Structure — Feature #5: Authentication

All code lives in `CVReviwer/`. Run every Python command from there, not the repo root.

```
CVReviwer/
├── auth_service.py        # SERVICE — all Feature 5 logic, no Streamlit calls
│                          # hash/verify (M-05-01/02), validate + inline checks
│                          # (M-05-04/05/06), register (M-05-07), jobseeker/admin
│                          # login (M-05-08/13), upload guard (M-05-10),
│                          # change/reset password (M-05-11/12), rename (M-05-14),
│                          # sessions (M-05-03/15/16/17/18/19)
├── app.py                 # UI (jobseeker) — _render_login/register/forgot forms,
│                          # profile popover, _login_success/_logout,
│                          # _restore_persistent_login, process_cv guard (SRS-085),
│                          # My CVs list + foreign-ID reject (SRS-086/087)
├── admin.py               # UI (admin) — dedicated login page (SRS-079), session
│                          # gate, _restore_admin_session, logout; talks to
│                          # controllers + auth_service only
├── cv_data_adapter.py     # Ownership index — record_cv_ownership(),
│                          # list_cv_ids_for() → jobseeker_cv (cvs.json authoritative)
├── db.py                  # Sole MySQL connection owner (pooled, DB_POOL_SIZE=5)
├── 1_structure.sql        # DDL: admin, jobseeker, jobseeker_cv (+ F1/F2 tables).
│                          # Does NOT contain auth_session
├── 2_data.sql             # Seed: admin/123 (plaintext, upgraded on login).
│                          # Has live creds — never commit
├── cvs.json / uploads/    # CV store (Feature 3); jobseekerId = owner (authoritative)
├── .env                   # OPENAI_API_KEY, DB_* — beside app.py, never committed
└── .streamlit/config.toml # maxUploadSize = 20 (matches 20 MB limit)
```

Layering: `app.py` / `admin.py` → `auth_service.py` → `db.py`. UI never issues auth SQL directly (the two deliberate `db.query()` in `admin.py` are the Log-tab read and the pre-service login lookup, per `AGENTS.md`). `auth_session` DDL lives only in `ensure_auth_tables()` (M-05-03), called at import and best-effort inside `create_*_session()`.
