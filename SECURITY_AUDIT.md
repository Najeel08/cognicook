# CogniCook Security Audit

Audit date: 2026-06-10  
Scope: Flask application, routes, templates, browser JavaScript, SQLAlchemy models, SQLite handling, dataset import tools, dependencies, environment configuration, and deployment guidance.

## 1. Executive Security Summary

Overall risk before remediation: **Moderate**  
Overall residual risk after remediation: **Low to Moderate**

No critical or high-severity vulnerability was found in the reviewed codebase. The application already had strong baseline controls: parameterized ORM queries, Jinja autoescaping, ownership-scoped favorite and activity queries, POST-only state changes, CSRF validation, session rotation, secure password hashing, request-size limits, authentication throttling, CSP/SRI, security headers, trusted-host support, and generic server error pages.

The most important gaps were production settings that could be weakened or omitted, automatic recipe-data replacement during production startup, authentication enumeration/side-channel behavior, reversible offline guessing of hashed rate-limit identifiers, and limited operational error visibility. These issues were remediated without changing core recipe, account, favorite, or activity workflows.

No evidence of SQL injection, stored/reflected DOM XSS, unsafe deserialization, SSRF, unrestricted file upload, exposed administrative routes, hardcoded production credentials, or broken object-level authorization was found.

## 2. Architecture and Attack Surface

Trust boundaries:

- Browser to Flask over HTTP(S): credentials, session cookie, CSRF token, ingredient searches.
- Flask to SQLite through SQLAlchemy: users, password hashes, favorites, activity, recipes, and throttle records.
- Local operator to CSV import scripts: trusted maintenance path that can replace recipe records.
- Browser to jsDelivr: Bootstrap CSS and JavaScript protected by Subresource Integrity.
- Deployment environment to application configuration: secret key, hosts, storage paths, proxy trust, cookie and HSTS settings.

Public endpoints:

- `GET/POST /` login
- `GET/POST /register`
- `GET/POST /dashboard`
- `GET /recommendations`
- `GET /similar`
- `GET /recipe/<id>`

Authenticated endpoints:

- `GET /favorites`
- `GET /activity`
- `POST /favorite/<id>`
- `POST /favorite/<id>/remove`
- `POST /logout`

There is no JSON API, file-upload endpoint, administrative web interface, JWT flow, refresh token, payment flow, or health-data workflow in the reviewed project.

## 3. Vulnerability Report

### SEC-01: Production security configuration did not fully fail closed

- Severity: **Medium**
- Affected: `config.py`, `app.py`
- Impact: A deployment could accept a weak secret, omit host validation, or explicitly disable secure cookies. This increases session forgery, Host-header abuse, and cookie interception risk.
- Exploit scenario: An operator deploys with `COGNICOOK_ENV=production` but a short secret or no trusted host list; an attacker then targets session integrity or poisoned Host-derived behavior.
- Remediation applied: Production startup now requires an environment-provided secret of at least 32 characters, secure cookies, and explicit non-wildcard trusted hosts.
- Functionality preserved: Development and test defaults remain convenient; only unsafe production startup is rejected.

### SEC-02: Production startup could automatically replace recipe data

- Severity: **Medium**
- Affected: `config.py`
- Impact: A changed, malformed, or incorrectly mounted dataset could alter production recipe data and favorite mappings during application startup.
- Exploit scenario: A compromised deployment artifact modifies the CSV, and startup automatically imports it into the live database.
- Remediation applied: `AUTO_BOOTSTRAP_DATA` now defaults off in production and remains on in development.
- Functionality preserved: Operators can explicitly enable bootstrap or use the existing import script.

### SEC-03: Login processing exposed a user-existence timing difference

- Severity: **Low**
- Affected: `routes.py`
- Impact: Repeated measurements could help distinguish registered from unregistered email addresses because password hashing was skipped for missing users.
- Exploit scenario: An attacker submits many login attempts and statistically compares response times.
- Remediation applied: Missing-user login attempts now verify against a valid dummy scrypt hash.
- Functionality preserved: Login messages and successful authentication behavior are unchanged.

