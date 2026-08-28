#!/bin/bash

# Script to refresh PostgreSQL collation versions
# This fixes the collation version mismatch warnings

echo "Refreshing collation versions for PostgreSQL databases..."

# Connect to PostgreSQL and refresh collation versions
psql -U postgres -d postgres -c "ALTER DATABASE postgres REFRESH COLLATION VERSION;" 2>/dev/null || echo "Could not refresh postgres database collation"
psql -U postgres -d template_postgis -c "ALTER DATABASE template_postgis REFRESH COLLATION VERSION;" 2>/dev/null || echo "Could not refresh template_postgis database collation"
psql -U postgres -d eurorace -c "ALTER DATABASE eurorace REFRESH COLLATION VERSION;" 2>/dev/null || echo "Could not refresh eurorace database collation (may not exist yet)"

echo "Collation refresh completed."
