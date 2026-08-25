# Generation 1 Security Phase B Activation Checklist

## Status and authority

This checklist governs GitHub Issue #23 Phase B. Gate A was implemented and
reviewed in PR #28 under explicit operator approval. Its merge does not
authorize Google Cloud configuration, Railway variable changes, live store
bootstrap, deployment, live OAuth, service restart, live credential read-back,
maturity promotion, or Issue #24 activation.

Phase A is merged at **Prototype** maturity. Phase B must preserve the
single-operator architecture, existing calendar approval rules, fail-loud
behavior, and the separation of code, operator knowledge, credentials, and
runtime/audit state.

No secret value, authorization code, provider token, encryption key, or real
operator knowledge may be pasted into chat, committed to GitHub, included in an
issue/PR, or printed in an acceptance receipt.

## Gate A result

The reviewed repository now contains the narrow, default-off activation
adapter. It adds OAuth start/callback/clean-completion routes, authenticated
sanitized credential read-back, and explicit one-time bootstrap plus no-create
structural check commands. It reuses the existing Railway HTTP listener and is
enabled only by `MISSION_CONTROL_SECURITY_HTTP_ENABLED=true`.

Canonical run #49 passed 136 tests and every existing acceptance harness on the
initial PR #28 head. No Google or Railway configuration, live credential,
deployment, provider grant, external action, or Calendar mutation occurred.
Do not configure a Google redirect URI or enter live Railway secrets until Gate
B or Gate C, respectively, receives its own approval.

The narrow adapter may expose only what Issue #23 needs:

- start a one-time server-side Google authorization transaction;
- receive the exact HTTPS callback without exposing the authorization code to
  page resources, logs, analytics, or third-party scripts;
- create the existing secure operator session;
- run sanitized persisted-credential read-back;
- explicitly bootstrap the two security databases once; and
- reopen existing stores without silently creating replacements.

It must not build the Issue #24 web application, add a user-management system,
request Gmail scopes, or execute calendar mutations.

## Approval map

| Gate | Separate approval authorizes | It does not authorize |
|---|---|---|
| A — Phase B activation adapter | Implement, test, publish, and review the minimal callback/bootstrap/read-back surface | Google/Railway configuration, live credentials, deployment, merge without its own approval |
| B — Google Cloud configuration | Create/configure the dedicated OAuth project, consent screen, scopes, test user, and Web Application client | Entering secrets into Railway or running OAuth |
| C — Railway configuration and deployment | Create approved volume roots, enter variables, seal secrets, run explicit bootstrap, and deploy the reviewed adapter | Granting Google consent or promoting maturity |
| D — Live OAuth and first read-back | Authorize the exact operator account and perform sanitized identity/primary-Calendar read-back | Calendar event creation, modification, deletion, Gmail access, or standing external-action approval |
| E — Restart and post-restart read-back | Restart the existing Railway deployment and verify the persisted authorization without re-consent | Redeploying unrelated code, rotating/deleting secrets, or Tested promotion |
| F — Acceptance and promotion | Review evidence, decide the Google Testing-status limitation, promote to Tested, close Issue #23, and activate Issue #24 if explicitly approved | Stable maturity, multi-user tenancy, Gmail work, or autonomous actions |

An approval at one gate does not carry forward to the next gate.

## Gate A — activation adapter readiness

- [x] Confirm work starts from current canonical `main` and Issue #23 remains
      the active milestone.
- [x] Add the smallest replaceable HTTP/command adapter required for live
      authorization, explicit bootstrap, and read-back.
- [x] Keep provider tokens server-side and use the existing
      `SingleOperatorSecurityBoundary` and `GoogleOAuthProvider` contracts.
- [x] Preserve one-time state, encrypted PKCE verifier, ten-minute default
      transaction expiry, exact redirect URI, and replay rejection.
- [x] Ensure the callback consumes the authorization response, then redirects
      to a clean result URL that contains no OAuth query parameters.
- [x] Render only sanitized success/failure state. Do not embed analytics,
      remote scripts, images, or other third-party resources on the callback.
- [x] Add explicit one-time bootstrap behavior. Normal startup must continue to
      fail if an expected database is missing.
