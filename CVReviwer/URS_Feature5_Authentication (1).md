# Feature #5: Authentication — URS / SRS / Use Case UC-008

## 1. User Requirements (URS)

**URS-010:** Jobseekers can register their own account, with the system checking that the chosen username or email is not already taken, so their CVs and results are saved under their own account.

* SRS-063: The registration form shall display an inline error when the entered username or email is already registered, without submitting the form.
* SRS-069: The system shall check, at registration, that the submitted username and email do not already exist in the Jobseeker records before creating a new account.
* SRS-077: The system shall validate registration format before checking duplicates: username 3–30 chars (`[A-Za-z0-9_.-]`), email must match standard email format, password minimum 6 characters.

**URS-011:** Jobseekers and administrators can log in using their own credentials to access their account or manage the platform.

* SRS-064: The Jobseeker login form shall accept either a username or an email address in the same field, together with a password.
* SRS-065: The admin login page shall present its own username and password fields, separate from the Jobseeker login form, and shall not expose Jobseeker-facing navigation.
* SRS-066: The Jobseeker interface shall show "Log In" and "Register" options to an unauthenticated Guest, and shall replace them with the Jobseeker's display name and a "Log Out" option once authenticated.
* SRS-070: The system shall authenticate a Jobseeker login by matching the supplied identifier (username or email) and verifying the password against its stored hash.
* SRS-071: The system shall authenticate an Administrator login by verifying the submitted credentials against the stored administrator credential hash.

**URS-012:** Jobseekers and administrators want the system to keep their password private and protected.

* SRS-072: The system shall store every Jobseeker and Administrator password as a salted hash (`pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`, 260k iterations) and shall never store or log a plaintext password.
* SRS-078: The system shall verify passwords with constant-time comparison and shall return a generic failure (no account-enumeration detail) on mismatch.

**URS-013:** Guests can view the CV upload section without creating an account, but must log in or register before they can upload a CV.

* SRS-067: The CV upload section shall remain visible to a Guest, but selecting the upload control shall redirect an unauthenticated Guest to the login/register screen instead of accepting a file.
* SRS-073: The system shall reject a CV upload request that lacks a valid authenticated Jobseeker session, regardless of what the UI displayed.

**URS-014:** Jobseekers can view their own uploaded CVs, analysis results, and job matches, kept under their own account and not visible to other users.

* SRS-068: The "My CVs" view shall display only the CVs uploaded by the currently authenticated Jobseeker.
* SRS-074: The system shall record the authenticated Jobseeker's ID as the owner of every uploaded CV, and shall use that ID to filter the CVs, analysis results, and match results returned to that Jobseeker.
* SRS-079: The system shall block rendering of a CV ID that is not owned by the current Jobseeker session (stale/guessed ID), warning "That CV belongs to another account."

**URS-015:** The administrator panel is kept separate from Jobseeker accounts, so the administrator can manage the platform.

* SRS-065: The admin login page shall present its own username and password fields, separate from the Jobseeker login form, and shall not expose Jobseeker-facing navigation.
* SRS-075: The system shall restrict every Admin panel route and function to sessions authenticated as Administrator, independent of any Jobseeker session state.

**URS-016:** Jobseekers and administrators can log out of their account to end their session securely.

* SRS-066: The Jobseeker interface shall show "Log In" and "Register" options to an unauthenticated Guest, and shall replace them with the Jobseeker's display name and a "Log Out" option once authenticated.
* SRS-076: The system shall end the active session and clear session state (`jobseeker_id`, `jobseeker_name`, `jobseeker_email`, `cv_file_id`, review/calc state, auth popup flags) when a Jobseeker or Administrator logs out.

**URS-017 (added — already implemented as outbound extension):** Jobseekers can change their password while signed in and reset a forgotten password without an email server.

* SRS-080: A signed-in Jobseeker shall be able to change password by supplying the correct current password and a new password (min 6 chars, must differ from old); the system shall store only the new salted hash.
* SRS-081: A forgotten-password reset shall require both the username AND the matching account email (identity check in place of an emailed token), plus new-password confirmation; on success the system stores only the new salted hash.
* SRS-082: Legacy admin rows seeded as plaintext (`"123"`) shall be accepted once via constant-time compare and transparently upgraded to a salted hash on successful login.

