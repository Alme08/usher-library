# Security Architecture

## 1. Purpose

This document defines the security boundaries, invariants, and required controls for Usher Library.

Detailed implementation procedures belong to feature specs, ADRs, and infrastructure documentation.

---

## 2. Security Principles

1. The browser is untrusted.
2. FastAPI is the application security boundary.
3. Authentication and authorization are separate concerns.
4. Authorization is always enforced server-side.
5. User-generated content is untrusted.
6. Secrets never enter source control.
7. Security controls fail closed.
8. Public identifiers never provide authorization.
9. Critical security invariants are enforced at the database level where practical.
10. New security-sensitive integrations require architectural review.

---

## 3. Trust Boundaries

```text id="8uk3by"
Internet
   ↓
Browser
   ↓
Caddy
   ↓
React / FastAPI
   ↓
PostgreSQL / Redis / Keycloak
```

All data crossing these boundaries is untrusted unless explicitly validated.

---

## 4. Threat Model

The system must account for:

- anonymous attackers
- malicious authenticated users
- compromised accounts
- abusive automated clients
- malicious or compromised administrators
- vulnerable dependencies
- compromised infrastructure credentials

Primary attack goals:

```text id="c3a4ex"
account takeover
privilege escalation
unauthorized data modification
XSS
CSRF
injection
spam/abuse
secret exposure
service exhaustion
```

---

## 5. Authentication

Authentication is delegated to Keycloak using OpenID Connect.

Required:

```text id="d8d6oz"
Authorization Code
PKCE
state validation
nonce validation
TLS
```

Passwords are never stored by Usher Library.

Detailed authentication behavior:

`docs/architecture/authentication.md`

---

## 6. Authorization

Initial roles:

```text id="0y6q7f"
READER
ADMIN
```

Anonymous users:

- read public content
- view public annotations/comments

Readers additionally:

- create annotations
- create comments/replies
- modify their own content
- modify their own profile

Admins additionally:

- moderate content
- manage users
- perform administrative actions

Authorization is checked for every protected operation.

---

## 7. Object-Level Authorization

For every protected resource:

```text id="d1vco8"
authenticate user
        ↓
resolve resource
        ↓
verify ownership or admin permission
        ↓
perform operation
```

Knowing a UUID is never sufficient.

Users cannot modify another user's:

- annotations
- comments
- profile
- administrative state

---

## 8. Privilege Escalation

Users cannot assign or modify their own role.

The backend ignores role information supplied by clients.

Role changes are administrative actions and must be audited.

---

## 9. Sessions

The application uses server-side sessions.

Browser authentication state is represented by an opaque session cookie.

Cookie requirements:

```text id="7j06sm"
Secure
HttpOnly
SameSite=Lax
```

Session identifiers must be:

- random
- opaque
- non-sequential
- unrelated to user IDs

Sessions require bounded lifetime and explicit revocation.

---

## 10. Token Handling

Long-lived authentication tokens must not be stored in:

```text id="j4pgl4"
localStorage
sessionStorage
React state
DOM
```

Tokens must never be logged or returned through normal API responses.

---

## 11. CSRF

Because authentication uses cookies, state-changing requests require CSRF protection.

Baseline controls:

```text id="zfl1iw"
SameSite cookies
Origin validation
CSRF token where required
```

Unsafe methods must not modify state without passing the configured CSRF policy.

---

## 12. CORS

The preferred deployment is same-origin:

```text id="l5q2i7"
https://example.com/
https://example.com/api/*
```

Broad CORS is prohibited.

If cross-origin access is required:

- origins must be explicit
- credentials require explicit origins
- wildcard origins are forbidden with credentials

---

## 13. Input Validation

All external input is untrusted.

Validate:

- type
- length
- allowed values
- ranges
- relationships
- request size
- ownership

Validation occurs at API and domain boundaries.

---

## 14. User-Generated Content

MVP comments and annotations are plain text.

Arbitrary HTML is not allowed.

Avoid rendering user content through unsafe HTML injection mechanisms.

If rich text is introduced later, it requires a dedicated sanitization design and security review.

---

## 15. Annotation Security

The backend validates:

```text id="s7twgr"
paragraph
book version
start offset
end offset
selected text
```

The client cannot define arbitrary annotation locations merely by submitting a fabricated text snapshot.

Annotation ranges must be valid against canonical paragraph content.

---

## 16. Injection Protection

Database queries must use:

- SQLAlchemy expressions
- parameterized SQL

Never concatenate user input into SQL.

The initial application must not expose arbitrary server-side URL fetching.

Any future SSRF-capable feature requires explicit security design.

---

## 17. HTTP Security

Production must use HTTPS and appropriate security headers, including:

```text id="ac9o9j"
Strict-Transport-Security
Content-Security-Policy
X-Content-Type-Options
Referrer-Policy
Permissions-Policy
```

The CSP should be restrictive and allow only required resources.

---

## 18. Rate Limiting

Rate limiting is required for abuse-prone operations, especially:

```text id="rp8j3v"
login-related endpoints
annotation creation
comment creation
profile mutations
administrative actions
```

Limits may consider:

- IP
- authenticated user
- endpoint
- time window