- [x] Add a sanitized live acceptance receipt format containing no secrets.
- [x] Prove the adapter cannot mutate Calendar or access Gmail.
- [x] Run the complete regression suite and all existing acceptance harnesses.
- [x] Publish through a dedicated branch/draft PR and canonical CI.
- [x] Obtain separate approval before marking that PR ready or merging it.

Gate A is complete when reviewed PR #28 is merged onto canonical `main`.

## Gate B — Google Cloud configuration

### Operator preparation

- [ ] Use a dedicated Google Cloud project for Mission Control rather than an
      unrelated production project.
- [ ] Enable the Google Calendar API.
- [ ] Open **Google Auth Platform** and complete Branding, Audience, and Data
      Access.
- [ ] Use a recognizable app name such as `Mission Control OS — Private Pilot`.
- [ ] Use an operator-controlled support/developer-contact email.
- [ ] For a personal Gmail account, select **External** and initially keep the
      publishing status at **Testing**.
- [ ] Add only the configured operator Google account as a test user.
- [ ] If the account is in an operator-controlled Google Workspace organization,
      evaluate **Internal** separately; do not assume a personal Gmail account
      can use Internal.

### Exact requested scopes

- [ ] `openid`
- [ ] `email`
- [ ] `https://www.googleapis.com/auth/calendar.events.owned`
- [ ] `https://www.googleapis.com/auth/calendar.calendars.readonly`
- [ ] Confirm no Gmail, Drive, Contacts, broad `calendar`, ACL, or unrelated
      scope is present.

`calendar.events.owned` technically permits viewing, creating, changing, and
deleting events on calendars the operator owns. It is required by the existing
Tested direct-calendar capability, but it does not grant Mission Control
constitutional permission to mutate an event. Existing proposal approval and
provider read-back requirements remain binding.

### Web Application OAuth client

- [ ] Confirm the Railway public HTTPS domain is stable.
- [ ] Fix one callback path in the reviewed Gate A adapter. Recommended shape:
      `https://<railway-public-domain>/auth/google/callback`.
- [ ] Create an OAuth client of type **Web application**, not Desktop, iOS,
      Android, or browser-only JavaScript.
- [ ] Enter the callback URL as an authorized redirect URI with an exact
      scheme, host, path, port, query, and trailing-slash match.
- [ ] Do not add an authorized JavaScript origin unless later code actually
      performs client-side Google API authorization; Phase B does not.
- [ ] Copy the client ID and one-time-visible client secret directly into an
      approved secure handoff. Do not download or commit `client_secret.json`.
- [ ] If the client secret cannot be transferred safely, stop and rotate it
      rather than pasting it into chat or an issue.

### Testing-status decision checkpoint

Google documents that an External app in **Testing** with Calendar scopes
receives refresh tokens that expire after seven days. That is acceptable for a
short controlled acceptance run, but not for routine unattended operation.

- [ ] Record whether Phase B will use Testing only for initial acceptance.
- [ ] Before Tested promotion, either move to an appropriate production state
      for this personal-use app or explicitly govern the seven-day
      reauthorization limitation and its operational consequences.
- [ ] Do not claim durable authorization merely because the first restart test
      passes inside the seven-day window.

## Gate C — Railway configuration and deployment

### Existing runtime boundary

- [ ] Use the existing single Railway service and existing volume mounted at
      `/data`.
- [ ] Keep exactly one service replica and one runtime writer.
- [ ] Do not create a parallel backend, a second SQLite writer, or a new
      credentials backup path.
- [ ] Confirm the current Stage 5 health and R2 backup boundary is healthy before
      modifying the service.
- [ ] Preserve all existing calendar-state and R2 variables.

Railway mounts volumes only when the container starts, not during build or
pre-deploy. Directory creation and explicit bootstrap must therefore run in an
approved runtime/startup operation, not a Docker build step.

### Approved volume roots

The following roots are distinct, non-nested, outside `/app`, and compatible
with the merged configuration validator:

```text
MISSION_CONTROL_OPERATOR_KNOWLEDGE_ROOT=/data/operator-knowledge
MISSION_CONTROL_CREDENTIAL_STORE_ROOT=/data/security-credentials
MISSION_CONTROL_SECURITY_RUNTIME_ROOT=/data/security-runtime
```

- [ ] Confirm none exists as a symlink.
- [ ] Create only the approved directories; do not alter `/data/state-volume`
      or `/data/backup-staging`.
