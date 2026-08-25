# Generation 1 Single-Operator Security Boundary

## Status

Issue #23 Phase A is implemented at **Prototype** maturity using synthetic
identity and credential data only. The software boundary has passed local and
separate-process acceptance. It has not completed Google OAuth, Railway secret,
deployed restart, or live provider read-back acceptance.

Synthetic acceptance must never be reported as deployed or credential
acceptance.

## Purpose

Protect the private Generation 1 Mission Control runtime while preserving the
existing human-approval model. Authentication establishes who may use Mission
Control. Provider authorization establishes what the runtime can technically
access. Neither grants standing permission to create, modify, or delete an
external resource.

This boundary is for exactly one operator. It is not a user-management or
multi-tenant subsystem.

## Storage separation

The application validates four distinct, non-nested roots:

1. Product repository — code and synthetic fixtures only.
2. Operator knowledge — real Mission Control knowledge outside GitHub.
3. Credential store — a dedicated SQLite database containing provider metadata
   and AES-256-GCM ciphertext.
4. Runtime/audit state — a separate SQLite database containing the pinned
   operator identity, one-time OAuth transaction state, hashed sessions, and
   sanitized security audit events.

The credential and runtime databases may use separate directories on the
existing single-runtime Railway volume. They must not be placed inside the
repository or operator-knowledge root. The existing calendar R2 backup path
does not copy the credential vault. Loss of the credential vault or its sealed
encryption key requires explicit Google reauthorization; Mission Control must
not silently substitute an empty or foreign store.

## Operator identity

The first controlled Google authorization must return a Google-signed,
email-verified identity matching the configured operator email. Mission Control
then pins Google's stable `sub` identifier. Every later sign-in, credential
load, and provider read-back must match the pinned provider, `sub`, and email.

An account with the same configured email but a different stable subject cannot
replace the enrolled operator.

No generalized users table, roles, invitations, password reset, or tenancy
model is included.

## Server-side OAuth

The thin Google adapter uses `google-auth-oauthlib` and the confidential Web
Application authorization-code flow. The browser receives only Google's
authorization URL and a one-time state value. Provider tokens remain on the
server.

Each authorization transaction has:

- a cryptographically random state value stored only as a SHA-256 hash
- a PKCE verifier encrypted in the runtime-state database
- a maximum ten-minute lifetime by default
- one-time consumption with replay rejection
- exact HTTPS callback configuration
- offline access and explicit initial consent so Google may return a refresh
  token

Generation 1 requests only `openid`, `email`, owned-calendar event access, and
read-only calendar metadata. Gmail scopes are not requested during Issue #23.

## Credential vault

Refresh tokens are encrypted with PyCA `cryptography` AES-256-GCM before SQLite
persistence. Every encryption uses a new 96-bit nonce and authenticated context
binding the ciphertext to the schema, provider, and pinned operator subject.

The encryption key and its explicit version come only from the sealed runtime
environment. The key, OAuth client secret, and refresh token are excluded from
object representations, audit records, and user-facing results. The vault
rejects malformed envelopes, changed ciphertext, wrong authenticated context,
wrong keys, and unavailable key versions.

Only refresh tokens are persisted. Short-lived Google access tokens are
refreshed in memory when needed.

## Private operator session

After a successful OAuth callback, Mission Control creates an opaque random
session token. SQLite stores only its SHA-256 hash. The future web surface must
deliver the token using a cookie with `Secure`, `HttpOnly`, and `SameSite=Lax`.
Sessions expire after twelve hours by default, can be revoked on logout, and
cannot outlive seven days under the current service guard.

Issue #24 will provide the HTTP routes and user interface that consume this
accepted backend contract. Issue #23 does not build that web application.

## Trusted credential read-back

Before a persisted Google credential is trusted, the runtime must:

1. Open the expected stores without creating replacements.
2. Decrypt and authenticate the refresh token.
3. Confirm stored identity and scopes match the enrolled operator.
4. Refresh Google access server-side.
5. Read back Google OpenID identity.
6. Read back the primary Google Calendar metadata context.
7. Compare provider, stable subject, verified email, and scopes again.
8. Persist a sanitized verification receipt only after every check passes.

No calendar mutation occurs during credential read-back.

## Fail-loud states

The boundary distinguishes and raises explicit errors for:

- incomplete or unsafe configuration
- missing expected credential or runtime database
- foreign schema or store role
- corrupt SQLite state
- missing credentials
- malformed, modified, wrong-key, or unreadable ciphertext
- missing or replayed OAuth state
- expired OAuth transaction or session
- wrong or unverified Google account
- insufficient OAuth scope
- revoked or expired provider authorization
- malformed or failed provider read-back

Normal startup never bootstraps a missing store. Store creation is a separate,
explicit one-time operation.

## Required Railway environment values

Values must be entered directly in Railway. Secret values must be sealed and
must never be pasted into chat or committed to GitHub.

- `MISSION_CONTROL_OPERATOR_KNOWLEDGE_ROOT`
- `MISSION_CONTROL_CREDENTIAL_STORE_ROOT`
- `MISSION_CONTROL_SECURITY_RUNTIME_ROOT`
- `MISSION_CONTROL_OPERATOR_GOOGLE_EMAIL`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`
- `MISSION_CONTROL_CREDENTIAL_ENCRYPTION_KEY`
- `MISSION_CONTROL_CREDENTIAL_KEY_VERSION`

## Phase A evidence

- 19 focused security tests pass.
- The complete repository suite passes 128 tests.
- The separate-process harness proves authorization persistence and read-back
  after a fresh Python process opens the stores.
- Refresh token and session plaintext are absent from their SQLite files.
- Wrong-account and wrong-key cases fail loudly.
- Existing Stage 4, Stage 5, Stage 7, and Knowledge Layer acceptance remain
  green.
- Real operator data: 0.
- Live Google calls: 0.
- External actions: 0.

## Phase B acceptance still required

The governed preparation and execution gates are defined in
[Generation 1 Security Phase B Activation Checklist](GEN1_SECURITY_PHASE_B_ACTIVATION.md).
The current repository does not yet contain the live OAuth callback/bootstrap
adapter required to execute that checklist. Implementing that narrow adapter is
the first separately approved Phase B gate; checklist preparation itself does
not authorize provider or deployment changes.

Prototype does not become Tested until separately authorized live acceptance
completes:

1. Publish and review the implementation branch through canonical CI.
2. Configure the Google consent screen and Web Application OAuth client.
3. Enter and seal Railway values without exposing their contents.
4. Complete controlled operator authorization.
5. Verify the returned Google identity and primary Calendar context.
6. Restart the Railway process.
7. Repeat refresh and provider read-back without reauthorization.
8. Inspect repository, database, logs, and responses for credential leakage.
9. Resolve or explicitly govern Google's seven-day refresh-token limitation if
   the OAuth application remains in external Testing status.

Issue #24 and Issue #25 remain out of scope until Issue #23 receives explicit
acceptance.
