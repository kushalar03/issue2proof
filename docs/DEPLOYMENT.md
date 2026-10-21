# Deploy a private instance

1. Provision your chosen Docker-capable Linux server. Point a domain's A/AAAA
   records at it, allow ports 80/443, and arrange backups of the evidence volume.
2. Copy the reviewed source and run `python -m issue2proof.configure` in an
   installed development environment, or generate a strong random token with your
   secret manager. Set DOMAIN, application token and Nebius configuration in the
   private `.env`. Do not commit it. It is excluded from Docker build context.
3. Set provider billing limits. Application dollar reservations are estimates;
   request counts and operation deadlines provide the application hard bounds.
4. Run `docker compose up --build -d`. Caddy provisions HTTPS for the configured
   domain. Public mode requires a strong token; the API container has no published
   port. Login cookies are Secure and therefore require HTTPS.
5. Check `/api/health`, sign in, run a reviewed example, inspect stage events, test
   cancellation and download evidence. Rotate the application token if exposed.
6. Back up `/data/runs.sqlite3` with SQLite's online backup mechanism, not an
   inconsistent copy of a live WAL database. Protect backups as source-code data.

The tested image uses uid 10001, a read-only root, `/tmp` tmpfs, dropped Linux
capabilities and no-new-privileges. Its persistent data directory is a volume.
Use the supplied proxy topology: the application trusts proxy headers from its
internal network. Do not directly publish it with untrusted forwarding headers.

Managed cloud builds may require the session CA as a BuildKit secret:

```
docker build --secret id=proxy_ca,src=/path/to/combined-ca-bundle -t issue2proof .
```

That CA is not baked into the image. A managed proxy runtime may additionally
require a read-only CA mount and SSL_CERT_FILE. Keep TLS verification enabled and
preserve the platform's proxy configuration. Ordinary production HTTPS deployments
use their standard CA roots.

Operational behavior: one embedded worker per API process; SQLite atomically
claims distinct jobs. A killed worker's lease expires in 120 seconds. Explicit
resume preserves completed evidence and reservations. It does not silently retry
paid work. A source response lost before persistence is an acknowledged uncertainty.
A persistent volume is required; this is not a stateless serverless deployment.

No server/domain or hosting account was configured during this task. The container
was built and tested locally; actual public HTTPS issuance and deployment need
that operator-supplied destination. No public URL is invented or claimed.
