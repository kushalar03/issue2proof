# Security model

The host reads ZIPs as data and never executes uploaded or generated code. Context
selection, hidden/key-file exclusions and explicit external-work authorization
precede model/sandbox calls. Embedded credentials in ordinary source still require
human review. Authentication guards source/evidence endpoints.

Dependency preparation contains no repository code or secrets and installs only
published binary wheels from PyPI into a separate target. Resulting resolved
versions and an immutable image are retained. Local project build hooks execute
only in a network-disabled sandbox, as uid/gid 65534 with no-new-privileges and
process limits. They run on a writable copy, while controller inputs remain owned
by root. Tests import the installed package and preserve text resources/metadata.

The child has bounded memory, CPU time, process count, files and wall time. The
API bounds writable layer and whole-operation duration. Guest networking is
explicitly disabled for source builds and tests. Verification operations are
disposable. Only the registered operation belonging to a job is cancelled.

A root controller protects inputs and output collection; hashes and metadata are
checked on the host. Arbitrary Python can still interfere with pytest and produce
misleading JUnit within its own process. Test counts, assertion-failure gates and
skip limits strengthen ordinary evidence but do not create an adversarial proof.
Independent tests require a suitable human-authored oracle.

Public mode requires a strong application token. Sessions are signed, expire in
12 hours and use Secure/HttpOnly/SameSite cookies. CSRF-style cross-origin writes
are rejected. Bearer authentication supports API clients. This is a private
single-credential instance, not a multi-tenant authorization system.

The data lifecycle covers local SQLite reports/jobs, not provider storage or
operator backups. Provider images/blobs follow account retention. Dependency
images contain dependencies only; repository source is confined to disposable
operations. Job records preserve reservation usage even when external work fails.
Dollar reservations are not authoritative provider billing caps.

Production operators own TLS/domain configuration, backups, key rotation,
provider billing limits and access-token distribution. No sandbox escape audit
or universal code-correctness certification is claimed.
