# Security

The application executes synthetic workloads only, inside temporary local DuckDB databases. It does not accept production warehouse profiles, external credentials or arbitrary SQL supplied in replay plans. CI must stay on GitHub-hosted ephemeral runners with read-only repository permissions.

Never run experiments against real customer pipelines or production tenants without separate authorization and a dedicated containment design. The project does not include such a production mode.

For a vulnerability involving secrets, command execution or bypass of isolation, avoid publishing exploit details in a public issue. Contact repository maintainers privately or use GitHub's private vulnerability reporting feature if available.
