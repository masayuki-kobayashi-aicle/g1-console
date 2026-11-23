# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting: open the repository's **Security**
tab and choose **Report a vulnerability**. If that option is not available, open
a public issue that says only that you have a security report, without details,
and a maintainer will arrange a private channel.

We aim to acknowledge a report within 7 days. This is a small project run in
spare time, so there is no guaranteed fix time.

## Scope and known limits

g1-console can command a physical robot. Treat it as a tool for a trusted,
isolated network, not for the internet.

Known and documented properties (see the "Security model" section of the README):

- Plain HTTP, no TLS.
- The login cookie holds the raw token (`HttpOnly`, `SameSite=Strict`, no `Secure`).
  The token is printed in the startup log and passed once in the `/login` URL.
- `--no-auth` lets anyone on the network operate the robot.
- By default the server listens on `127.0.0.1` only; opening it on another
  interface requires the token.
- The software emergency stop is not a certified safety function. Keep the
  physical remote controller in reach.

Reports about these documented properties are welcome as improvement ideas, but
are not treated as vulnerabilities by themselves. Reports we especially want:

- authentication or Host/Origin check bypass,
- a way to send a command that the allowlists and clamps should refuse,
- path traversal, command injection or request smuggling in the hub or helpers,
- anything that lets a remote page or a second client take over an operator lock.

## Supported versions

Only the latest release (or `main` before the first release) is supported.
