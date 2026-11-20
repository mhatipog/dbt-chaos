# Experimental credential-free test runner for a reviewed external dbt project.
# Dependencies are installed at IMAGE BUILD time (with networking), not runtime.
# The project under test is only mounted at runtime, read-only.
FROM python:3.13-slim
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    DO_NOT_TRACK=1 \
    HOME=/tmp/chaos-home

WORKDIR /opt/dbt-chaos
COPY pyproject.toml README.md /opt/dbt-chaos/
COPY dbt_chaos /opt/dbt-chaos/dbt_chaos
RUN python -m pip install --no-cache-dir \
        "dbt-core==1.12.5" "dbt-duckdb==1.11.0" "duckdb==1.5.5" \
    && python -m pip install --no-cache-dir --no-deps /opt/dbt-chaos \
    && python -c "import duckdb, dbt_chaos.external_dbt; print(duckdb.__version__)"
# Runtime is non-root; host passes --network none, read-only root FS,
# zero capabilities, no-new-privileges, limited pids/memory and tmpfs.
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["dbt-chaos"]
