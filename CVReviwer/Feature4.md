CVision
Software Design Document
Panuwat Songkram 662115038
Ratthasas Singhamanee 662115041
Bachelor of Science
Software Engineering Program
College of Arts, Media, and Technology
Chiang Mai University
April 2026
Project Advisor
Asst.Prof.Chartchai Doungsa-ard, Ph.D

Document History
Document History Status Date Editable Reviewer
Name
Documents
CVision_Software_Desig C 1/6/2026 PS, RS -
- Create Chapter 1, 2, 3, 4
n_Document_v1.docx
CVision_Software_Desig - Create the ERDiagram C,R 7/6/2026 PS, RS CD
n_Document_v1.2.docx - Create the Sequence
Diagram
CVision_Software_Desig - Create Data Dictionary C, R, U 14/6/2026 PS, RS CD
n_Document_v1.3.docx - Create Method
Description
- Update ERDiagram
- Update Sequence
Diagram
CVision_Software_Desig - Create UI C, R, U 25/6/2026 PS, RS CD
n_Document_v2.docx - Create Files Structure
- Update Sequence
Diagram
- Update Method
Description
CVision_Software_Desig - Update Files Structure R, U 6/7/2026 PS, RS CD
n_Document_v3.docx - Update Method
Description
*PS = Panuwat Songkram Status:
*RS = Ratthasas Singhamanee C = Create
*CD = Asst.Prof.Chartchai Doungsa-ard, Ph.D R = Reviewed by advisor
U = Update
Version: D = Delete
document name_vX.Y.Z
X: External published
Y: Test approval
Z: Internal review
Document Name CVision_Software_Design_ Owner PS, RS Page 2 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

|     |     |     |     |
| --- | --- | --- | --- |

TABLE OF CONTENTS
| Chapter One | Introduction                     |                           |     | 6   |
| ---------------------------------------------- | ------------------------- | --- | --- |
|                                                | 1.1 Purpose               |     | 6   |
|                                                | 1.2 Scope                 |     | 6   |
|                                                | 1.3 User Characteristics  |     | 6   |
| Chapter Two | System Architecture              |                           |     | 7   |
| Chapter Three | Detailed Design                |                           |     | 8   |
|              3.1 Entity Relationship Diagram   |                           |     | 8   |
|                                                | 3.1.2 Data Dictionary     |     | 10  |
|                                                | 3.1.3 File Structure      |     | 24  |
|              3.2 Sequence Diagram              |                           |     | 30  |
| Chapter Four | Technical Documentation         |                           |     | 44  |
|       4.1 Method Description                   |                           |     | 44  |
|       4.3 User Interface Design                |                           |     | 61  |

Document Name  CVision_Software_Design_ Owner  PS, RS  Page  3 / 16
Document_v3.docx
DocumentType  Software Design  Release Date  1/6/2026  Print Date  8/7/2026

2.3 Use Case Diagram
Document Name CVision_Software_Design_ Owner PS, RS Page 4 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

|     |     |     |     |     |
| --- | --- | --- | --- | --- |

2.4 Use Case Description

Feature #4: AI-Based CV Analysis and Scoring

