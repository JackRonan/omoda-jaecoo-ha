# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue, PR, or
discussion for anything security-sensitive.

- Preferred: **GitHub → Security → "Report a vulnerability"** (Private Vulnerability
  Reporting is enabled on this repository).
- Include: affected version, a description of the issue, reproduction steps or a
  proof-of-concept, impact, and (if you have one) a proposed fix. Please do **not**
  include real credentials, tokens, VINs, or GPS coordinates in the report — redact them.

You'll get an acknowledgement as soon as possible. Coordinated disclosure is welcome:
we'll agree a timeline for a fix and a public advisory, and credit you unless you'd
rather stay anonymous.

## Supported versions

This is a community project. Security fixes target the **latest release** only; please
update via HACS before reporting.

## Scope & handling of sensitive data

This integration talks to the OMODA/Jaecoo cloud on your behalf, so it necessarily
handles sensitive data. What to know:

- **Credentials and tokens** (account email, 4-digit command PIN, access/refresh tokens,
  `tUserId`) are stored **only in your own Home Assistant** (the config entry and files
  under your HA config dir). Nothing is sent to any third party or stored in this repo.
- **Diagnostics** downloaded from Home Assistant are anonymised (email, PIN, VIN,
  `tUserId` and GPS redacted; tokens/certificates shown only as present yes/no). They are
  safe to attach to a bug report — but please skim them before sharing.
- **Logs** never contain the PIN, OTP, or tokens. The most sensitive value that can appear
  is the VIN at debug level.
- The bundled mutual-TLS certificates and app signing constants are extracted from the
  public OMODA/Jaecoo app and are the same for every user; they are not per-account secrets.

## Out of scope

- Vulnerabilities in Home Assistant core or in the OMODA/Jaecoo cloud itself.
- Issues that require an already-compromised Home Assistant host or physical access to it.
