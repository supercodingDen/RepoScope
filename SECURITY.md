# Security policy

RepoScope is a pre-release, single-host demonstration. There is no supported hosted version and no public security-update promise yet. The owner reviews reports against the current main branch and any future explicitly supported release tags. See the [T11 security review](docs/t11-security.md) for verified controls and known limitations.

Do not publish exploit details, credentials, private code, or a live target in an issue. While this repository is private, collaborators should contact the owner through an existing private GitHub channel. Once the repository becomes public, the owner should promptly enable GitHub private vulnerability reporting, which is available to public repositories, or publish another private security contact here. Until a private channel is available, open an issue asking only for a secure contact method, without vulnerability details. Private vulnerability reporting is a separate repository setting from this file.

Include the affected commit, a minimal safe reproduction, impact, and any suggested fix in a private report. Do not test against systems or repositories you do not control. Maintainers will triage the report, coordinate a fix and disclosure, and update this policy with supported versions at release time. No response-time SLA is claimed before the reporting channel and release process are configured.

The default local API is bound to loopback and uses mock providers. There is no internet-facing deployment. Source scans and container controls reduce risk but do not prove the absence of vulnerabilities; unresolved image advisories remain recorded in [project status](docs/project-status.md). Do not expose the development Compose stack publicly.