Initial values should be configurable rather than hard-coded into business logic.

---

## 19. Spam / Abuse

Possible controls:

- rate limiting
- duplicate detection
- moderation
- account suspension
- progressive restrictions

CAPTCHA should only be introduced if actual abuse justifies it.

---

## 20. Database Security

PostgreSQL must remain private.

Only the backend should access it.

Database credentials follow least privilege.

Critical ownership and uniqueness rules should be enforced by database constraints.

---

## 21. Redis Security

Redis must remain private.

Redis is not a source of truth.

It may contain:

- sessions
- cache
- rate-limit state
- ephemeral pub/sub data

Loss of Redis must never cause permanent domain-data loss.

---

## 22. Secrets

Never commit:

- database credentials
- Keycloak secrets
- session secrets
- Redis credentials
- deployment credentials
- TLS private keys

Use environment variables or a secret manager.

`.env.example` may contain placeholders only.

---

## 23. Data Privacy

Store only necessary personal data.

Public profile data should be limited to information intentionally exposed by the product.

Never expose:

- authentication identifiers
- session IDs
- tokens
- private identity metadata
- administrative information

through public APIs.

---

## 24. API Responses

API endpoints use explicit response schemas.

Do not serialize database/ORM models directly.

Responses must expose only the data required by the endpoint.

---

## 25. Error Handling

Production responses must not reveal:

- stack traces
- SQL
- filesystem paths
- secrets
- internal service details

Errors should include a request/correlation ID where useful.

Internal diagnostics belong in protected logs.

---

## 26. Logging and Auditing

Structured logs should include:

```text id="h4m5mu"
timestamp
request_id
route
method
status
duration
user_id where available
error category
```

Never log:

- passwords
- access tokens
- refresh tokens
- session cookies
- secrets
- full authentication headers

Security-sensitive actions should create audit events.

Examples:

```text id="j1j2u8"
login_failure
login_success
session_revoked
user.suspended
user.role_changed
annotation.deleted
comment.hidden
```

Audit events are append-only.

---

## 27. Admin Security

Administrators require stronger protection than normal readers.

Recommended:

- MFA through Keycloak
- minimal admin accounts
- explicit authorization checks
- session revocation
- audit logging

Every administrative endpoint requires explicit admin authorization.

---

## 28. Container Security

Production containers should:

- use minimal images
- run as non-root where practical
- avoid privileged mode
- expose only required ports
- avoid unnecessary capabilities
- never expose the Docker socket

---

## 29. Dependency Security

Production dependencies should be pinned/locked.

CI should scan:

```text id="xjkt4j"
Python dependencies
Node dependencies
Docker images
CI/CD actions
```

Recommended tooling:

```text id="f5kll0"
Dependabot
pip-audit
npm audit
Trivy
```

Critical vulnerabilities should block release according to the project's severity policy.

---

## 30. Book Integrity

Published book content is immutable.

The approved source is Project Gutenberg.

Book versions should have content hashes.

The application must not expose public endpoints that modify published book text.

---

## 31. Security Testing

Security tests are required for:

### Authentication

- invalid state
- invalid nonce
- invalid PKCE
- expired session
- revoked session

### Authorization

- anonymous protected request
- reader modifying another user's resource
- reader attempting admin action
- self-assigned admin role

### Input

- invalid annotation range
- oversized input
- malicious text payload
- invalid relationships

### Security controls

- CSRF
- rate limiting
- public/private response boundaries

---

## 32. CI Security Gate

Recommended pipeline:

```text id="8jcncr"
lint
 ↓
typecheck
 ↓
tests
 ↓
security tests
 ↓
dependency scan
 ↓
container scan
 ↓
build
```

Critical security failures block deployment.

---

## 33. Security Invariants

1. Browser is never an authorization boundary.
2. Protected mutations require authentication and authorization.
3. Users may modify only their own content unless authorized as admins.
4. Users cannot change their own role.
5. Passwords are never stored by the application.
6. Tokens are never stored in browser localStorage.
7. Sessions use secure opaque identifiers.
8. User-generated content is untrusted.
9. Arbitrary HTML is not allowed in the MVP.
10. SQL queries are parameterized.
11. PostgreSQL and Redis are private.
12. Secrets never enter source control.
13. Published book content is immutable.
14. Annotation ranges are validated against canonical text.
15. Administrative actions are auditable.
16. Public caches must never expose private responses.
17. Security failures fail closed.
18. New security-sensitive functionality requires security review.

---

## 34. Security Review Checklist

Before approving a feature:

```text id="4dd33x"
[ ] Authentication requirement defined
[ ] Authorization requirement defined
[ ] Ownership checked server-side
[ ] Input validated
[ ] Output does not expose private data
[ ] XSS considered
[ ] CSRF considered
[ ] Abuse/rate limiting considered
[ ] Database constraints considered
[ ] Secrets considered
[ ] Logging/auditing considered
[ ] Negative security tests added
[ ] Dependencies reviewed
```

---

## 35. Related Documents

```text id="pf5d0d"
overview.md
system.md
database.md
authentication.md
infrastructure.md
decisions/ADR-*.md
specs/*
```

Agents should load only the security sections relevant to the current task.