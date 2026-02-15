# Dockerfile — FreeRADIUS with PostgreSQL module for iron-claw
#
# Extends the freeradius-lab runtime image, adding the PostgreSQL SQL module
# needed for rlm_sql_postgresql -> Supabase backend.
#
# Usage:
#   docker compose up -d    # Start FreeRADIUS with config overlay
#   docker compose down     # Stop

FROM ghcr.io/silverbeer/freeradius-lab:latest

# Install PostgreSQL SQL module
# The base image has FreeRADIUS 3.2.8 (custom RPM), but AL2023 repo only has
# freeradius-postgresql-3.2.5 which has a hard dep on freeradius=3.2.5.
# Use --nodeps since rlm_sql_postgresql.so is ABI-compatible within 3.2.x.
RUN dnf install -y 'dnf-command(download)' postgresql-libs && \
    dnf download freeradius-postgresql --downloaddir=/tmp && \
    rpm -ivh --nodeps /tmp/freeradius-postgresql-*.rpm && \
    rm -f /tmp/freeradius-postgresql-*.rpm && \
    dnf clean all

# Copy custom dictionary into FreeRADIUS dictionary directory
COPY raddb/dictionary.misstable /etc/raddb/dictionary.misstable

# Append vendor dictionary include to main dictionary
RUN echo '$INCLUDE dictionary.misstable' >> /etc/raddb/dictionary

# Enable sql and sqlcounter modules (symlink mods-available -> mods-enabled)
RUN ln -sf /etc/raddb/mods-available/sql /etc/raddb/mods-enabled/sql && \
    ln -sf /etc/raddb/mods-available/sqlcounter /etc/raddb/mods-enabled/sqlcounter

EXPOSE 1812/udp 1813/udp

CMD ["radiusd", "-f"]