---

## 2. Outbound / Out-of-Scope (added)

### 2.1 Outbound interfaces (what this feature sends out)

| ID | Outbound target | Content | Notes |
|----|-----------------|---------|-------|
| OUB-01 | MySQL `jobseeker` table | `id, username, email, password_hash, created_at` | Created by `ensure_auth_tables()`; `username` + `email` UNIQUE |
| OUB-02 | MySQL `admin` table | Upgraded `password` hash on legacy login | Best-effort `UPDATE`; login succeeds even if upgrade fails |
| OUB-03 | MySQL `jobseeker_cv` index + `cvs.json` | `jobseeker_id` as CV owner | Authoritative owner = `cvs.json:jobseekerId`; index is queryable copy |
| OUB-04 | Streamlit session state | `jobseeker_id/name/email`, `admin_authenticated/admin_user` | Cleared on logout per SRS-076 |
| OUB-05 | Admin activity log (`log_service.set_current_user`) | Admin id/username on admin login | Best-effort; failure does not block login |

### 2.2 Out of scope — explicitly NOT in Feature #5

| ID | Exclusion | Rationale |
|----|-----------|-----------|
| OUT-01 | No emailed reset links / SMTP | Reset uses username+email match (SRS-081) by owner request |
| OUT-02 | No OAuth / SSO / social login | Username-or-email + password only |
| OUT-03 | No MFA / CAPTCHA / account lockout / password expiry | Generic "invalid username/email or password" only |
| OUT-04 | No role-based permissions beyond Jobseeker vs Admin | Admin routes gated by `admin_authenticated` only |
| OUT-05 | No plaintext password logging or recovery | Hashes only; forgotten password = reset, never retrieval |
| OUT-06 | No cross-account visibility | Enforced server-side (SRS-073/074/079), not just UI hiding |

---

## 3. Traceability (URS → SRS → code)

| URS | SRS | Implements |
|-----|-----|------------|
| URS-010 | SRS-063, SRS-069, SRS-077 | `auth_service.validate_registration()`, `is_username_taken()`, `is_email_taken()`, `register_jobseeker()` |
| URS-011 | SRS-064, SRS-065, SRS-066, SRS-070, SRS-071 | `auth_service.authenticate_jobseeker()`, `authenticate_admin()`, `app._render_login_form()`, `admin.show_admin_page()` |
| URS-012 | SRS-072, SRS-078 | `auth_service.hash_password()`, `verify_password()` |
| URS-013 | SRS-067, SRS-073 | `app` uploader guest-popup + `auth_service.require_jobseeker()`, `app.process_cv()` guard |
| URS-014 | SRS-068, SRS-074, SRS-079 | `cv_data_adapter.list_cv_ids_for()`, `record_cv_ownership()`, `app` My-CVs + ownership check |
| URS-015 | SRS-065, SRS-075 | `admin.py` session gate (`admin_authenticated`), `?page=admin` routing |
| URS-016 | SRS-066, SRS-076 | `app._login_success()`, `app._logout()` |
| URS-017 | SRS-080, SRS-081, SRS-082 | `auth_service.change_jobseeker_password()`, `reset_jobseeker_password()`, legacy-upgrade in `authenticate_admin()` |

> Note: `app.py` also accepts administrator credentials in the same login popup and routes to `?page=admin` on match. This deviates from SRS-065's separate-form rule per owner request; the two credential checks remain independent.

---

## 4. Use Case UC-008 — Register, Log In, and Manage Session Access

**Use Case ID:** UC-008

**Use Case Name:** Register, Log In, and Manage Session Access

**Created By:** [Name]

**Last Update By:** [Name]

**Date Created:** 25/09/2026

**Last Revision Date:** 28/09/2026 — added URS-017/SRS-077..082 + Outbound section

**Actors:** Jobseeker, Guest, Administrator, System

