# Security and deployment notes

Audit date: 2026-10-12. Findings are recorded without credential values.

Hardcoded Django keys appear in current and historical settings, including older branches. Rotate deployed keys. Documentation token examples were replaced with placeholders; their activity was not tested. Re-check user/location authorization with your event frontend before deploying.

## Scope and limits

Current source was checked with Gitleaks and a manual configuration review. Where the Git mirror was fully available, Gitleaks scanned all fetched refs and an additional search checked hardcoded Django/password patterns. This is not an assurance that no secret or vulnerability exists. Generic password strings and well-known documentation placeholders need manual classification; Gitleaks alone did not identify every application password.

The new CI scan checks the current source. Historical findings are not silently erased or reclassified as safe. No exposed credential was used to contact its provider, and no runtime secret was revoked or rotated by this change. History rewriting was not performed.

If a committed credential was used in a real deployment, revoke/rotate it at the provider or hosting environment first. Deleting a line or file does not remove earlier commits, forks, caches or deployed copies. See [GitHub's removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

Keep `.env`, private keys, signing credentials, local databases and user uploads out of Git. `.env.example` may contain names and placeholders only. Re-run dependency audits after resolving/installing the target environment and before deployment.

Report an actual credential leak privately to the repository owner; never put credential values in a public issue or pull request.