### SEC-04: Registration disclosed duplicate accounts directly

- Severity: **Low**
- Affected: `routes.py`
- Impact: Attackers could confirm whether an email was registered.
- Exploit scenario: Submit a valid registration for a target email and inspect the duplicate-account message.
- Remediation applied: Duplicate and uniqueness-race responses now use the same less-specific registration failure guidance.
- Functionality preserved: Legitimate users still receive an actionable prompt to use another address or sign in.

### SEC-05: Account throttle identifiers used unkeyed email hashes

- Severity: **Low**
- Affected: `app.py`
- Impact: If the throttle table leaked, common email addresses could be recovered through offline dictionary guessing.
- Exploit scenario: An attacker obtains the SQLite file and compares SHA-256 values for candidate emails.
- Remediation applied: Account identifiers now use HMAC-SHA-256 keyed by the application secret.
- Functionality preserved: Existing temporary throttle records naturally expire; rate-limit behavior is unchanged.

### SEC-06: `TRACE` was treated as CSRF-safe

- Severity: **Low**
- Affected: `app.py`
- Impact: Future TRACE-capable routing or middleware could bypass CSRF checks for a method that should not be exposed by the application.
- Exploit scenario: A later component enables TRACE and attaches state-changing behavior.
- Remediation applied: Only `GET`, `HEAD`, and `OPTIONS` are exempt.
- Functionality preserved: Current routes do not require TRACE.

### SEC-07: Database and server error handlers lacked explicit operational events

- Severity: **Low**
- Affected: `app.py`
- Impact: Production failures could be harder to detect and investigate.
- Exploit scenario: Repeated database errors affect availability without a consistent event for log aggregation.
- Remediation applied: Sanitized endpoint, method, path, and exception-type events are logged without SQL text or secrets.
- Functionality preserved: Users continue receiving generic error pages.

## 4. Existing Controls Confirmed

- Access control: authenticated routes use `login_required`; favorites and activity are filtered by `current_user.id`.
- Injection: ORM filters and bound SQLAlchemy parameters are used; no user-controlled SQL construction was found.
- XSS: Jinja autoescaping is retained; no `safe` filter, `innerHTML`, `eval`, or inline event handlers were found.
- CSRF: all unsafe methods require a per-session token; cross-site Fetch Metadata requests are rejected.
- Authentication: Werkzeug scrypt password hashing, generic login errors, strong Flask-Login session protection, session clearing and CSRF rotation after login.
- Sessions: HttpOnly, SameSite=Lax, optional/production Secure cookies, eight-hour lifetime, Host-prefixed production cookie name.
- Request hardening: request-size cap, endpoint query schemas, duplicate parameter rejection, control/traversal checks, enumerated filters.
- Response hardening: CSP, frame denial, nosniff, HSTS support, referrer policy, permissions policy, cross-origin isolation policies, and no-store for dynamic responses.
- Supply chain: exact direct dependency versions and SRI-pinned Bootstrap assets.
- Secrets: `.env`, databases, local secret files, logs, and virtual environments are ignored by Git; history and tracked-file scans found no exposed credential.

## 5. Threat Model

### STRIDE

| Threat | Relevant control | Residual gap |
|---|---|---|
| Spoofing | scrypt passwords, signed sessions, login throttling | No MFA, email verification, or recovery flow |
| Tampering | CSRF, bound queries, SRI, validated imports | Local CSV/import operator remains highly privileged |
| Repudiation | security and error events | No centralized immutable audit store |
| Information disclosure | autoescaping, generic errors, HttpOnly cookies | SQLite and backups are not application-encrypted |
| Denial of service | body limits, auth throttling, pagination | Public recommendation endpoints lack distributed rate limits |
| Elevation of privilege | ownership filters, no admin route | No formal RBAC model if privileged roles are added later |