- [ ] Confirm the credential vault is excluded from the existing R2 calendar
      backup path.

### Railway variable inventory

| Variable | Classification | Checklist treatment |
|---|---|---|
| `MISSION_CONTROL_OPERATOR_KNOWLEDGE_ROOT` | Non-secret path | Service variable using the approved `/data` root |
| `MISSION_CONTROL_CREDENTIAL_STORE_ROOT` | Non-secret path | Service variable using the approved `/data` root |
| `MISSION_CONTROL_SECURITY_RUNTIME_ROOT` | Non-secret path | Service variable using the approved `/data` root |
| `MISSION_CONTROL_OPERATOR_GOOGLE_EMAIL` | Operator identity / PII | Enter directly and seal |
| `GOOGLE_OAUTH_CLIENT_ID` | Identifier, not a password | Service variable; never commit it to a public example containing the real value |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Secret | Enter directly and seal immediately |
| `GOOGLE_OAUTH_REDIRECT_URI` | Non-secret URL | Exact same value registered with Google |
| `MISSION_CONTROL_CREDENTIAL_ENCRYPTION_KEY` | Secret root key | Generate privately, enter directly, and seal immediately |
| `MISSION_CONTROL_CREDENTIAL_KEY_VERSION` | Non-secret metadata | Start with an explicit value such as `gen1-v1` |

Railway sealed variables are write-only in the dashboard/API, cannot be
unsealed, and are not available through `railway run`. Do not use the Raw Editor
for secrets. Run live validation inside the deployed service boundary.

Generate the 32-byte URL-safe base64 encryption key in a private local terminal
only after Gate C approval:

```bash
python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
```

The printed result is a secret. Paste it directly into the Railway variable,
seal it, do not send it through chat, and do not save it in the repository. Loss
of this key requires Google reauthorization; the credential database alone is
not recoverable.

### Bootstrap and deploy

- [ ] Confirm the reviewed Gate A bootstrap command from canonical `main`.
      Do not invent or reuse the synthetic acceptance command.
- [ ] Stage the approved variables without printing their values.
- [ ] Run the explicit one-time security-store bootstrap inside the mounted
      runtime volume.
- [ ] Confirm creation of exactly:
      `/data/security-credentials/provider-credentials.sqlite3` and
      `/data/security-runtime/security-runtime.sqlite3`.
- [ ] Return immediately to normal no-create startup.
- [ ] Deploy the reviewed canonical commit and wait for a healthy service.
- [ ] Verify an ordinary restart/open refuses missing, symlinked, wrong-role,
      corrupt, or incompatible stores rather than replacing them.

## Gate D — controlled live OAuth and first read-back

- [ ] Record the canonical commit, Railway deployment ID, public domain, Google
      client ID fingerprint/last characters, key version, and start time. Do not
      record the client secret or encryption key.
- [ ] Open the approved authorization start endpoint.
- [ ] Confirm the Google consent screen identifies the intended Mission Control
      project and exactly the four approved scopes.
- [ ] Select the exact configured operator account; stop if another account is
      selected or Google reports an unexpected audience/scope.
- [ ] Approve consent once.
- [ ] Confirm the callback returns a sanitized result and a Secure, HttpOnly,
      SameSite=Lax operator session cookie.
- [ ] Confirm the server reports verified provider `google`, expected operator
      email, stable subject match, granted scopes, primary Calendar context, and
      Calendar timezone without returning tokens.
- [ ] Confirm a sanitized credential verification receipt is persisted only
      after the provider read-back passes.
- [ ] Confirm live Calendar mutations remain **0**.

Do not use a successful token exchange as acceptance. The independent identity
and primary-Calendar metadata read-back is mandatory.

## Gate E — restart and post-restart read-back

- [ ] Capture a sanitized pre-restart receipt and confirm both security database
      files exist on the mounted volume.
- [ ] Restart the current Railway deployment without rebuilding it.
- [ ] Wait for Railway and the Mission Control health boundary to return healthy.
- [ ] Do not revisit Google consent and do not re-enter any secret.
- [ ] Authenticate with the persisted Mission Control session if it remains
      valid, or use the approved private verification operation without
      reauthorizing Google.
- [ ] Run persisted-credential read-back again.
- [ ] Confirm the same Google provider, stable subject, normalized operator
      email, primary Calendar context, granted scopes, and key version.
