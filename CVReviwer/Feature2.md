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
Document Name CVision_Software_Design_ Owner PS, RS Page 2 / 21
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

Document Name  CVision_Software_Design_ Owner  PS, RS  Page  3 / 21
Document_v3.docx
DocumentType  Software Design  Release Date  1/6/2026  Print Date  8/7/2026

2.3 Use Case Diagram
Document Name CVision_Software_Design_ Owner PS, RS Page 4 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

2.4 Use Case Description
Feature #2: Job Matching
Use Case ID UC-006
Use Case View Job Match Results
Name
Created By Ratthasas Singhamanee Last Update By Panuwat Songkram
Date Created 24/07/2026 Last Revision Date 27/07/2026
Actors Jobseeker, System
Description Triggered automatically once a Jobseeker has uploaded and parsed a CV (UC-005). The
system reads the Jobseeker's stored structured CV information and compares it against every
active, non-outdated job listing that has been enriched with structured job data. For each
listing it compares skills, education and work experience, calculates a matching score between
0.000 and 1.000, identifies the matched skills, ranks the listings from highest to lowest score,
and stores the ranked results. The ranked job cards are displayed below the extracted CV
information summary on the CV upload page. Each card shows the job title, company name
and location, the match score, a progress bar, matched and unmatched skill tags, and a link to
the original job posting. For the five highest-ranked listings the system also generates a short
AI-written explanation of why the Jobseeker suits that role.
Trigger The system has completed CV extraction and is displaying the extracted CV
Preconditions 1. The Jobseeker has successfully uploaded and parsed a CV (UC-005 completed).
2. The system has stored the Jobseeker's structured CV data (skills, education, work
experience).
3. At least one job listing exists that is active and non-outdated (Feature #1) and has been
enriched with structured job data — required skills, qualification requirement and experience
requirement. A listing without that enrichment is excluded from matching, because there is
nothing to compare the CV against.
Use Case Input Specification
Input type Constraint Example
url String Required. URL of the job https://www.linkedin.com/jobs/view
listing. /full-stack-engineer-digital-venture-
at-makro-pro-4420709351
Document Name CVision_Software_Design_ Owner PS, RS Page 5 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

|     |     |     |     |     |
| --- | --- | --- | --- | --- |

job_title  String  Required. Title of the job  Full-stack Engineer, Digital
|            |         | position.              | Venture    |     |
| ---------- | ------- | ---------------------- | ---------- | --- |
| company_na | String  | Required. Name of the  | Makro PRO  |     |
| me         |         | hiring company.        |            |     |
job_location  String  Required. Location of the  Bangkok, Bangkok City, Thailand
job.
job_details  String  Required. Full job  Makro PRO is an exciting new
|     |     | description and  | digital venture...  |     |
| --- | --- | ---------------- | ------------------- | --- |
requirements.
| job_employm | String  | Optional. Employment  | Full-time  |     |
| ----------- | ------- | --------------------- | ---------- | --- |
| ent_type    |         | type of the job.      |            |     |
job_posted_d String  Optional. Date the job  2026-06-09T20:12:48.473Z
| ate  |     | was posted (ISO 8601  |     |     |
| ---- | --- | --------------------- | --- | --- |
format).
salary  String  Optional. Displayed as  40,000 - 70,000 Baht
“No salary listed” if left
empty.
skill_name  String  Required. Skill name.  "Python", "Food Safety",
|     |     | Practical skills and  | "Teamwork"  |     |
| --- | --- | --------------------- | ----------- | --- |
general soft skills are
both accepted and are
weighted differently
when scoring.
| proficiency_  | String  | Optional. One of:        | "Advanced"  |     |
| ------------- | ------- | ------------------------ | ----------- | --- |
| level         |         | Beginner, Intermediate,  |             |     |
Advanced, Expert, or
null. Extracted and
stored, but not used in
the current scoring.
institution   String  Educational institution  "Chiang Mai University"
name

Document Name  CVision_Software_Design_ Owner  PS, RS  Page  6 / 21
Document_v3.docx
DocumentType  Software Design  Release Date  1/6/2026  Print Date  8/7/2026

degree String Degree or qualification "Bachelor of Science "
name
start_year, String Optional. Four-digit years 2019, 2023
end_year marking the start and
end of study. Either may
be null when the CV
does not state it.
company String Required. Employer "ABC Company"
name as written on the
CV.
position String Job title; 1–100 "Software Engineer"
characters
start_date String Optional. Free text as "2022", "Jan 2022"
written on the CV; the
system reads the
four-digit year from it to
measure duration.
end_date String Optional. Free text as "2025", "Present"
written on the CV.
"Present", "Current" or
an empty value counts
the role as ongoing to
the current year.
description String Optional. Free-text "Developed web applications..."
description of the role.
Stored with the CV but
not used by the matching
calculation.
Post 1. A match record is stored for every job listing evaluated, holding the match score, the
conditions matched skill tags and any CV categories that were missing.
2. Job listings are ranked in descending order by match score, ties broken deterministically so
that a stored ranking reproduces the order the Jobseeker saw.
3. The Jobseeker is presented with ranked job cards showing the match score (0.000–1.000),
Document Name CVision_Software_Design_ Owner PS, RS Page 7 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

|     |     |     |     |
| --- | --- | --- | --- |

| Normal Flows  | Jobseeker  | System  |     |
| ------------- | ---------- | ------- | --- |
    1.Display CV uploader UI with upload button and previous CV
  selector if the user login as Jobseeker and have uploaded a
|     |                                | CV before.  |     |
| --- | ------------------------------ | ----------- | --- |
|     | 2.Click the upload button and  |             |     |
|     | select their CV.               |             |     |
  3. Retrieves the Jobseeker's stored structured CV information
|     |     | (skills, education, work experience).      |     |
| --- | --- | ------------------------------------------ | --- |
|     |     |                                            |     |
|     |     | 4. Display upload successful notification  |     |
|     |     |                                            |     |
  5.Displays skills card, education card, work experience card
|     |     | from CV information.  |     |
| --- | --- | --------------------- | --- |
|     |     |                       |     |
  6. Retrieves all active, non-outdated job listings that have
|     |     | structured job data.  |     |
| --- | --- | --------------------- | --- |
|     |     |                       |     |
  7. Compares CV skills with each listing's required skills,
|     |     | weighting practical skills above general soft skills.  |     |
| --- | --- | ------------------------------------------------------ | --- |
|     |     |                                                        |     |
  8. Compares CV education with each listing's qualification
|     |     | requirement, by degree level and field of study.  |     |
| --- | --- | ------------------------------------------------- | --- |
|     |     |                                                   |     |
  9. Compares CV work experience with each listing's minimum
|     |     | years of experience.  |     |
| --- | --- | --------------------- | --- |
|     |     |                       |     |
  10. Calculates a matching score (0.000–1.000) for each listing
|     |     | from the three comparisons.  |     |
| --- | --- | ---------------------------- | --- |
|     |     |                              |     |
  11. Identifies the matched skills for each listing and generates
|     |     | skill tags.  |     |
| --- | --- | ------------ | --- |
|     |     |              |     |
  12. Ranks the listings by matching score in descending order.
|     |     |                                                           |     |
| --- | --- | --------------------------------------------------------- | --- |
|     |     | 13. Displays the ranked job cards below the extracted CV  |     |
|     |     | summary. Each card shows the job title, company name and  |     |
  location, the match score, a progress bar, matched skill tags
  and remaining required skills, and a "View Job Posting" link.
14. Reviews the extracted  The five highest-ranked cards also carry a short AI-written
|     | CV information and scrolls   | explanation of the fit.  |     |
| --- | ---------------------------- | ------------------------ | --- |
|     | down to view the ranked job  |                          |     |
|     | match results.               |                          |     |
|     |                              |                          |     |

Document Name  CVision_Software_Design_ Owner  PS, RS  Page  8 / 21
Document_v3.docx
DocumentType  Software Design  Release Date  1/6/2026  Print Date  8/7/2026

15. Clicks "View Job Posting"
on a job card.
16. Validates the stored job URL and opens it in a new
browser tab.
Alternative [A2: Returning Jobseeker Selects a Stored CV]
Flow A3: A Jobseeker with an account opens the list of their previously uploaded CVs and selects
one instead of uploading a new file.
A4: System retrieves that CV's stored structured information in place of the CV just uploaded.
A5: Returns to Step 3 in Normal Flows.
Exception [E10: Matching Calculation Error]
Flow E11: System encounters an internal error during the matching calculation, or is unable to read
from or write to storage.
E12: System displays an error message below the CV summary indicating that job matches
could not be generated at this time.
E13: Any partial results are rolled back, leaving previously stored results for this CV
unchanged.
[F2: CV Data Corrupted]
F3: System detects that the stored CV data is missing, unreadable, or contains no usable
skills, education or work experience.
F4: System displays an error message requesting the Jobseeker to re-upload their CV.
[G6: Invalid Job Posting URL]
G7: The stored job URL is missing or malformed when the job card is displayed.
G8: System displays a notification on that card that the job posting is no longer available, and
does not offer the "View Job Posting" link for it.
[H3: No Active Job Listings]
H4: System retrieves zero job listings that are active, non-outdated and enriched with
structured job data.
H5: System displays a message below the CV summary indicating that no job listings are
currently available for matching.
Document Name CVision_Software_Design_ Owner PS, RS Page 9 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

● SRS-047 : The system shall retrieve the Jobseeker's structured CV information (skills, education,
work experience) from stored CV data upon completion of CV upload and parsing (UC-005).
● SRS-048 : The system shall retrieve all active, non-outdated job listings previously fetched from
external job APIs (Feature #1) for which structured job data has been extracted, and shall exclude
any listing without that data from matching.
● SRS-049 : The system shall compare the Jobseeker's CV skills against each job listing's required
skills, matching case-insensitively and weighting practical skills more heavily than general soft skills
so that overlap on skills common to most roles does not outweigh overlap on the skills the role
actually requires.
● SRS-050 : The system shall compare the Jobseeker's CV education against each job listing's
qualification requirement, by comparing the attained degree level against the minimum level
required and the field of study against the fields the listing accepts, where listed fields are treated as
alternatives.
● SRS-051 : The system shall compare the Jobseeker's total years of work experience against each
job listing's minimum years of experience.
● SRS-052 : The system shall calculate a matching score, expressed as a decimal value between
0.000 and 1.000, for each job listing based on the CV-to-job comparison.
● SRS-053 : The system shall identify matched skills between the CV and each job listing and
generate corresponding skill tags for display.
● SRS-054 : The system shall rank job listings in descending order by matching scores, from highest
to lowest.
● SRS-055 : The system shall display ranked job match results below the extracted CV information
summary, with each job card showing the job title, company name and location, match score, a
progress bar, matched skill tags and remaining required skills, and a link to the original job posting.
● SRS-056 : The system shall open the external job posting URL in a new browser tab when the
Jobseeker selects "View Job Posting."
● SRS-057 : The system shall allow a Jobseeker with an account to select a previously uploaded CV
and generate job match results from that CV's stored information, without requiring a new upload.
Document Name CVision_Software_Design_ Owner PS, RS Page 10 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

● SRS-058 : The system shall calculate a matching score using only the available CV data
categories, and adjust the weighting of scoring factors accordingly, when one or more CV
categories (skills, education, or work experience) are missing or empty.
● SRS-059 : The system shall calculate a matching score based on available education and
experience factors and display the job card without skill tags when zero skill overlap is found
between the CV and a job listing.
● SRS-060 : The system shall display an error message indicating that job matches could not be
generated when an internal error occurs during the matching calculation.
● SRS-061 : The system shall display an error message requesting the Jobseeker to re-upload their
CV when the stored CV data is detected as corrupted or unreadable.
● SRS-062 : The system shall display a notification and withhold the "View Job Posting" link for a job
card when the stored job URL is missing or malformed, while continuing to process and display the
remaining job cards.
● SRS-063 : The system shall display a message indicating that no job listings are currently available
when zero active, non-outdated and enriched job listings exist for matching.
Document Name CVision_Software_Design_ Owner PS, RS Page 11 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

2.5 Software Requirement Specifications
URS-007: Jobseekers want the system to compare their extracted CV data with job descriptions retrieved from
external sources.
● SRS-047: The system shall retrieve the Jobseeker's structured CV information (skills, education, work
experience) from the database upon completion of CV upload and parsing (UC-005).
● SRS-048: The system shall retrieve all active, non-outdated job listings previously fetched from external job
APIs. (Feature#1)
● SRS-049: The system shall compare the Jobseeker's CV skills against each job listing's required skills.
● SRS-050: The system shall compare the Jobseeker's CV education against each job listing's qualification
requirements.
● SRS-051: The system shall compare the Jobseeker's CV work experience against each job listing's experience
requirements.
● SRS-057: The system shall display a message indicating that no job listings are currently available when zero
active job listings exist for matching.
● SRS-061: The system shall display an error message requesting the Jobseeker to re-upload their CV when the
stored CV data is detected as corrupted or unreadable.
URS-008: Jobseekers want the system to calculate a matching percentage for each job listing based on similarities in
skills, qualifications, and work experience.
● SRS-052: The system shall calculate a matching score, expressed as a decimal value between 0.000 and
1.000, for each job listing based on the CV-to-job comparison.
● SRS-058: The system shall calculate a matching score using only the available CV data categories, and adjust
the weighting of scoring factors accordingly, when one or more CV categories (skills, education, or work
experience) are missing or empty.
● SRS-060: The system shall display an error message indicating that job matches could not be generated when
an internal error occurs during the matching calculation.
Document Name CVision_Software_Design_ Owner PS, RS Page 12 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

URS-009: Jobseekers want to view the matching percentage and a breakdown of matches for each job listing to
understand their suitability.
● SRS-053: The system shall identify matched skills between the CV and each job listing and generate
corresponding skill tags for display.
● SRS-055: The system shall display ranked job match results below the extracted CV information summary,
with each job card showing the job title, company name and location, match score, matched skill tags, and a
link to the original job posting.
● SRS-056: The system shall open the external job posting URL in a new browser tab when the Jobseeker
selects "View Job Posting."
● SRS-059: The system shall calculate a matching score based on available education and experience factors
and display the job card without skill tags when zero skill overlap is found between the CV and a job listing.
● SRS-062: The system shall display a notification and disable the "View Job Posting" link for a job card when
the stored job URL is invalid or the external site is unreachable, while continuing to process and display the
remaining job cards.
URS-010: Jobseekers want the system to rank job listings according to their matching percentage to help identify the
most suitable job opportunities.
● SRS-054: The system shall rank job listings in descending order by matching scores, from highest to lowest.
Document Name CVision_Software_Design_ Owner PS, RS Page 13 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

Chapter Three | Detailed Design
3.1 Entity Relationship Diagram
3.1.1 Entity Relationship Diagram
3.1.1.1 Feature #2: Job Matching
Document Name CVision_Software_Design_ Owner PS, RS Page 14 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

3.1.2 Data Dictionary
3.1.3 File Structure
Document Name CVision_Software_Design_ Owner PS, RS Page 15 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

3.2 Sequence Diagram
3.2.1 Feature #
SD-F1-01
Document Name CVision_Software_Design_ Owner PS, RS Page 16 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

Chapter Four | Detailed Design
4.1 Method Description
Feature #2: Job Matching
M-02-01
retrieveCVData(cvId: string): CVData
Description:
Retrieves the Jobseeker's structured CV information (skills, education, work experience) from the database upon
completion of CV upload and parsing (UC-005). Queries the CV_extracted record along with its associated
Skill, Education, and WORK_EXPERIENCE rows for the given cvId. Parameters:
cvId: string — The unique identifier of the Jobseeker's stored CV data.
Returns:
CVData — object containing the skills, education, and work experience arrays extracted from the CV.
Throws:
CVDataCorruptedException — if the stored CV data is detected as corrupted or unreadable; prompts the Jobseeker to
re-upload their CV (Exception Flow E2).
M-02-02
retrieveActiveJobListings(): list<JobListing>
Description:
Retrieves all active, non-outdated job listings previously fetched from external job APIs (Feature #1) for use in
matching. Filters out listings where outdated_manual is true.
Parameters: -
Returns:
list<JobListing> — active job listings available for matching. Returns an empty list when zero active listings exist.
Throws: -
Document Name CVision_Software_Design_ Owner PS, RS Page 17 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

M-02-03
compareSkills(cvSkills: list<Skill>, jobSkills: list<string>):
SkillComparisonResult
Description:
Compares the Jobseeker's CV skills against a job listing's required skills to identify overlapping entries. Performs
case-insensitive matching between each Skill.skill_name and the job's listed required skills.
Parameters:
cvSkills: list<Skill> — Skills extracted from the Jobseeker's CV.
jobSkills: list<string> — Required skills listed for the job.
Returns:
SkillComparisonResult — the overlapping skills and a skill match ratio (0.000–1.000).
Throws: -
M-02-04
compareEducation(cvEducation: list<Education>, jobRequirements:
JobQualification): EducationComparisonResult
Description:
Compares the Jobseeker's CV education history against a job listing's qualification requirements (e.g. minimum
degree level, field of study).
Parameters:
cvEducation: list<Education> — Education entries extracted from the CV.
jobRequirements: JobQualification — Qualification requirements defined for the job listing.
Returns:
EducationComparisonResult — a qualification match indicator and an education match ratio (0.000–1.000).
Throws: -
Document Name CVision_Software_Design_ Owner PS, RS Page 18 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

M-02-05
compareExperience(cvExperience: list<WorkExperience>, jobRequirements:
JobQualification): ExperienceComparisonResult
Description:
Compares the Jobseeker's CV work experience against a job listing's experience requirements (e.g. minimum years,
relevant role history).
Parameters:
cvExperience: list<WorkExperience> — Work experience entries extracted from the CV.
jobRequirements: JobQualification — Experience requirements defined for the job listing.
Returns:
ExperienceComparisonResult — a relevance indicator and an experience match ratio (0.000–1.000).
Throws: -
M-02-06
calculateMatchScore(skillResult: SkillComparisonResult, educationResult:
EducationComparisonResult, experienceResult: ExperienceComparisonResult,
availableCategories: list<string>): number
Description:
Calculates an overall matching score, expressed as a decimal value between 0.000 and 1.000, by combining the
weighted results of the skill, education, and experience comparisons (SRS-052). When one or more CV categories are
missing or empty, use only the available categories and adjust the weighting of the remaining factors accordingly
(SRS-058, Alternative Flow B).
Parameters:
skillResult: SkillComparisonResult — Result from compareSkills.
educationResult: EducationComparisonResult — Result from compareEducation.
experienceResult: ExperienceComparisonResult — Result from compareExperience.
availableCategories: list<string> — The CV categories (skills, education, experience) that contained data.
Returns:
number — the calculated matching score (0.000–1.000).
Throws:
MatchingCalculationException — if an internal error occurs during score calculation (Exception Flow E1).
Document Name CVision_Software_Design_ Owner PS, RS Page 19 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

M-02-07
identifyMatchedSkills(cvSkills: list<Skill>, jobSkills: list<string>):
list<string>
Description:
Identifies the specific skills that overlap between the CV and a job listing and generates the corresponding skill tags
for display on the job card. When zero skill overlap is found, returns an empty list and matching continues using
education and experience factors only (Alternative Flow C).
Parameters:
cvSkills: list<Skill> — Skills extracted from the Jobseeker's CV.
jobSkills: list<string> — Required skills listed for the job.
Returns:
list<string> — the matched skill tags. Empty when no overlap exists.
Throws: -
M-02-08
rankJobMatches(matches: list<JobMatchResult>): list<JobMatchResult>
Description:
Sorts the calculated job match results in descending order by matching score, from highest to lowest suitability.
Parameters:
matches: list<JobMatchResult> — Unranked job match results, each containing a job listing and its calculated score.
Returns:
list<JobMatchResult> — the same results, ranked by descending match score.
Throws: -
M-02-09
storeJobMatchResults(cvId: string, matches: list<JobMatchResult>): void
Description:
Persists the calculated and ranked job match results to the JobMatch table, recording the match score, matched skill
tags, and any missing CV categories for each job listing evaluated against the given CV.
Parameters:
cvId: string — The Jobseeker's CV identifier the matches belong to.
matches: list<JobMatchResult> — The ranked job match results to persist.
Returns: void
Throws:
DatabaseException — if any database insert fails, causing the transaction to be rolled back.
Document Name CVision_Software_Design_ Owner PS, RS Page 20 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026

M-02-10
displayJobMatchResults(cvId: string): void
Description:
Retrieves the stored job match results for the given CV and renders the ranked job cards below the extracted CV
information summary on the CV upload page. Each card shows the job title, company name and location, match score,
matched skill tags, and a link to view the original job posting. If zero active job listings exist for matching, displays a
message indicating no listings are currently available (SRS-057).
Parameters:
cvId: string — The unique identifier of the CV whose job matches are to be displayed.
Returns: void
Throws: -
M-02-11
openJobPosting(url: string): void
Description:
Opens the external job posting URL in a new browser tab when the Jobseeker selects "View Job Posting" on a job
card (SRS-056). If the stored URL is invalid or the external site is unreachable, displays a notification and disables the
"View Job Posting" link for that card without interrupting the remaining job cards (Exception Flow E3, SRS-062).
Parameters:
url: string — The external job posting URL stored on the job listing.
Returns: void
Throws:
JobPostingUnavailableException — if the URL is invalid or the external site cannot be reached.
M-02-12
handleMatchingError(exception: Exception): string
Description:
Maps job-matching related exceptions to their corresponding user-facing error messages. Maps
MatchingCalculationException to "Job matches could not be generated at this time",
CVDataCorruptedException to "Your CV data could not be read — please re-upload your CV", and
JobPostingUnavailableException to "This job posting is no longer available". If the exception type does
not match any known matching error, returns a generic "An unexpected error occurred. Please try again" message.
Parameters:
exception: Exception — The exception thrown during the matching or display process.
Returns:
string — the user-facing error message corresponding to the exception type.
Throws: none.
Document Name CVision_Software_Design_ Owner PS, RS Page 21 / 21
Document_v3.docx
DocumentType Software Design Release Date 1/6/2026 Print Date 8/7/2026