### MITRE ATT&CK Mapping

- T1110 Brute Force: mitigated by IP and account-scoped authentication throttling.
- T1078 Valid Accounts: reduced by password policy and session protection; MFA remains recommended for higher-risk deployments.
- T1190 Exploit Public-Facing Application: reduced by validation, CSRF, CSP, parameterized queries, and production fail-closed checks.
- T1189 Drive-by Compromise: reduced by CSP and SRI for third-party browser assets.
- T1552 Unsecured Credentials: reduced by environment secrets and Git exclusions.
- T1005 Data from Local System / T1530 Cloud Storage Data: database and backup access remain deployment responsibilities.
- T1565 Data Manipulation: automatic production dataset bootstrap is now disabled by default.

### Cyber Kill Chain

- Reconnaissance: registration and timing enumeration were reduced.
- Weaponization/Delivery: no upload or messaging surface exists.
- Exploitation: primary web injection classes are strongly constrained.
- Installation/Persistence: no server-side plugin or code-upload path exists.
- Command and Control: CSP limits browser connections to the same origin.
- Actions on Objectives: ownership checks constrain favorite/activity access; database theft remains a host-level risk.

## 6. Framework Alignment

This is an alignment review, not a certification or legal determination.

| Framework | Aligned areas | Main gaps and practical recommendations |
|---|---|---|
| NIST CSF 2.0 | Protect controls, validation, recovery-aware DB handling | Add Govern policies, asset inventory, alerting, incident response, and recovery tests |
| CIS Controls | Secure config, account controls, vulnerability scan, data protection basics | Add automated inventory, centralized logs, backups, CI scanning, and access reviews |
| ISO/IEC 27001 | Technical controls support access, secure coding, and configuration | Requires ISMS scope, risk register, owners, evidence, audits, supplier and incident processes |
| ISO/IEC 27002 | Authentication, logging, secure development, configuration | Formalize retention, backup, key management, monitoring, and change management |
| NIST SP 800-53 | Partial AC, IA, SC, SI, AU controls | Add control ownership, AU retention/review, CP/IR plans, CM baselines, and assessment evidence |
| SOC 2 | Security-related logical access and change controls are partially present | Define trust-service scope, evidence collection, monitoring, vendor management, availability targets |
| COBIT | Technical practices support DSS05 and BAI03 | Add governance objectives, accountability, metrics, risk ownership, and assurance |
| HITRUST CSF | Useful baseline access and application controls | Not suitable for regulated health data without stronger governance, encryption, logging, BCP, and vendor controls |
| PCI DSS v4.0 | Secure coding and access-control concepts align | No cardholder flow exists; do not introduce payment data without segmentation, ASV scans, logging, and PCI-scoped providers |
| HIPAA Security Rule | Basic access and integrity safeguards | No PHI use is established; PHI would require risk analysis, audit controls, BAAs, contingency plans, and stronger data governance |
| GDPR security provisions | Data minimization is modest; passwords are hashed | Add privacy notice, lawful basis, retention/deletion, export/erasure handling, processor records, and breach procedures |
| DORA | Secure development contributes to ICT risk reduction | Financial-entity use requires ICT governance, incident reporting, resilience testing, registers, and third-party oversight |
| CMMC 2.0 | Some access, identification, and system-integrity practices | Do not process CUI without scoped controls, evidence, logging, configuration management, and assessment |
| FISMA | Some NIST-aligned technical safeguards | Federal deployment requires categorization, selected control baseline, SSP, assessment, authorization, and continuous monitoring |

## 7. Dependency and Configuration Report

Direct dependencies are pinned in `requirements.txt`. On 2026-06-10:

- `pip check`: no broken requirements.
- `pip-audit -r requirements.txt`: no known vulnerabilities.
- Bandit recursive scan: no reportable findings.
- Git tracked-file and history scan: no exposed secret was identified.

Residual supply-chain gaps:

