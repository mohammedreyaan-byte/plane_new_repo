# PLN-015 PR checklist

Use this checklist in the pull-request description. All commands are run from the repository root. Do not commit or push from the validation workspace without an explicit owner request.

## Scope and compatibility

- [x] Work performed on branch `dev`; no commit/push was made.
- [x] Pre-existing uncommitted PLN-017/email-worker work was preserved.
- [x] Forbidden files were not edited: email worker files, `apps/api/pytest.ini`, `apps/api/plane/settings/common.py`, `apps/api/plane/license/**`, `docs/evidence/**`, production `docker-compose.yml`, `Plane Tickets.xlsx`, `instructions.md`, and `.playwright-mcp` screenshots.
- [x] No `docker compose down -v`, no credentials, no non-placeholder external hosts.

## Fixed surfaces and proving tests

| Surface                                                      | Fix                                                                                                                                         | Test                                                                                                                                                                               |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Project resolution                                           | `resolve_request_project()` filters by workspace slug; unknown/cross-workspace project -> `404`.                                            | `test_resolve_project_rejects_cross_workspace_id`, `test_cross_workspace_project_id_is_hidden`                                                                                     |
| Membership                                                   | `require_project_membership()` checks only active `ProjectMember`; workspace role is never proof. Admin override is logged.                 | `test_membership_never_infers_permission_from_workspace_role`, `test_workspace_member_without_project_membership_is_denied`                                                        |
| Object IDs under a project                                   | Detail requests without membership -> `404`; view querysets remain project-filtered.                                                        | `test_detail_lookup_hides_and_collection_denies`, `test_issue_from_another_project_is_hidden`                                                                                      |
| Body/URL mismatch                                            | `assert_body_project_matches()` -> `400 project_mismatch`.                                                                                  | `test_body_project_mismatch_raises_400`, `test_body_project_id_must_match_url`                                                                                                     |
| Guest visibility                                             | `is_guest_restricted()`, `visible_objects()`, `guest_visibility_q()` applied to lists/details/comments/attachments/activity/search/exports. | `test_guest_sees_only_own_issues`, `test_restricted_guest_only_sees_own_issues`                                                                                                    |
| Search, analytics, exports, drafts, favorites, recent visits | Querysets reuse the visibility helpers; export URLs are requester-only and rechecked.                                                       | Helper unit tests plus representative contract tests; full per-endpoint matrix noted as a limitation.                                                                              |
| Attachments/files                                            | Central membership check plus parent-object checks; private 15-minute signed URLs.                                                          | `test_every_project_scoped_callback_enforces_central_scope`, docs deployment note.                                                                                                 |
| Service tokens                                               | Hashed storage, plaintext once, explicit workspace/project scope enforced centrally.                                                        | `test_service_token_scope_enforces_workspace_and_project`, `test_api_tokens_are_hashed_and_plaintext_only_once`, `test_service_token_cannot_cross_project_or_workspace_boundaries` |
| Invitation accept                                            | Per-IP and per-email throttle.                                                                                                              | `test_invitation_accept_is_rate_limited`                                                                                                                                           |
| Webhook receiver                                             | Per-IP and per-workspace/provider throttle; uniform rejection envelope; deterministic dedupe.                                               | `test_webhook_rejections_are_indistinguishable`, `test_webhook_receiver_is_rate_limited`                                                                                           |
| URL coverage                                                 | Exact 220-route manifest plus static mixin check fails closed on new routes.                                                                | `test_committed_matrix_matches_urlconf`, `test_every_project_scoped_callback_enforces_central_scope`                                                                               |

## CI and markers

- [x] Added `.github/workflows/pln015-security.yml` running the focused suite with `--build`.
- [ ] **Maintainer action:** mark the `Project isolation authorization suite` job as required in branch protection for `dev`/`main`.
- [x] Suite uses only registered `unit` and `contract` markers.
- [ ] **Maintainer decision:** register a `security` marker in `apps/api/pytest.ini` so the suite can be selected by `-m security`. `pytest.ini` was not edited in this workspace.

## Model/migration handoff

- [x] Added `apps/api/plane/db/migrations/0142_service_token_scope.py`.
- [x] `APIToken` fields added in `plane/db/models/api.py`; `hash_api_token()` imported from that module because `db/models/__init__.py` was off-limits.
- [ ] **Optional follow-up:** re-export `hash_api_token` from `plane/db/models/__init__.py` if package-root imports are preferred. No functional change is required for this PR.
- [ ] Apply the migration in deployment order before enabling hashed-only token validation.

## Additional reviewer decisions

- [ ] Confirm the workspace-admin override should remain for external access; it is logged with identifiers only.
- [ ] Confirm private bucket policy and CDN cache rules; signed URLs alone do not prevent public reads.
- [ ] Schedule generic email-existence responses separately; current auth contract tests require `USER_DOES_NOT_EXIST`.
- [ ] Rotate legacy plaintext API tokens after deployment.
- [ ] Complete the live method × actor × endpoint matrix automation; current coverage is exact-route static enforcement plus representative end-to-end cases.

## Evidence

- Evidence JSON: `../.playwright-mcp/issue-pln015-backend-result.json`
- Source docs: `docs/security/project-isolation.md`, `docs/security/isolation-incident-runbook.md`, this checklist.
- Route manifest: `apps/api/plane/tests/security/matrix.py`
