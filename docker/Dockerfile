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
RUN dnf install -y \
        freeradius-postgresql-3.2* && \
    dnf clean all

# Copy custom dictionary into FreeRADIUS dictionary directory
COPY ../raddb/dictionary.misstable /etc/raddb/dictionary.misstable

# Append vendor dictionary include to main dictionary
RUN echo '$INCLUDE dictionary.misstable' >> /etc/raddb/dictionary

EXPOSE 1812/udp 1813/udp

CMD ["radiusd", "-f"]