**Description:** An unauthenticated Guest can view the CV upload section but must register or log in before uploading a CV or accessing personalized features (URS-013). A Guest registers a Jobseeker account with a username, email, and password, with the system checking that the username and email are not already taken (URS-010). Once logged in, a Jobseeker sees only their own CVs, analysis results, and job matches (URS-014). An Administrator logs in separately through the admin panel, which stays isolated from Jobseeker accounts (URS-015). Both Jobseekers and Administrators can log in with their own credentials (URS-011), have their passwords kept private and protected (URS-012), can log out to end their session securely (URS-016), and Jobseekers can change/reset passwords (URS-017).

**Trigger:** A Guest chooses to register, log in, or attempts to upload a CV without an account; or an Administrator chooses to log in to the admin panel.

**Preconditions:**

1. The system is available and reachable.
2. For login, the user already holds a registered Jobseeker account or valid administrator credentials.

**Use Case Input Specification:**

| Input | Type | Constraint | Example |
| ----- | ---- | ---------- | ------- |
| username | String | Required for registration; 3–30 chars `[A-Za-z0-9_.-]`; must not already exist [SRS-069, SRS-077] | "alice_j" |
| email | String | Required for registration; valid email format; must not already exist [SRS-069, SRS-077] | "alice@example.com" |
| password | String | Required; min 6 chars; stored only as salted hash, never plaintext [SRS-072, SRS-077] | "••••••••" |
| identifier | String | Required for Jobseeker login; a username or an email address, same field [SRS-064] | "alice_j" |
| admin_username | String | Required for administrator login; separate field set from Jobseeker login [SRS-065] | "admin" |
| admin_password | String | Required for administrator login; verified against stored admin hash [SRS-071] | "••••••••" |
| current_password | String | Required for password change; must verify against stored hash [SRS-080] | "••••••••" |
| new_password | String | Required for change/reset; min 6 chars, must differ from old (change) [SRS-080, SRS-081] | "••••••••" |

**Postconditions:**

1. A new Jobseeker account is created only if the username and email were not already taken [SRS-069].
2. The Jobseeker's or Administrator's password is stored as a salted hash [SRS-072].
3. An authenticated Jobseeker session is scoped so their CVs, analysis, and matches are returned only to them [SRS-074, SRS-079].
4. An authenticated Administrator session is restricted to admin routes, independent of any Jobseeker session state [SRS-075].
5. On logout, the session is ended and cleared [SRS-076].
6. Changed/reset passwords replace the old hash; legacy admin plaintext is upgraded to a hash [SRS-080, SRS-081, SRS-082].
7. Outbound writes go to `jobseeker` / `admin` / `jobseeker_cv` + session state only [OUB-01..05]; OUT-01..06 remain out of scope.

**Normal Flows:**

| Jobseeker / Guest | System |
| ----------------- | ------ |
| 1. Guest views the CV upload section without an account. | 2. Displays the upload section to the Guest [SRS-067]. |
| 3. Guest selects the upload control. | 4. Redirects the unauthenticated Guest to the login/register screen instead of accepting the file [SRS-067]. |
| 5. Guest navigates to the registration form and submits a username, email, and password. | 6. Validates format [SRS-077]; checks that the username and email do not already exist in the Jobseeker records [SRS-069]. |
|  | 7. Creates the account, storing the password as a salted hash [SRS-072]; writes outbound owner index [OUB-01, OUB-03]. |
| 8. Enters a username or email, together with a password, in the single Jobseeker login form [SRS-064]. | 9. Matches the supplied identifier and verifies the password against its stored hash [SRS-070, SRS-078]. |
|  | 10. Establishes the Jobseeker's session; replaces "Log In"/"Register" with the Jobseeker's display name and a "Log Out" option [SRS-066]. |
| 11. Uploads a CV and views "My CVs." | 12. Records the Jobseeker's ID as the CV's owner, and filters "My CVs," analysis, and match results to that ID; blocks foreign CV IDs [SRS-068, SRS-074, SRS-079]. |
| 13. Selects Log Out. | 14. Ends the session and restores the "Log In"/"Register" options [SRS-066, SRS-076]. |

**Alternative Flows:**

[A6: Duplicate Username or Email]
A7: System detects the submitted username or email already exists.
A8: Registration form displays an inline error without submitting the form, and does not create the account [SRS-063].
A9: Returns to Step 5.

