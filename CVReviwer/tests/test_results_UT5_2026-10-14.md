# Feature 5 Unit Test Results — 2026-10-14 (tester: auto)

SUMMARY: 99/99 passed

| Test Record ID | Result | Actual Output |
|---|---|---|
| UT-5-01-001 | PASS | hash starts with 'pbkdf2_sha256$260000$' (pbkdf2_sha256$260000$fbcdfa3779b...) |
| UT-5-01-002 | PASS | two calls give different hashes (random salt) |
| UT-5-01-003 | PASS | hash contains no plaintext |
| UT-5-01-004 | PASS | AuthValidationException (Password is required.) |
| UT-5-02-001 | PASS | correct password verifies True |
| UT-5-02-002 | PASS | wrong password verifies False |
| UT-5-02-003 | PASS | stored=None verifies False (no raise) |
| UT-5-02-004 | PASS | legacy plaintext verifies False (handled by admin path, not here) |
| UT-5-02-005 | PASS | malformed stored value verifies False (no raise) |
| UT-5-03-001 | PASS | jobseeker + auth_session exist (rows 1/0) |
| UT-5-03-002 | PASS | second call raises nothing (IF NOT EXISTS, no duplicates) |
| UT-5-03-003 | PASS | creates only ['auth_session', 'jobseeker']; admin row count unchanged (2->2) |
| UT-5-03-004 | PASS | surfaces DatabaseError (template names it DatabaseException; implementation raises db.DatabaseError — same DB-layer failure, not swallowed) |
| UT-5-04-001 | PASS | returns ('alice_j', 'alice@example.com') |
| UT-5-04-002 | PASS | short username rejected (Username must be 3-30 characters: letters, digits, _ . -) |
| UT-5-04-003 | PASS | username with space rejected (Username must be 3-30 characters: letters, digits, _ . -) |
| UT-5-04-004 | PASS | malformed email rejected (Enter a valid email address.) |
| UT-5-04-005 | PASS | email >255 chars rejected (Email must be at most 255 characters.) |
| UT-5-04-006 | PASS | password 7 chars rejected (Password must be at least 8 characters.) |
| UT-5-04-007 | PASS | password 65 chars rejected (Password must be at most 64 characters.) |
| UT-5-04-008 | PASS | missing username rejected (Username is required.) |
| UT-5-04-009 | PASS | boundary values (3-char user, 8-char pw) do not throw |
| UT-5-04-010 | PASS | empty password rejected (Password is required.) |
| UT-5-05-001 | PASS | existing username -> True |
| UT-5-05-002 | PASS | unknown username -> False |
| UT-5-05-003 | PASS | padded username -> True (stripped) |
| UT-5-05-004 | PASS | empty username -> False (no query) |
| UT-5-06-001 | PASS | existing email -> True |
| UT-5-06-002 | PASS | case/space variant -> True |
| UT-5-06-003 | PASS | unknown email -> False |
| UT-5-06-004 | PASS | empty email -> False (no query) |
| UT-5-07-001 | PASS | returns id/username/email; count 2->3 |
| UT-5-07-002 | PASS | password_hash salted (pbkdf2_sha256$260000$80a...), no plaintext |
| UT-5-07-003 | PASS | created_at=2026-10-14 13:21:00.179000 (UTC) |
| UT-5-07-004 | PASS | UsernameTakenException (That username is already registered.) |
| UT-5-07-005 | PASS | EmailTakenException (That email is already registered.) |
| UT-5-07-006 | PASS | invalid input raises AuthValidationException; count 3->3 |
| UT-5-08-001 | PASS | username login returns id 69fa2ee6 |
| UT-5-08-002 | PASS | email login returns same id |
| UT-5-08-003 | PASS | wrong password -> None |
| UT-5-08-004 | PASS | unknown id -> None |
| UT-5-08-005 | PASS | empty identifier/password -> None (no raise) |
| UT-5-08-006 | PASS | keys=['email', 'id', 'username'] (no hash) |
| UT-5-09-001 | PASS | returns id/username/email, no hash |
| UT-5-09-002 | PASS | unknown id -> None |
| UT-5-10-001 | PASS | valid id returned unchanged |
| UT-5-10-002 | PASS | None raises UnauthenticatedUploadException (Log in to upload a CV.) |
| UT-5-10-003 | PASS | '' raises UnauthenticatedUploadException (Log in to upload a CV.) |
| UT-5-11-001 | PASS | no-throw; new verifies, old does not |
| UT-5-11-002 | PASS | wrong current rejected; hash unchanged |
| UT-5-11-003 | PASS | 7-char new rejected (Password must be at least 8 characters.) |
| UT-5-11-004 | PASS | blocklisted new rejected (That password is too common — pick a less predictable one.) |
| UT-5-11-005 | PASS | same-as-old new rejected (New password must differ from the old one.) |
| UT-5-11-006 | PASS | 65-char new rejected (Password must be at most 64 characters.) |
| UT-5-11-007 | PASS | not signed in rejected (Not signed in.) |
| UT-5-12-001 | PASS | returns id/username/email; hash replaced |
| UT-5-12-002 | PASS | generic failure, nothing changed (No account matches that username and email.) |
| UT-5-12-003 | PASS | same message as 002 ('No account matches that username and email.') |
| UT-5-12-004 | PASS | mismatched confirmation rejected (New passwords do not match.) |
| UT-5-12-005 | PASS | missing confirmation rejected (Password confirmation is required.) |
| UT-5-12-006 | PASS | weak password rejected (Password must be at least 8 characters.) |
| UT-5-12-007 | PASS | missing username/email rejected (Username and email are both required.) |
| UT-5-13-001 | PASS | returns id/username ({'id': 'b459ea05-da51-4256-a57a-cdff83e86dcc', 'username': 'ut5_admin'}) |
| UT-5-13-002 | PASS | wrong password -> None |
| UT-5-13-003 | PASS | unknown admin -> None |
| UT-5-13-004 | PASS | legacy plaintext accepted once; row upgraded to salted hash |
| UT-5-13-005 | PASS | post-upgrade login via hash path works |
| UT-5-13-006 | PASS | jobseeker creds -> None at admin login |
| UT-5-14-001 | PASS | row updated to ut5_nm2 (email kept ut5_nm@example.com) |
| UT-5-14-002 | PASS | unchanged name returns existing account; 0 write statements issued |
| UT-5-14-003 | PASS | UsernameTakenException (That username is already registered.) |
| UT-5-14-004 | PASS | AuthValidationException (Username must be 3-30 characters: letters, digits, _ . -) |
| UT-5-14-005 | PASS | AuthValidationException (Not signed in.) |
| UT-5-15-001 | PASS | token row: jobseeker set, admin NULL, expiry +30d (delta=30 days, 0:00:00) |
| UT-5-15-002 | PASS | two tokens differ (random) |
| UT-5-16-001 | PASS | token row: admin set, jobseeker NULL |
| UT-5-17-001 | PASS | valid token returns id/username/email |
| UT-5-17-002 | PASS | unknown token -> None |
| UT-5-17-003 | PASS | expired token -> None; row deleted |
| UT-5-17-004 | PASS | None token -> None (no raise) |
| UT-5-17-005 | PASS | admin token -> None on jobseeker lookup |
| UT-5-18-001 | PASS | valid admin token returns id/username |
| UT-5-18-002 | PASS | unknown token -> None |
| UT-5-18-003 | PASS | jobseeker token -> None on admin lookup |
| UT-5-19-001 | PASS | session row deleted |
| UT-5-19-002 | PASS | None: no exception |
| UT-5-19-003 | PASS | 'no-such-token': no exception |
| UT-5-19-004 | PASS | '': no exception |
| UT-5-20-001 | PASS | weak pw -> (5, 'Weak') |
| UT-5-20-002 | PASS | strong pw -> (100, 'Strong') |
| UT-5-21-001 | PASS | returns True; row holds ids/filename/upload time ({'jobseeker_id': '69fa2ee6-fd6a-42d1-868d-f5a9680c4c3e', 'cv_id': 'ut5cv_own_001', 'original_filename': 'CV.pdf', 'uploaded_at': datetime.datetime(2026, 10, 14, 13, 21, 2, 698000)}) |
| UT-5-21-002 | PASS | raises DatabaseException: jobseeker_id and cv_id are both required. |
| UT-5-21-003 | PASS | raises DatabaseException: jobseeker_id and cv_id are both required. |
| UT-5-22-001 | PASS | 3 ids newest-first: ['ut5cv_l002', 'ut5cv_l001', 'ut5cv_l000'] |
| UT-5-22-002 | PASS | returns 20 ids (template expects the 20 newest; service has no cap — the [:20] slice lives in app.py UI) |
| UT-5-22-003 | PASS | other jobseeker's id excluded |
| UT-5-22-004 | PASS | unparsed id excluded — service filters orphans only; the parsed-only filter lives in app.py (_has_extracted_data) |
| UT-5-22-005 | PASS | orphan id (absent from registry) excluded |
| UT-5-22-006 | PASS | unknown jobseeker -> [] |
