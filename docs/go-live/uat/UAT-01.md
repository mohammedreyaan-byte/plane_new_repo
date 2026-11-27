# UAT-01 — Workspace and project access

- **Status:** NOT EXECUTED
- **Source:** `prompts/27-PLN-027.txt` UAT plan
- **Business process:** Workspace and project access

## Objective

Confirm that an administrator can invite the 15 users with the correct roles and
that each user signs in and sees only the projects and capabilities their role
allows.

## Preconditions

- Staging release candidate is deployed and healthy.
- A UAT coordinator, workspace admin and named test users are recorded.
- Role matrix for Developer, QA, Viewer and Guest is agreed in writing.

## Steps and expected results

|   # | Step                                                                    | Expected result                                                                     | Actual result | Pass/Fail |
| --: | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------- | --------- |
|   1 | As workspace admin, invite all 15 named users with their assigned roles | All 15 invitations are created; roles match the agreed matrix                       |               |           |
|   2 | Each user accepts the invite and signs in to staging                    | Each user reaches the workspace home without error                                  |               |           |
|   3 | Each user lists visible projects                                        | Developer/QA/Viewer see only their assigned projects; Guest sees only allowed items |               |           |
|   4 | Attempt to open a project the user is not a member of                   | Access is denied with a not-found or permission response; no data leaks             |               |           |
|   5 | Check available actions per role                                        | Actions match the role matrix; restricted actions are absent or blocked             |               |           |
|   6 | Remove one test member and retry access                                 | Removed member can no longer open the project                                       |               |           |

## Result record

| Field          | Value         |
| -------------- | ------------- |
| Tester         |               |
| Date           |               |
| Overall result | Pending       |
| Evidence file  | None recorded |
| Defect ID      |               |
| Notes          |               |