- Dependencies do not include package hashes.
- No lockfile/SBOM generation or CI vulnerability gate is committed.
- Bootstrap is loaded from jsDelivr. SRI protects the exact files, but availability and CSP trust still depend on that CDN.
- Transitive dependency versions are not captured by the direct requirements file.

Recommended next controls:

- Generate a reproducible lock with hashes for the deployment Python version.
- Produce a CycloneDX SBOM in CI.
- Run `pip-audit`, Bandit, tests, and secret scanning on every change.
- Consider self-hosting Bootstrap when offline operation or third-party minimization is required.

Production environment minimum:

```text
COGNICOOK_ENV=production
SECRET_KEY=<at least 32 random characters from a secret manager>
COGNICOOK_TRUSTED_HOSTS=app.example.com
SESSION_COOKIE_SECURE=1
SECURITY_HSTS_ENABLED=1
AUTO_BOOTSTRAP_DATA=0
```

Terminate TLS at a maintained reverse proxy or platform, preserve the original HTTPS scheme, restrict database-file permissions, and back up the database to encrypted storage.

## 8. Remaining Risks

- No MFA, email verification, password reset, session inventory, or forced logout after credential changes.
- Account-level throttling can be abused for temporary denial of service and is database-local rather than distributed.
- Public search/recommendation routes have no general distributed rate limit or resource quota.
- SQLite is suitable for this project scale but lacks built-in multi-node operation, granular database roles, and application-level encryption.
- Search activity has no documented retention period, user deletion/export workflow, or privacy notice.
- Logs are local and not guaranteed immutable, centralized, retained, alerted, or scrubbed by a deployment platform.
- No tested disaster-recovery objective, encrypted backup procedure, infrastructure-as-code, container policy, WAF, or TLS configuration is included.
- Dataset maintenance scripts are privileged local operations and need OS-level access control and change review.
- No formal secure-development policy, incident-response plan, data classification, vendor review, or compliance evidence process exists.

These are primarily operational or architectural controls. They should be added when the deployment risk, data sensitivity, user count, or regulatory scope justifies them.

## 9. Final Stability Check

Validation performed:

- Full unit/integration suite.
- Dependency consistency check.
- Dependency vulnerability audit.
- Bandit static scan.
- Python import/compile coverage through tests and direct module execution.
- Git diff and secret scans.

Manual deployment testing still recommended:

- HTTPS reverse-proxy behavior and secure cookie delivery.
- Trusted-host values for every real hostname.
- Backup, restore, and filesystem permission tests.
- Multi-process rate-limit behavior under load.
- Central log ingestion and alert delivery.
- Browser CSP behavior if CDN or asset hosting changes.

The applied changes preserve the existing account, login, recipe search, recommendation, favorite, activity, and dataset maintenance features.

## 10. Primary Reference Register

Official sources checked for this alignment review:

- NIST CSF 2.0: https://www.nist.gov/cyberframework
- NIST SP 800-53 Rev. 5 and Release 5.2.0: https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final
- CIS Critical Security Controls v8: https://www.cisecurity.org/controls/v8
- ISO/IEC 27001: https://www.iso.org/standard/27001
- ISO/IEC 27002: https://www.iso.org/standard/75652.html
- AICPA SOC services: https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services
- ISACA COBIT: https://www.isaca.org/resources/cobit
- HITRUST CSF: https://hitrustalliance.net/hitrust-framework
- PCI DSS: https://www.pcisecuritystandards.org/standards/pci-dss/
- HHS HIPAA Security Rule: https://www.hhs.gov/hipaa/for-professionals/security/index.html
- GDPR: https://eur-lex.europa.eu/eli/reg/2016/679/oj
- DORA: https://eur-lex.europa.eu/eli/reg/2022/2554/oj
- DoD CMMC: https://dodcio.defense.gov/CMMC/About/
- OWASP Top 10: https://owasp.org/www-project-top-ten/
- MITRE ATT&CK: https://attack.mitre.org/
- Microsoft STRIDE threat definitions: https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats
