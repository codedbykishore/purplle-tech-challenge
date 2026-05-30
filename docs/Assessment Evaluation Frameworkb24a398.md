Store Intelligence Challenge — Evaluation Framework
1. Context and Evaluation Philosophy
This challenge is intentionally designed as an end-to-end system problem — not a model-
building exercise.
Candidates are expected to start from raw CCTV footage and build a complete pipeline
that produces meaningful business metrics such as store conversion rate. As outlined in the
challenge briefly, the goal is not perfect detection accuracy, but the ability to:
• Decompose a real-world ambiguous problem
• Build a working system with reasonable assumptions
• Handle known edge cases (re-entry, staff movement, occlusion, etc.)
• Translate raw signals into business-relevant insights
Accordingly, this evaluation framework prioritizes:
• Functional correctness over theoretical completeness
• Engineering judgment over model complexity
• Clarity of reasoning over volume of implementation
A candidate is not expected to build a perfect system. A strong candidate is one who
builds a system that works, makes reasonable trade-offs, and can clearly explain those
decisions.
2. Evaluation Process Overview
The evaluation is conducted in three stages:
Stage Purpose
Acceptance Gate Eliminate incomplete or non-functional submissions
Structured Scoring Evaluate technical quality and system correctness
Identify top 30 candidates based on score and
Final Shortlisting
consistency
Each submission is evaluated independently by two reviewers.
3. Acceptance Gate (Mandatory)
Submissions must satisfy the following:
Check Requirement
System Execution docker compose up runs without manual intervention
API Availability /Metrics endpoint returns a valid response
Event Generation Detection pipeline produces structured events
Documentation DESIGN.md and CHOICES.md are present and non-trivial
1 UpGrad Placements - April 2026

| Stability  |     | System does not crash during basic execution  |     |     |
| ---------- | --- | --------------------------------------------- | --- | --- |

Failure in any of the above results in rejection prior to scoring.
4. Reviewer Evaluation Approach
Each submission is evaluated within a structured time window to ensure consistency:

Time  Activity
|     | 2 minutes  | Run system and verify API        |     |     |
| --- | ---------- | -------------------------------- | --- | --- |
|     | 2 minutes  | Inspect generated events         |     |     |
|     | 3 minutes  | Validate API outputs             |     |     |
|     | 2 minutes  | Review DESIGN.md and CHOICES.md  |     |     |
|     | 1 minute   | Assign scores                    |     |     |

05 Scoring Framework (100 Marks)
5.1  Detection Pipeline (30 Marks)

| Criteria     |                                     | Strong           | Moderate    | Weak         |
| ------------ | ----------------------------------- | ---------------- | ----------- | ------------ |
|              | Close to actual counts (within      |                  | Noticeable  |              |
| Entry/Exit:  |                                     |                  |             | Unreliable   |
|              | reasonable error margin)            |                  | deviation   |              |
|              | Handles re-entry, staff, and group  |                  | Partial     |              |
| Accuracy:    |                                     |                  |             | Not handled  |
|              |                                     | entry correctly  | handling    |              |
Minor
| Edge Case  | Structured, complete, and consistent  |     |     | Poor or  |
| ---------- | ------------------------------------- | --- | --- | -------- |
inconsistencie
| Handling:  |     | events  |     | incomplete  |
| ---------- | --- | ------- | --- | ----------- |
s

VALIDATION APPROACH
•  Run a sample clip and compare approximate entry counts with system output
•  Inspect event schema for completeness and consistency

5.2  API and Business Logic (35 Marks)

| Criteria  |     | Strong  | Moderate  | Weak  |
| --------- | --- | ------- | --------- | ----- |
Endpoint/Corre All endpoints return correct and  Minor  Incorrect
| ctness:  |     | consistent results  | inconsistencies  | outputs  |
| -------- | --- | ------------------- | ---------------- | -------- |
Session-based, no double
| Funnel Logic:  |     |     | Basic  | Missing  |
| -------------- | --- | --- | ------ | -------- |
counting
Anomaly
|     | Logical and meaningful  |     | Basic  | Missing  |
| --- | ----------------------- | --- | ------ | -------- |
Detection:

| VALIDATION  | APPROACH  |     |     |     |
| ----------- | --------- | --- | --- | --- |
/metrics returns logically consistent values
/funnel shows expected drop-off behavior

2
 UpGrad Placements - April 2026

5.3  Production Readiness (20 Marks)

|     | Criteria  |                               |     | Strong  |     | Moderate        |     | Weak  |
| --- | --------- | ----------------------------- | --- | ------- | --- | --------------- | --- | ----- |
|     |           | Runs seamlessly with minimal  |     |         |     | Requires minor  |     | Not   |
Deployment:
|     |     |     |     | setup  |     | effort  | functional  |     |
| --- | --- | --- | --- | ------ | --- | ------- | ----------- | --- |
Comprehensive (logs, metrics,
| Observability:  |     |     |     |     |     | Partial  |     | Missing  |
| --------------- | --- | --- | --- | --- | --- | -------- | --- | -------- |
tracing)
Covers key scenarios and edge
|     | Testing:  |     |     |     | Limited coverage  |     | No testing  |     |
| --- | --------- | --- | --- | --- | ----------------- | --- | ----------- | --- |
cases

5.4  Engineering Thinking and Decision Making (15 Marks)

|     | Criteria  |     |     | Strong  |     | Moderate  |     | Weak  |
| --- | --------- | --- | --- | ------- | --- | --------- | --- | ----- |
CHOICES.md:  Clear trade-offs and justification  Some reasoning  Generic
Basic
|     | DESIGN.md:  |     | Clear system architecture  |     |     |     |     | Unclear  |
| --- | ----------- | --- | -------------------------- | --- | --- | --- | --- | -------- |
explanation
|     | Reasoning  |     | Demonstrates independent  |     |     |     |     | Superficia |
| --- | ---------- | --- | ------------------------- | --- | --- | --- | --- | ---------- |
Limited depth
|     | Depth:  |     |     | thinking  |     |     |     | l   |
| --- | ------- | --- | --- | --------- | --- | --- | --- | --- |

Reviewers should assess whether the candidate demonstrates ownership of
decisions or relies on generic explanations.
06 Integrity Check
To ensure authenticity of submissions:

|     |     |                                 |                           | Check  |                     | Action  |     |     |
| --- | --- | ------------------------------- | ------------------------- | ------ | ------------------- | ------- | --- | --- |
|     |     | Hardcoded outputs suspected     |                           |        | Score capped at 50  |         |     |     |
|     |     | Outputs do not vary with input  |                           |        | Score capped at 50  |         |     |     |
|     |     |                                 | Lack of real computation  |        | Score capped at 50  |         |     |     |
07 Final Scoring and Shortlisting
Final score is computed as:

Total = Detection (30) + API (35) + Production (20) + Thinking (15)
|     |     |     |     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
3
 UpGrad Placements - April 2026

Shortlisting guidelines:
Score Range Interpretation
85+ Strong candidate
70-85 Suitable for interview
60-70 Above Average
Top 30 candidates are selected based on score and consistency across reviewers.
8. Tie-Breaking Criteria
In cases of similar scores, preference is given to candidates who demonstrate:
Better handling of edge cases
Cleaner and more maintainable system design
Stronger understanding of the underlying business metric Clear and structured reasoning
9. Evaluation Principle
This framework is designed to identify candidates who can:
• Build working systems under constraints
• Handle real-world ambiguity
• Make and justify engineering decision
4 UpGrad Placements - April 2026