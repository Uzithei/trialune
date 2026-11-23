# Security policy

## Reporting a vulnerability

Use **Security → Report a vulnerability** on the project's repository if private reporting
is enabled. Include affected versions, a minimal synthetic reproducer, expected versus actual
behavior and the impact. Remove credentials, customer data and unrelated local files.

If no private reporting channel is available, open an issue asking the maintainers to establish
one. Do not include exploit details or sensitive evidence in that public request. This project
does not publish a security contact address or promise a response-time SLA.

Maintainers should acknowledge reports, agree on a private reproduction, prepare and test a
fix, and coordinate disclosure with the reporter. Publish affected/fixed versions and relevant
mitigations after the issue can be disclosed safely. No automated message or upload is required.

## Supported versions

The current `0.2.x` development line receives best-effort fixes. Earlier versions are not
maintained. Before a published release, check the changelog and use the latest reviewed commit.

## Trust model

- Agent files are trusted executable code running under the invoking OS user. Worker process
  separation and deadlines are not a sandbox for untrusted code.
- Default environment filtering does not stop an agent reading local credential files or
  using the network. Use independently configured OS/container isolation for hostile code.
- Tool observations cover calls through the provided context. External actions are not
  automatically observed or reversed.
- Evidence can contain sensitive prompts, outputs and logs. Redaction, access control and
  retention are the integrator's responsibility; the runner does not upload artifacts.
- Checksums and replay establish consistency, not authenticity. Whole-bundle replacement
  is outside that guarantee.

Issues that bypass declared input validation, falsify required outcomes, break evidence
verification or expose data contrary to documented behavior are relevant security reports.
Read [operational limits](docs/agent-integration.md#operational-limits) before deployment.
