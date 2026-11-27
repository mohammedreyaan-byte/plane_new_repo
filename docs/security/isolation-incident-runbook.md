# Isolation incident runbook (PLN-015)

Use this when someone reports that a user saw, changed, exported or downloaded data from a project they do not belong to.

## 1. Triage in 15 minutes

1. Record the exact URL, method, actor role, project/workspace IDs, timestamp and request ID.
2. Determine the boundary crossed:
   - same workspace, different project -> project membership / object lookup;
   - different workspace -> workspace resolution / token scope;
   - guest saw another user's item -> guest visibility helper;
   - export or signed URL -> requester recheck / URL expiration;
   - webhook or integration -> provider signature / dedupe / throttle.
3. Check whether the route is in `apps/api/plane/tests/security/matrix.py`. If it is absent, the URL-coverage guard did not run for the latest route change.
4. Check whether the route callback inherits `ProjectScopeMixin` and whether `skip_project_scope` was set. An exact exemption must exist in `apps/api/plane/tests/security/allowlist.py`.

## 2. Contain

- For token abuse: revoke the token (`revoked_at`) and rotate affected credentials. New tokens are hashed; legacy plaintext rows should be rotated.
- For a single route: add the failing case to `plane/tests/security/test_project_isolation.py` and verify it fails before changing production code.
- For a systemic scoping bypass: temporarily disable the affected endpoint or enforce membership at the base mixin for its whole module; do not rely on hiding UI navigation.
- For signed URLs: invalidate/rotate storage keys if a URL escaped its 15-minute window, and verify the bucket is private.

## 3. Reproduce as a test

Use the shared `isolation_context` fixture. It provides two workspaces, three projects, an owner, member, restricted guest, workspace outsider, service identity, and issues in each project. Add the smallest test that demonstrates the leak:

- object fetch from project B under project A -> expect `404`;
- collection/mutation without project membership -> expect `403`;
- body/URL mismatch -> expect `400 project_mismatch`;
- restricted guest -> expect only their own objects;
- service token outside its project/workspace -> expect `403`/`401`.

Run:

```bash
docker compose -p gmc-pln015-test -f docker-compose-test.yml run --rm --build api-tests \
  pytest plane/tests/unit/utils/test_project_scope.py plane/tests/security -vv
```

## 4. Fix

- Put the fix in `plane/utils/permissions/project_scope.py` when it applies to multiple views.
- Keep object lookups filtered by the URL project. Do not trust `project_id` from the body.
- Reuse `visible_objects()` / `visible_issues()` for counts, search and exports.
- Keep the permission decorators intact; central scoping is an additional precondition.
- If the change affects a public route, update the allowlist with a precise justification, never a broad prefix that covers scoped routes.

## 5. Audit and follow-up

- Search `plane.security.isolation` logs for `project_scope.workspace_admin_override`. Only identifiers, method and path should be present. Escalate if emails, names, payloads or tokens appear.
- Search webhook rejections by the stable code `webhook_rejected`; confirm no success event was created for a rejected delivery.
- Confirm cache counters for `invitation_accept`, `webhook_receiver` and token failures were populated during the incident window.
- If data was exposed, notify the workspace owner with object identifiers and timestamps; avoid including restricted content in the notification itself.
- Add the regression test to the required CI job before closing the incident.

## Escalation

P1 isolation bugs block external access. Escalate to the backend security owner and the workspace administrator. If bucket policy allowed public reads, escalate to infrastructure at the same time because application controls cannot compensate for public object storage.