| Use Case ID  | UC-007             |     |     |     |
| ------------ | ------------------ | --- | --- | --- |
| Use Case     | Analyze and Score  |     |     |     |
Name
Created By   Ratthasas Singhamanee  Last Update By   Panuwat Songkram
| Date Created  | 24/07/2026                              | Last Revision Date  | 27/07/2026  |     |
| ------------- | --------------------------------------- | ------------------- | ----------- | --- |
| Actors        | Jobseeker, System, External AI Service  |                     |             |     |
Description  After a Jobseeker successfully uploads and parses a CV (UC-005), the system analyzes the
structured CV data to evaluate its quality. The analysis assesses completeness (presence and
depth of skills, education, and work experience), relevance (alignment of content with industry
standards and job market keywords), and clarity (readability, formatting consistency, and
descriptive quality). The system generates an overall CV score (0–100) and a detailed
breakdown with actionable improvement suggestions. Results are displayed alongside the
extracted CV summary.
Trigger  The system has completed CV extraction and storage (UC-005).
| Preconditions  | 1. Jobseeker is logged into the system.  |     |     |     |
| -------------- | ---------------------------------------- | --- | --- | --- |
2. CV upload and parsing (UC-005) completed successfully.
3. Structured CV data (skills, education, work experience) is available in the database.
4. External AI Service is available for analysis.
Use Case Input Specification
| Input   | type     | Constraint         | Example        |     |
| ------- | -------- | ------------------ | -------------- | --- |
| cv_id   | String   | Required valid CV  | "cv_7f8a9b2c"  |     |
identifier.
skills   Array    Extracted from CV it may  [{"skill_name":"Python","proficienc
|     |     | be empty.  | y_level":"Advanced"}, ...]  |     |
| --- | --- | ---------- | --------------------------- | --- |
education   Array    Extracted from CV it may  [{"institution":"CMU","degree":"B.S
|     |     | be empty.  | c.","graduation_year":"2026"}, ...]  |     |
| --- | --- | ---------- | ------------------------------------ | --- |
work_  Array    Extracted from CV it   [{"company":"ABC","position":"Dev

Document Name  CVision_Software_Design_ Owner  PS, RS  Page  5 / 16
Document_v3.docx
DocumentType  Software Design  Release Date  1/6/2026  Print Date  8/7/2026

|     |     |     |     |     |
| --- | --- | --- | --- | --- |

experience   may be empty.  eloper","start_date":"2022-01-01","
end_date":"Present","description":"
..."}, ...]
raw_cv_text   Text     Extracted text from  "Tim Hammer\nEducation: ..."
PDF/A; max 50,000
chars.
Post  1. CV analysis results are calculated and stored in the system.
conditions  2. The Jobseeker is presented with an overall CV score (0–100) and category scores.
3. Actionable improvement suggestions are displayed for each evaluated category.
4. A log entry is recorded for the analysis action.
| Normal Flows  | Jobseeker  | System                   | External AI Service                   |     |
| ------------- | ---------- | ------------------------ | ------------------------------------- | --- |
|               |            | 1. Retrieves structured  |                                       |     |
|               |            | CV data (skills,         |                                       |     |
|               |            | education, work          |                                       |     |
|               |            | experience) from the     |                                       |     |
|               |            | database using cv_id.    |                                       |     |
|               |            |                          |                                       |     |
|               |            | 2. Retrieves the raw CV  |                                       |     |
|               |            | text and masked          |                                       |     |
|               |            | personal information.    |                                       |     |
|               |            |                          |                                       |     |
|               |            | 3. Transmits CV data     |                                       |     |
|               |            | and raw text to the      |                                       |     |
|               |            | External AI Service for  |                                       |     |
|               |            | analysis.                |                                       |     |
|               |            |                          |                                       |     |
|               |            |                          | 4. Receives CV data and raw text.     |     |
|               |            |                          |                                       |     |
|               |            |                          | 5. Analyzes Completeness:             |     |
|               |            |                          | checks presence and depth of          |     |
|               |            |                          | skills, education, and work           |     |
|               |            |                          | experience sections.                  |     |
|               |            |                          |                                       |     |
|               |            |                          | 6. Analyzes Relevance: evaluates      |     |
|               |            |                          | alignment of skills and experience    |     |
|               |            |                          | with current industry standards       |     |
|               |            |                          | and market keywords.                  |     |
|               |            |                          |                                       |     |
|               |            |                          | 7. Analyzes Clarity: assesses         |     |
|               |            |                          | readability, formatting consistency,  |     |

Document Name  CVision_Software_Design_ Owner  PS, RS  Page  6 / 16
Document_v3.docx
DocumentType  Software Design  Release Date  1/6/2026  Print Date  8/7/2026

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |

|     |                            |                            |          | action-verb usage, and descriptive  |     |
| --- | -------------------------- | -------------------------- | -------- | ----------------------------------- | --- |
|     |                            |                            |          | quality of experience entries.      |     |
|     |                            |                            |          |                                     |     |
|     |                            |                            |          | 8.Calculates category scores        |     |
|     |                            |                            |          | (0–100) for Completeness,           |     |
|     |                            |                            |          | Relevance, and Clarity.             |     |
|     |                            |                            |          |                                     |     |
|     |                            |                            |          | 9.Calculates an overall CV score    |     |
|     |                            |                            |          | (0–100) using weighted category     |     |
|     |                            |                            |          | scores.                             |     |
|     |                            |                            |          |                                     |     |
|     |                            |                            |          | 10. Generates actionable            |     |
|     |                            |                            |          | improvement suggestions for         |     |
|     |                            |                            |          | low-scoring categories.             |     |
|     |                            |                            |          |                                     |     |
|     |                            |                            |          | 11.Returns analysis results.        |     |
|     |                            |                            |          |                                     |     |
|     |                            | 12. Receives analysis      |          |                                     |     |
|     |                            | results, category scores,  |          |                                     |     |
|     |                            | overall score, and         |          |                                     |     |
|     |                            | suggestions.               | Returns  |                                     |     |
|     |                            | analysis results.          |          |                                     |     |
|     |                            |                            |          |                                     |     |
|     |                            | 13. Stores the CV          |          |                                     |     |
|     |                            | analysis results in the    |          |                                     |     |
|     |                            | CV_Analysis table.         |          |                                     |     |
|     |                            |                            |          |                                     |     |
|     |                            | 14. Displays the overall   |          |                                     |     |
|     |                            | CV score, category score   |          |                                     |     |
|     |                            | breakdown (visual chart),  |          |                                     |     |
|     |                            | and actionable             |          |                                     |     |
|     |                            | suggestions below the      |          |                                     |     |
|     |                            | extracted CV summary.      |          |                                     |     |
|     |                            |                            |          |                                     |     |
|     | 15. Reviews the CV score,  |                            |          |                                     |     |
category breakdown, and
improvement suggestions.
| Alternative  | [A1: Partial CV Data]  |     |     |     |     |
| ------------ | ---------------------- | --- | --- | --- | --- |
Flow  A2: System detects that one or more CV categories (skills, education, or work experience) are
missing or empty.
A3: System notifies the External AI Service to analyze only available categories.
A4: Completeness score is adjusted downward to reflect missing sections.
A5: Analysis continues for available categories.

Document Name  CVision_Software_Design_ Owner  PS, RS  Page  7 / 16
Document_v3.docx
DocumentType  Software Design  Release Date  1/6/2026  Print Date  8/7/2026

A6: Returns to Step 8 in Normal Flows.
[B3: Low Clarity Score]
B4: External AI Service detects poor readability or formatting issues.
B5: System generates specific suggestions (e.g., "Use bullet points," "Add action verbs,"
"Increase description length").
B6: Returns to Step 10 in Normal Flows.
Exception [E1: External AI Service Unavailable]
Flow E2: External AI Service does not respond or returns a service error.
E3: System records the communication failure.
E4: System displays an error message: "CV analysis service is temporarily unavailable.
Please try again later."
E5: Use case ends.
[F2: Analysis Calculation Error]
F3: System encounters an internal error during score calculation or data processing.
F4: System displays an error message: "CV analysis could not be completed at this time."
F5: Use case ends.
[G3: CV Data Corrupted]
G4: System detects that the stored CV data is corrupted or unreadable.
G5: System displays an error message requesting the Jobseeker to re-upload their CV.
G6: Returns to Step 1 in UC-005 (Upload CV).
● SRS-063: The system shall retrieve the Jobseeker's structured CV information from the
database upon completion of CV upload and parsing (UC-005).
● SRS-064: The system shall transmit CV data to the External AI Service for analysis of
completeness, relevance, and clarity.
● SRS-065: The system shall calculate a completeness score (0–100) based on the presence
and depth of skills, education, and work experience sections.
● SRS-066: The system shall calculate a relevance score (0–100) based on alignment of CV
content with industry standards and job market keywords.
● SRS-067: The system shall calculate a clarity score (0–100) based on readability, formatting
consistency, and descriptive quality.
● SRS-068: The system shall calculate an overall CV score (0–100) by combining weighted
category scores.
Document Name CVision_Software_Design_ Owner PS, RS Page 8 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

● SRS-069: The system shall generate actionable improvement suggestions for categories
scoring below 0.700.
● SRS-070: The system shall display the overall CV score, category score breakdown, and
improvement suggestions below the extracted CV summary.
● SRS-071: The system shall store CV analysis results in the database for future reference.
● SRS-072: The system shall adjust the completeness score and continue analysis using only
available CV categories when data is partially missing.
● SRS-073: The system shall display an error message when the External AI Service is
unavailable.
● SRS-074: The system shall display an error message when an internal error occurs during
analysis calculation.
● SRS-075: The system shall request the Jobseeker to re-upload their CV when stored CV data
is detected as corrupted.
Document Name CVision_Software_Design_ Owner PS, RS Page 9 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

2.5 Software Requirement Specifications
URS-011: Jobseekers want the system to evaluate the quality of their CV based on predefined criteria such as
completeness, relevance, and clarity.
● SRS-063: The system shall retrieve the Jobseeker's structured CV information from the database upon
completion of CV upload and parsing (UC-005).
● SRS-064: The system shall transmit CV data to the External AI Service for analysis of completeness,
relevance, and clarity.
● SRS-065: The system shall calculate a completeness score (0–100) based on the presence and depth of skills,
education, and work experience sections.
● SRS-066: The system shall calculate a relevance score (0–100) based on alignment of CV content with
general industry standards, independent of any specific job listing.
● SRS-067: The system shall calculate a clarity score (0–100) based on readability, formatting consistency, and
descriptive quality.
● SRS-071: The system shall adjust the completeness, relevance, and clarity scores and continue analysis using
only the available CV categories when data is partially missing.
● SRS-072: The system shall display an error message when the External AI Service is unavailable.
● SRS-073: The system shall display an error message when an internal error occurs during score calculation.
● SRS-074: The system shall request the Jobseeker to re-upload their CV when stored CV data is detected as
corrupted.
URS-012: Jobseekers want the system to generate an overall CV score indicating the strength of their CV.
● SRS-068: The system shall calculate an overall CV score (0–100) by combining weighted completeness,
relevance, and clarity scores.
● SRS-069: The system shall display the overall CV score and the individual completeness, relevance, and
clarity scores below the extracted CV summary.
● SRS-070: The system shall store the CV analysis results, including the overall score and individual category
scores, in the database for future reference.
Document Name CVision_Software_Design_ Owner PS, RS Page 10 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

Chapter Three | Detailed Design
3.1 Entity Relationship Diagram
3.1.1 Entity Relationship Diagram
3.1.1.1 Feature #4: AI-Based CV Analysis and Scoring
Document Name CVision_Software_Design_ Owner PS, RS Page 11 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

3.1.2 Data Dictionary
3.1.3 File Structure
Document Name CVision_Software_Design_ Owner PS, RS Page 12 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

3.2 Sequence Diagram
3.2.1 Feature #
SD-F1-01
Document Name CVision_Software_Design_ Owner PS, RS Page 13 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

Chapter Four | Detailed Design
4.1 Method Description
Feature #4: AI-Based CV Analysis and Scoring
M-04-01
retrieveCVForAnalysis(cvId: string): CVData
Retrieves structured CV data and sanitized raw text from the database for analysis. Corresponds to Steps 1–2
of UC-008's Normal Flow (SRS-063).
Parameters: cvId: string — the Jobseeker's CV identifier.
Returns: CVData — structured CV data and raw text.
Throws: CVDataCorruptedException — if the stored CV data is corrupted or unreadable (Exception
Flow E3).
M-04-02
requestCVAnalysis(cvData: CVData, rawText: string): AnalysisResult
Transmits CV data and raw text to the External AI Service. Corresponds to Step 3 of UC-008 (SRS-064).
Parameters: cvData: CVData, rawText: string.
Returns: AnalysisResult — raw evaluation signals for completeness, relevance, and clarity.
Throws: AIServiceUnavailableException — if the External AI Service does not respond (Exception
Flow E1).
M-04-03
calculateCompletenessScore(cvData: CVData, availableCategories: list<string>):
number
Evaluates presence and depth of skills, education, and work experience. Adjusts using only available categories
when data is partially missing. Corresponds to Step 5 (SRS-065, SRS-071).
Parameters: cvData: CVData, availableCategories: list<string>.
Returns: number — completeness score (0.000–1.000).
Throws: -
Document Name CVision_Software_Design_ Owner PS, RS Page 14 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

M-04-04
calculateRelevanceScore(cvData: CVData, availableCategories: list<string>):
number
Evaluates alignment of CV content with general industry standards, independent of any job listing.
Corresponds to Step 6 (SRS-066, SRS-071).
Parameters: cvData: CVData, availableCategories: list<string>.
Returns: number — relevance score (0.000–1.000).
Throws: -
M-04-05
calculateClarityScore(rawText: string, workExperience: list<WorkExperience>):
number
Assesses readability, formatting consistency, and descriptive quality. Corresponds to Step 7 (SRS-067,
SRS-071).
Parameters: rawText: string, workExperience: list<WorkExperience>.
Returns: number — clarity score (0.000–1.000).
Throws: -
M-04-06
calculateOverallScore(completeness: number, relevance: number, clarity:
number, availableCategories: list<string>): number
Calculates weighted overall CV score (0.000–1.000), adjusting weights when categories are missing.
Corresponds to Step 9 (SRS-068, SRS-071).
Parameters: completeness: number, relevance: number, clarity: number,
availableCategories: list<string>.
Returns: number — overall CV score (0.000–1.000).
Throws: CVAnalysisException — if an internal error occurs during calculation (Exception Flow E2).
M-04-07
storeCVAnalysis(cvId: string, analysis: CVAnalysisResult): void
Persists the overall and category scores to the CV_Analysis table. Corresponds to Step 10 (SRS-070).
Parameters: cvId: string, analysis: CVAnalysisResult.
Returns: void
Throws: DatabaseException — if the insert fails, rolling back the transaction.
Document Name CVision_Software_Design_ Owner PS, RS Page 15 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

M-04-08
displayCVAnalysis(cvId: string): void
Renders the overall CV score and category score breakdown on the CV upload page. Corresponds to Step 12
(SRS-069).
Parameters: cvId: string.
Returns: void
Throws: -
M-04-09
handleAnalysisError(exception: Exception): string
Maps analysis exceptions to user-facing messages: AIServiceUnavailableException → "The CV score
could not be generated at this time"; CVDataCorruptedException → "Your CV data could not be read —
please re-upload your CV"; CVAnalysisException → "An error occurred while calculating your CV
score". Unknown types return a generic error message.
Parameters: exception: Exception.
Returns: string.
Throws: none.
Document Name CVision_Software_Design_ Owner PS, RS Page 16 / 16
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026