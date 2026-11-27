# PLN-015 project isolation

This document describes the backend isolation boundary introduced for PLN-015. It covers the API surfaces under `apps/api`; hiding UI controls is not part of the guarantee.

## Invariants

| ID  | Invariant                                                                               | Enforcement                                                                                                                                                                         |
| --- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| I1  | A project-scoped object is readable only by an active member of that project.           | `ProjectScopeMixin.initial()` calls `check_project_scope()` before the view body. Workspace-admin overrides remain for compatibility but are logged with identifiers only.          |
| I2  | Mutations require membership plus the existing capability matrix.                       | The central check is a precondition; existing role/capability decorators are unchanged.                                                                                             |
| I3  | Inaccessible object IDs return `404`; inaccessible collections/mutations return `403`.  | `check_project_scope()` treats object-ID kwargs as detail lookups and raises `Http404`/`PermissionDenied` accordingly.                                                              |
| I4  | Counts, aggregates, search facets and exports use already-scoped querysets.             | `visible_objects()`, `visible_issues()`, `membership_q()` and `guest_visibility_q()` are the shared filters.                                                                        |
| I5  | Restricted guests see only their own items unless `guest_view_all_features` is enabled. | `is_guest_restricted()` and the visibility helpers are reused by lists, details, comments, attachments, activity, search and exports.                                               |
| I6  | Service tokens are bound to workspace and explicit project scope.                       | `token_scope_violation()` compares the **token's** workspace against both the URL slug and resolved project. Project-list mismatch returns `403`; workspace mismatch returns `401`. |
| I7  | Soft-deleted objects stay out of counts and normal lists.                               | Existing manager/state filters are retained; scoping helpers do not bypass them.                                                                                                    |

## Central implementation

- `plane/utils/permissions/project_scope.py` owns project resolution, membership checks, guest visibility, token scope and the error contract.
- `plane/app/views/base.py` and `plane/api/views/base.py` each define `ProjectScopeMixin`. Both call the same helper from `initial()`.
- Permission modules import the helper lazily inside request-time functions to avoid the existing import cycle.
- New API tokens are stored as SHA-256 hashes with a display prefix. The plaintext is returned once by `APITokenSerializer` at creation time; legacy plaintext rows still authenticate.
- Failed token lookups, invitation accepts and provider-webhook deliveries use fixed-window counters in `plane/api/rate_limit.py`. Cache keys contain hashed identifiers, never credentials.

### Error contract

| Situation                                                | Response                                                                                                           |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Unknown/cross-workspace project in URL                   | `404`                                                                                                              |
| Object ID under a project the caller cannot access       | `404`                                                                                                              |
| Collection or mutation without active project membership | `403`                                                                                                              |
| Body `project_id` differs from URL project               | `400` with `{"error":{"code":"project_mismatch","message":"The project does not match the request."}}`             |
| Service token used outside its project scope             | `403`                                                                                                              |
| Service token used outside its workspace                 | `401`                                                                                                              |
| Rejected provider webhook                                | `401` with the constant `{"error":{"code":"webhook_rejected","message":"The webhook was not accepted."}}` envelope |

## Route matrix

`apps/api/plane/tests/security/matrix.py` is the exact source-of-truth manifest: **220 project-scoped routes** generated from Django's URLconf. `test_url_coverage.py` asserts:

1. the committed manifest equals the live URLconf, so a new route fails CI until it is reviewed; and
2. every manifest route resolves to a DRF class that inherits `ProjectScopeMixin` and does not opt out, unless the exact route appears in `PUBLIC_ROUTES`.

The manifest covers app, v1 API, asset, public/space, and GMC feature routes. It intentionally includes paths with `project_id` or `project_identifier` even when the view is public; those are listed explicitly in the allowlist.

## Allowlist

`apps/api/plane/tests/security/allowlist.py` is the only place a project-scoped route may skip central membership checks. Current exact exemption:

| Route                                                                 | Reason                                                                                                                |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `api/public/workspaces/<str:slug>/projects/<uuid:project_id>/anchor/` | Public deploy-board anchor resolves an opaque share link; access is granted by `DeployBoard`, not project membership. |

Other entries are non-project-scoped public prefixes (authentication, invitations, OAuth callbacks, instance config, health, docs). A new entry must name the exact failing route and explain the independent authorization mechanism.

## Exports and attachments

- Export history stores the requester. The serializer rechecks membership for each project in the job and hides the URL unless the requester initiated the job.
- Signed URLs are private and expire in 15 minutes (`SIGNED_URL_EXPIRATION` default `900`; task argument `15 * 60`). The `public-read` ACL was removed.
- **Deployment requirement:** the bucket policy must not grant public `GetObject`. A permissive bucket policy can bypass application-level checks; verify the storage account policy and CDN/cache configuration separately.
- Attachment download endpoints require active project membership through the central mixin and the existing parent-object checks.

## Webhooks and notifications

- Provider webhooks are throttled per IP and per workspace/provider. All rejections use one status and envelope so callers cannot probe for configured integrations.
- Provider delivery headers are preserved for deduplication. Header-less deliveries use a deterministic SHA-256 of provider, workspace, event type and body, so retries do not create duplicate events.
- Workspace webhooks remain admin-configured and may cover all workspace projects; this exposure is intentional and must not be granted to project guests.
- Notification delivery continues to rely on the existing send-time filtering; a removed member must stop receiving project notifications.

## Known limitations and reviewer decisions

1. **Workspace-admin override:** workspace admins who are not project members still get access, but every occurrence is logged to `plane.security.isolation` with user/project/workspace identifiers, method and path only. No names, emails, tokens or payloads are logged. Reviewers should decide whether to remove this compatibility behaviour for external deployments.
2. **Email enumeration:** existing contract tests require `USER_DOES_NOT_EXIST` for sign-in, so generic "check your email" responses were not introduced. Login, magic-link and password-reset endpoints already use `AuthenticationThrottle`; changing the response contract needs a separate ticket.
3. **Test depth:** the coverage guard statically proves the central mixin on all 220 routes, and end-to-end tests exercise representative list, detail, mutation, guest, token, webhook and invite flows. It does not issue one live request per method × actor × endpoint; the full matrix remains a follow-up automation item.
4. **Legacy tokens:** plaintext legacy token rows remain valid for migration compatibility. New tokens are hashed; rotate all pre-PLN-015 tokens after deployment.
5. **Bucket policy:** private signed URLs are necessary but not sufficient if the object store allows public reads. This is an infrastructure check, not covered by pytest.

## Adding a new project-scoped endpoint safely

1. Inherit from `plane.app.views.base.BaseAPIView`/`BaseViewSet` or `plane.api.views.base.BaseAPIView`.
2. Do not set `skip_project_scope = True`.
3. Use `request.project_scope` (set by the mixin) rather than re-reading `request.data["project_id"]`.
4. Filter object lookups by `project_id=request.project_scope.id`; never use a bare `pk` lookup.
5. For lists/counts/search/exports, apply `visible_objects()` or `visible_issues()`.
6. If the route is genuinely public, add the **exact** route to `PUBLIC_ROUTES` with an independent authorization explanation.
7. Regenerate/extend `matrix.py`, add a representative contract test, and run:

   ```bash
   docker compose -p gmc-pln015-test -f docker-compose-test.yml run --rm --build api-tests \
     pytest plane/tests/unit/utils/test_project_scope.py plane/tests/security -vv
   ```

Do not run `-m security` until the marker is registered in `apps/api/pytest.ini`; the suite uses the registered `unit` and `contract` markers.