- [ ] Confirm `last_verified_at` advances and the existing refresh token is
      reused server-side.
- [ ] Confirm live Calendar mutations remain **0**.

Railway documents that **restart** reuses the existing deployment image without
a rebuild. Use redeploy only if separately required and approved.

## Leakage and failure inspection

- [ ] Scan the repository and Git history for OAuth client secret, encryption
      key, authorization code, access-token, and refresh-token signatures.
- [ ] Inspect Railway build, deploy, runtime, health, and acceptance logs. No
      secret or authorization code may appear.
- [ ] Inspect callback/result URLs and browser history. The final result URL must
      not retain `code`, `state`, access token, or refresh token parameters.
- [ ] Confirm HTTP responses never include provider tokens or encryption key.
- [ ] Confirm the credential SQLite file contains an AES-256-GCM envelope and no
      refresh-token plaintext.
- [ ] Confirm the runtime SQLite file contains session/state hashes and no
      session-token or PKCE-verifier plaintext.
- [ ] Confirm security audit records contain sanitized action/outcome/context
      only.
- [ ] Confirm Railway shows the three approved secrets as sealed.
- [ ] Confirm R2 contains no credential-vault or security-runtime database.
- [ ] Confirm missing/corrupt/unreadable live state fails loudly and does not
      become a false `connected` result.

If any leakage is found, stop acceptance, revoke the Google grant, rotate the
affected client secret or encryption key, quarantine the security databases,
and do not promote maturity.

## Evidence receipt

The final Phase B receipt may contain only:

- canonical commit and PR;
- Railway deployment/restart identifiers and timestamps;
- Google project/client identifier fingerprint, never the secret;
- configured publishing status and seven-day limitation decision;
- provider name and redacted/pinned operator context;
- granted scope names;
- sanitized primary Calendar ID/context and timezone;
- database paths, schema versions, store roles, and key version;
- pre/post-restart verification times;
- pass/fail results for restart, read-back, leakage, and zero-mutation checks;
- explicit operator acceptance decision.

## Gate F — maturity and successor decision

Do not promote the capability merely because OAuth succeeds.

- [ ] Gate A adapter is merged and canonical CI passes.
- [ ] Google/Railway configuration matches this checklist.
- [ ] First live operator and Calendar read-back passes.
- [ ] Railway restart completes without reauthorization.
- [ ] Post-restart provider read-back passes.
- [ ] Leakage inspection passes.
- [ ] Google Testing-status seven-day limitation is resolved or explicitly
      governed.
- [ ] Complete repository regression and acceptance harnesses remain green.
- [ ] Operator explicitly approves Prototype → Tested promotion.
- [ ] Update Implementation State, Capability Registry, CHANGELOG, and Issue
      #23 with evidence.
- [ ] Close Issue #23 only after explicit acceptance.
- [ ] Begin Issue #24 only after separate activation approval.

## Stop and recovery rules

- Wrong/unverified Google account: reject; do not persist the credential.
- Redirect mismatch or unexpected scope: stop and correct Google/Railway
  configuration; do not bypass the check.
- Missing refresh token: require explicit re-consent; do not claim success.
- Missing/corrupt/wrong-role store: stop normal startup; do not bootstrap over
  it.
- Wrong encryption key/version: stop and recover the correct sealed key or
  reauthorize after controlled vault replacement.
- Suspected client-secret exposure: rotate the Google secret before continuing.
- Suspected refresh-token exposure: revoke the Google grant, quarantine/delete
  only the credential vault under explicit approval, and reauthorize.
- Failed deployment: return to the last known-good canonical image without
  deleting the Railway volume or existing calendar state.

## Official provider references

- [Google OAuth for web server applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google OAuth consent and scope configuration](https://developers.google.com/workspace/guides/configure-oauth-consent)
- [Google OAuth client management](https://support.google.com/cloud/answer/15549257)
- [Google refresh-token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)
- [Google Calendar API scopes](https://developers.google.com/workspace/calendar/api/auth)
- [Railway variables and sealed variables](https://docs.railway.com/variables)
- [Railway secrets guidance](https://docs.railway.com/guides/managing-secrets-on-railway)
- [Railway volumes](https://docs.railway.com/volumes)
- [Railway restart behavior](https://docs.railway.com/cli/restart)