[A5b: Bad Format]
A5b-1: Username, email, or password fails format/length check [SRS-077].
A5b-2: Form shows validation message; no DB check, no account created.
A5b-3: Returns to Step 5.

[B1: Administrator Login]
B2: Administrator navigates to the separate admin login page, which shows no Jobseeker-facing navigation [SRS-065].
B3: Administrator submits admin_username and admin_password.
B4: System verifies the credentials against the stored administrator hash [SRS-071, SRS-072]; upgrades legacy plaintext once [SRS-082].
B5: System establishes an admin session restricted to admin routes and functions, independent of any Jobseeker session [SRS-075]; sets outbound log user [OUB-05].
B6: Returns to Step 11 (admin equivalent: manages the platform).
B7: Administrator selects Log Out; system ends the admin session [SRS-076].

[C1: Change Password]
C2: Signed-in Jobseeker submits current + new password (with confirmation).
C3: System verifies current hash, rejects weak/same-as-old, stores new salted hash [SRS-080].
C4: Returns to Step 11.

[D1: Forgot-Password Reset]
D2: Guest submits username + account email + new password (with confirmation).
D3: System requires username and email to match the same account, then stores the new salted hash [SRS-081].
D4: Returns to Step 8.

**Exception Flows:**

[E9: Invalid Login Credentials]
E10: No matching account is found, or the password does not match the stored hash.
E11: System displays an "invalid username/email or password" message (no enumeration) [SRS-078].
E12: Returns to Step 8.

[F4: Upload Bypasses the UI Prompt]
F5: A request to upload a CV arrives without a valid authenticated Jobseeker session, regardless of what the interface displayed.
F6: System rejects the request at the server level, independent of the redirect in Step 4 [SRS-073].
F7: Use case ends.

[G12: Foreign CV ID]
G13: Session holds a CV ID owned by another Jobseeker.
G14: System clears `cv_file_id`, warns "That CV belongs to another account" [SRS-079].
G15: Use case ends.

---

## 5. Method Description — Feature #5: Authentication (`auth_service.py`)

M-05-01
hash_password(password: string): string
Description:
This method hashes a plaintext password with a random 16-byte salt using PBKDF2-HMAC-SHA256 (260,000 iterations). The output format is `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`. It never returns or logs plaintext.
Parameters:
password: string – The plaintext password to hash.
Returns: string — salted password hash for storage.
Throws: AuthValidationException – if the password is empty.

M-05-02
verify_password(password: string, stored: string | null): boolean
Description:
This method compares a plaintext candidate against a stored salted hash using constant-time comparison so timing does not leak prefix matches. It returns False for missing, legacy, or malformed stored values instead of raising.
Parameters:
password: string – The plaintext candidate from the login form.
stored: string | null – The stored hash from the `jobseeker` / `admin` table.
Returns: boolean — true if the candidate matches the stored hash, otherwise false.
Throws: none (returns false on any parse or decode failure).

M-05-03
ensure_auth_tables(): void
Description:
This method creates the `jobseeker` table (`id, username UNIQUE, email UNIQUE, password_hash, created_at`) if it does not exist yet. It is safe to call on every startup. The `admin` table is not created here; its passwords are upgraded lazily.
Parameters:
none.
Returns: void.
Throws: DatabaseException – if the DDL statement fails.

M-05-04
validate_registration(username: string, email: string, password: string): tuple[string, string]
Description:
This method validates registration format only, without touching the database. It trims and lowercases the email, checks username is 3–30 chars `[A-Za-z0-9_.-]`, email matches standard format, and password is at least 6 characters. It returns the cleaned values for the caller to use.
Parameters:
username: string – The requested username.
email: string – The requested email address.
password: string – The requested plaintext password (never stored).
Returns: tuple[string, string] — cleaned (username, email).
Throws: AuthValidationException – if any field is missing or malformed.

M-05-05
is_username_taken(username: string): boolean
Description:
This method performs the inline duplicate check for the registration form (SRS-063). It queries the `jobseeker` table for the cleaned username and reports whether it already exists, without submitting the form.
Parameters:
username: string – The username typed in the form.
Returns: boolean — true if the username is already registered, otherwise false.
Throws: none (returns false when input is empty; DB errors propagate to caller).

