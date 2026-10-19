# Feature 3 System Test Results — 2026-10-17 (tester: auto)

SUMMARY: 27/27 passed

| Test ID | Result | Actual Result |
|---|---|---|
| STC-03-001-TC-01 | PASS | process_cv accepted CV_2026.pdf -> cv_file_id=f205e31e, record validated, extracted skills stored, page renders 'Selected file' card + 'Upload successful' notification |
| STC-03-001-TC-02 | PASS | st.file_uploader('Upload your CV (PDF)') accepts browse and drag-and-drop; help text documents drag-and-drop; both land on the same 'if uploaded_file:' -> process_cv() path (no separate branch) |
| STC-03-001-TC-03 | PASS | CV_20MB.pdf (20971520 bytes) accepted, stored, processed; cv_file_id=51599e39, extracted data present |
| STC-03-001-TC-04 | PASS | isMasked=True; masked_email=t***@gmail.com, masked_phone=--4567, masked_address='*** Rim', masked_id=*********0123; verify passed; PII literals leaked to AI text: none; masked fields reported=['ID number', 'address', 'email', 'phone'] |
| STC-03-001-TC-05 | PASS | cvs.json extracted_data holds skills/education/work entries; displayExtractedCVInfo + render_extracted_info draw Python/Advanced, Chiang Mai University, ABC Company (skills=2, education=1, work=1) |
| STC-03-001-TC-06 | PASS | end_date 'Present' stored and displayed without error (stored end_date='Present'; drawn=True) |
| STC-03-002-TC-01 | PASS | CV_SkillsOnly.pdf: stored sections={'skills': 3, 'education': 0, 'work_experience': 0}; drawn sections={'skills': True, 'education': False, 'work_experience': False}; no error shown |
| STC-03-002-TC-02 | PASS | CV_NoWork.pdf: stored sections={'skills': 2, 'education': 1, 'work_experience': 0}; drawn sections={'skills': True, 'education': True, 'work_experience': False}; no error shown |
| STC-03-002-TC-03 | PASS | CV_WorkOnly.pdf: stored sections={'skills': 0, 'education': 0, 'work_experience': 2}; drawn sections={'skills': False, 'education': False, 'work_experience': True}; no error shown |
| STC-03-003-TC-01 | PASS | CV_NoSensitive.pdf: detectSensitiveInfo found nothing; masking skipped (masked_fields=[]); extraction stored and summary displayed (cv_file_id=a4673e5f) |
| STC-03-003-TC-02 | PASS | CV_YearsOnly.pdf: detectSensitiveInfo found nothing; masking skipped (masked_fields=[]); extraction stored and summary displayed (cv_file_id=f08c5f52) |
| STC-03-003-TC-02-evidence | PASS | '2022-2025' and 'GPA 3.75' not matched as phone/ID (phone=None, id=None) |
| STC-03-004-TC-01 | PASS | CV.docx: rejected with message 'Unsupported file format. Please upload a PDF file.'; stored=False |
| STC-03-004-TC-02 | PASS | Photo.jpg: rejected with message 'Unsupported file format. Please upload a PDF file.'; stored=False |
| STC-03-004-TC-03 | PASS | CV_Plain.pdf (standard PDF 1.4, not PDF/A) accepted and stored (cv_file_id=330b6901) |
| STC-03-004-TC-04 | PASS | CV_Fake.pdf (docx bytes, .pdf name): magic-byte check caught the mismatch; rejected with 'File is corrupted or unreadable. Please upload a valid CV file.'; file not stored |
| STC-03-005-TC-01 | PASS | CV_20MB_plus1.pdf (20971521 bytes): rejected with 'File size limit exceeded. Maximum size is 20 MB.'; stored=False |
| STC-03-005-TC-02 | PASS | CV_50MB.pdf (52428800 bytes): rejected with 'File size limit exceeded. Maximum size is 20 MB.'; stored=False |
| STC-03-006-TC-01 | PASS | CV_Truncated.pdf: rejected with 'File is corrupted or unreadable. Please upload a valid CV file.'; stored=False |
| STC-03-006-TC-02 | PASS | CV_Empty.pdf: rejected with 'File is corrupted or unreadable. Please upload a valid CV file.'; stored=False |
| STC-03-006-TC-03 | PASS | CV_BadHeader.pdf: rejected with 'File is corrupted or unreadable. Please upload a valid CV file.'; stored=False |
| STC-03-007-TC-01 | PASS | CV_Irrelevant.pdf: AI returned 0 categories; NoExtractionResultException -> 'CV could not be processed — please upload a clearer or properly formatted CV'; no extracted data stored; returns to upload step |
| STC-03-007-TC-02 | PASS | CV_ImageOnly.pdf: no text layer detected before AI call (AI calls=0); rejected with 'CV could not be processed — please upload a clearer or properly formatted CV'; no extracted data stored |
| STC-03-008-TC-01 | PASS | CV_BadEmail.pdf: mask step returned unmasked text (simulated External AI protection failure); verifySensitiveDataProtection raised; system stopped with 'CV processing could not be completed securely'; no extracted data stored |
| STC-03-008-TC-02 | PASS | CV_BadID.pdf: mask step returned unmasked text (simulated External AI protection failure); verifySensitiveDataProtection raised; system stopped with 'CV processing could not be completed securely'; no extracted data stored |
| STC-03-008-TC-03 | PASS | CV_MultiAddress.pdf: mask step returned unmasked text (simulated External AI protection failure); verifySensitiveDataProtection raised; system stopped with 'CV processing could not be completed securely'; no extracted data stored |
| STC-03-008-detection-evidence | PASS | real regex detection: bad-email CV -> email='morgan [at] example [dot] com'; bad-ID CV -> id='AB-12*34'; multi-line address -> address='123 Mae Rim Road' |
| STC-03-009-TC-01 | PASS | AI service down: real AI client raised ConnectionError; system responded with 'The analysis service is temporarily unavailable — please try again later'; communication failure recorded via error path |
| STC-03-009-TC-02 | PASS | AI service timeout: real AI client raised TimeoutError; system responded with 'The analysis service is temporarily unavailable — please try again later'; communication failure recorded via error path |
