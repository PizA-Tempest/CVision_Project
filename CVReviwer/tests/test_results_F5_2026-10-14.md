# Feature 5 System Test Results — 2026-10-14 (tester: auto)

SUMMARY: 69/69 passed

| Test ID | Result | Actual Result |
|---|---|---|
| STC-05-001-TC-01 | PASS | app.py renders st.file_uploader('Upload your CV (PDF)') unconditionally (SRS-084 section); guest sees the upload section |
| STC-05-001-TC-02 | PASS | app.py: 'if uploaded_file and not _current_jobseeker_id()' calls _auth_dialog() instead of accepting the file |
| STC-05-001-TC-03 | PASS | require_jobseeker(None) raises UnauthenticatedUploadException; registry unchanged; record_cv_ownership(None,..) raises DatabaseException (file discarded, nothing stored/processed) |
| STC-05-001-TC-04 | PASS | validate_registration accepts 3-30 char username, standard email, 8-64 char password -> (carol_z,carol@example.com) |
| STC-05-001-TC-05 | PASS | is_username_taken(carol_z)=False, is_email_taken(carol@example.com)=False (both False) |
| STC-05-001-TC-06 | PASS | jobseeker row created: id=ec22b923-2343-4261-b64e-a2af7158adb4, username=carol_z, email=carol@example.com |
| STC-05-001-TC-07 | PASS | password_hash=pbkdf2_sha256$260000$91466860d0d... (salted, no plaintext; verifies) |
| STC-05-001-TC-08 | PASS | authenticate_jobseeker(carol_z) -> id=ec22b923-2343-4261-b64e-a2af7158adb4, no hash in return |
| STC-05-001-TC-09 | PASS | authenticate_jobseeker(carol@example.com) -> same id=ec22b923-2343-4261-b64e-a2af7158adb4 |
| STC-05-001-TC-10 | PASS | logged-in branch shows popover with display name/email + Change name/Change password/Log out; logged-out branch shows Log in/Sign up only |
| STC-05-001-TC-11 | PASS | require_jobseeker(carol session) returns id (upload accepted, valid Jobseeker session) |
| STC-05-001-TC-12 | PASS | jobseeker_cv links cv stc_cv_carol_001 -> jobseeker ec22b923 (Carol) |
| STC-05-001-TC-13 | PASS | My CVs for carol_z = ['stc_cv_carol_002', 'stc_cv_carol_001'] (newest first, cv_bob_001 absent) |
| STC-05-001-TC-14 | PASS | delete_session(token) revokes it (get_by_session -> None); _logout clears session state, login page shows Log in/Sign up again |
| STC-05-001-TC-15 | PASS | list_cv_ids_for(None/'') returns [] (no Jobseeker CVs shown when logged out) |
| STC-05-002-TC-01 | PASS | is_username_taken(alice_j) -> True (username already registered) |
| STC-05-002-TC-02 | PASS | is_email_taken(alice@example.com) -> True (email already registered) |
| STC-05-002-TC-03 | PASS | is_email_taken(' ALICE@Example.com ') -> True (case/space-insensitive) |
| STC-05-002-TC-04 | PASS | registration form runs inline duplicate check on every keystroke and shows inline error before submit (no form submission) |
| STC-05-002-TC-05 | PASS | duplicate username -> UsernameTakenException, duplicate email -> EmailTakenException; count 4->4, no new_user row |
| STC-05-003-TC-01 | PASS | username 'ab' (too short): rejected (Username must be 3-30 characters: letters, digits, _ . -) |
| STC-05-003-TC-02 | PASS | username 31 chars (too long): rejected (Username must be 3-30 characters: letters, digits, _ . -) |
| STC-05-003-TC-03 | PASS | username 'ali ce' (space): rejected (Username must be 3-30 characters: letters, digits, _ . -) |
| STC-05-003-TC-04 | PASS | email 'alice@' (no domain): rejected (Enter a valid email address.) |
| STC-05-003-TC-05 | PASS | email 256 chars (too long): rejected (Email must be at most 255 characters.) |
| STC-05-003-TC-06 | PASS | password 7 chars (too short): rejected (Password must be at least 8 characters.) |
| STC-05-003-TC-07 | PASS | password 65 chars (too long): rejected (Password must be at most 64 characters.) |
| STC-05-003-TC-08 | PASS | invalid format raises validation message with zero duplicate SELECTs (format checked before uniqueness) |
| STC-05-003-TC-09 | PASS | 3 invalid registrations attempted; count 4->4 (unchanged) |
| STC-05-003-TC-10 | PASS | boundaries accepted: username 3/30 chars, password 8/64 chars |
| STC-05-004-TC-01 | PASS | admin.py shows dedicated Admin Login page (SRS-079), no Jobseeker navigation on it |
| STC-05-004-TC-02 | PASS | authenticate_admin(stc_admin/Admin@2026) -> id=7ec03ac2 |
| STC-05-004-TC-03 | PASS | legacy plaintext accepted once and upgraded to salted hash (pbkdf2_sha256$260000$ceb...) |
| STC-05-004-TC-04 | PASS | authenticate_admin(stc_admin/Wrong@2026) -> None + generic failure (no detail) |
| STC-05-004-TC-05 | PASS | jobseeker credentials (alice_j/Alice123) rejected at admin login (independent verification) |
| STC-05-004-TC-06 | PASS | admin session token minted and validated; admin page shown (session established) |
| STC-05-004-TC-07 | PASS | delete_session(admin token) ends session; login page shown again |
| STC-05-005-TC-01 | PASS | username+email pair matches exactly 1 account (alice_j/alice@example.com) |
| STC-05-005-TC-02 | PASS | reset stores new salted hash (pbkdf2_sha256$260000$3f8...), no plaintext |
| STC-05-005-TC-03 | PASS | old password Alice123 no longer authenticates (None) |
| STC-05-005-TC-04 | PASS | new password Timmy123 authenticates as alice_j |
| STC-05-005-TC-05 | PASS | other-account email rejected generically (No account matches that username and email.); hash unchanged |
| STC-05-005-TC-06 | PASS | unknown username gives identical generic failure ('No account matches that username and email.') — no field disclosure |
| STC-05-005-TC-07 | PASS | mismatched confirmation rejected; hash unchanged |
| STC-05-005-TC-08 | PASS | missing confirmation rejected (New passwords do not match.); nothing changed |
| STC-05-005-TC-09 | PASS | weak new password rejected (policy 8-64); nothing changed |
| STC-05-006-TC-01 | PASS | current password verified; changed Alice123 -> Timmy123 |
| STC-05-006-TC-02 | PASS | wrong current rejected generically; hash unchanged |
| STC-05-006-TC-03 | PASS | 'Tim1234' rejected (Password must be at least 8 characters.); unchanged |
| STC-05-006-TC-04 | PASS | 'password' rejected (That password is too common — pick a less predictable one.); unchanged |
| STC-05-006-TC-05 | PASS | 'Timmy123' rejected (New password must differ from the old one.); unchanged |
| STC-05-006-TC-06 | PASS | new password stored as salted hash only (pbkdf2_sha256$260000$8ac...) |
| STC-05-006-TC-07 | PASS | Timmy123 accepted, Alice123 rejected (replacement confirmed) |
| STC-05-007-TC-01 | PASS | username updated alice_j -> alice_j2 (id=0bf931e3) |
| STC-05-007-TC-02 | PASS | app.py _change_name_dialog writes st.session_state['jobseeker_name'] immediately (no re-login) |
| STC-05-007-TC-03 | PASS | unchanged username accepted as success, no duplicate error, no extra write needed |
| STC-05-007-TC-04 | PASS | name used by another account rejected (That username is already registered.); unchanged |
| STC-05-007-TC-05 | PASS | invalid format rejected (Username must be 3-30 characters: letters, digits, _ . -); unchanged |
| STC-05-008-TC-01 | PASS | wrong password -> None (no account returned) |
| STC-05-008-TC-02 | PASS | unknown identifier -> None (no account returned) |
| STC-05-008-TC-03 | PASS | single shared generic message used 1x for both paths ('Invalid username/email or password.'); wrong-pw->None, unknown-id->None |
| STC-05-008-TC-04 | PASS | generic message ('Invalid username/email or password.') discloses neither identifier existence nor which field failed |
| STC-05-008-TC-05 | PASS | failed logins create no session rows (0->0); UI keeps Log in/Sign up |
| STC-05-008-TC-06 | PASS | admin credentials rejected at jobseeker login (independent stores; None) |
| STC-05-009-TC-01 | PASS | no session rejected as unauthenticated (Log in to upload a CV.) |
| STC-05-009-TC-02 | PASS | empty session id rejected (Log in to upload a CV.) |
| STC-05-009-TC-03 | PASS | rejected Carol_CV.pdf never stored/processed (registry byte-identical) |
| STC-05-009-TC-04 | PASS | ownership without session raises DatabaseException x2, no row created (count 6->6) |
| STC-05-009-TC-05 | PASS | valid session (alice_j) accepted for upload (id=0bf931e3) |