M-05-06
is_email_taken(email: string): boolean
Description:
This method performs the inline duplicate check for the registration form (SRS-063). It lowercases and trims the email, queries the `jobseeker` table, and reports whether it already exists, without submitting the form.
Parameters:
email: string – The email typed in the form.
Returns: boolean — true if the email is already registered, otherwise false.
Throws: none (returns false when input is empty; DB errors propagate to caller).

M-05-07
register_jobseeker(username: string, email: string, password: string): dict
Description:
This method creates a Jobseeker account (SRS-069, SRS-072). It validates format, checks username and email uniqueness before inserting, generates a UUID id, and stores only the salted hash with a UTC created timestamp.
Parameters:
username: string – The requested username.
email: string – The requested email address.
password: string – The requested plaintext password.
Returns: dict — {id, username, email} of the new account.
Throws: AuthValidationException – if format validation fails. UsernameTakenException – if the username already exists. EmailTakenException – if the email already exists.

M-05-08
authenticate_jobseeker(identifier: string, password: string): dict | null
Description:
This method logs in with a username OR an email in one field (SRS-064, SRS-070). An identifier containing `@` is matched against `email` (lowercased); otherwise against `username`. The password is verified against the stored hash. It returns null on any failure with no account-enumeration detail.
Parameters:
identifier: string – A username or an email address, same field.
password: string – The plaintext password attempt.
Returns: dict | null — {id, username, email} on success, null on failure.
Throws: none (returns null when input is missing, no row matches, or hash mismatches).

M-05-09
get_jobseeker_by_id(jobseeker_id: string): dict | null
Description:
This method fetches a Jobseeker by id for session restore. It selects `id, username, email` only — never the password hash.
Parameters:
jobseeker_id: string – The session's stored Jobseeker id.
Returns: dict | null — {id, username, email} if found, otherwise null.
Throws: none (returns null when id is empty or not found).

M-05-10
require_jobseeker(jobseeker_id: string | null): string
Description:
This method is the server-side upload guard (SRS-073). It enforces that a CV upload request carries a valid authenticated Jobseeker session, independent of what the UI displayed.
Parameters:
jobseeker_id: string | null – The current session's Jobseeker id.
Returns: string — the Jobseeker id when authenticated.
Throws: UnauthenticatedUploadException – if the session id is missing (caller shows "Log in to upload a CV.").

M-05-11
change_jobseeker_password(jobseeker_id: string, current_password: string, new_password: string): void
Description:
This method changes the password for a signed-in Jobseeker (SRS-080). It verifies the current password against the stored hash, rejects a weak new password (min 6 chars) or one identical to the old, then stores only the new salted hash.
Parameters:
jobseeker_id: string – The signed-in Jobseeker's id.
current_password: string – The current plaintext password for verification.
new_password: string – The new plaintext password to store as a hash.
Returns: void.
Throws: AuthValidationException – if not signed in, account not found, current password is incorrect, new password is weak, or new equals old.

M-05-12
reset_jobseeker_password(username: string, email: string, new_password: string): dict
Description:
This method resets a forgotten password without an email server (SRS-081). The username AND email must both match the same account as an identity check in place of an emailed token. It stores only the new salted hash.
Parameters:
username: string – The account username.
email: string – The account email; must belong to the same row as the username.
new_password: string – The new plaintext password (min 6 chars).
Returns: dict — {id, username, email} of the reset account.
Throws: AuthValidationException – if fields are missing, no account matches the pair, or the new password is weak.

M-05-13
authenticate_admin(username: string, password: string): dict | null
Description:
This method verifies admin credentials against the stored hash (SRS-071, SRS-072). Legacy plaintext seed rows (e.g. "123") are accepted once via constant-time compare and transparently upgraded to a salted hash, so existing installs keep working. Login still succeeds if the best-effort upgrade write fails.
Parameters:
username: string – The admin username.
password: string – The plaintext password attempt.
Returns: dict | null — {id, username} on success, null on failure.
Throws: none (returns null when input is missing, no row matches, or hash mismatches).
