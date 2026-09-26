# Parity sandbox – debian:bookworm-slim + GnuCOBOL 3 + OpenJDK 17 + Python 3
# Build: docker build -t parity .

FROM debian:bookworm-slim

# ── system packages ────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        gnucobol3 \
        openjdk-17-jdk-headless \
        python3 \
        python3-venv \
        python3-pytest \
        python3-fastapi \
        python3-uvicorn \
        python3-httpx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# ── COBOL compilation (per PLAN.md §Build/compile order) ──────────
# All outputs land in /build; COB_LIBRARY_PATH is set so the driver's
# dynamic CALL can resolve .so modules at run time.
RUN mkdir -p /build

# Step 1 – CEE3ABD stub (module)
RUN cobc -m -fsign=EBCDIC \
         -I vendor/carddemo/cpy \
         -o /build/CEE3ABD.so \
         harness/CEE3ABD.cbl

# Step 2 – CBACT04C original, unmodified (module)
RUN cobc -m -fsign=EBCDIC \
         -I vendor/carddemo/cpy \
         -o /build/CBACT04C.so \
         vendor/carddemo/cbl/CBACT04C.cbl

# Step 3 – DRIVER executable
RUN cobc -x \
         -o /build/DRIVER \
         harness/DRIVER.cbl

# Step 4 – LOADER_TCATBALF executable
RUN cobc -x \
         -o /build/LOADER_TCATBALF \
         harness/LOADER_TCATBALF.cbl

# Step 5 – LOADER_XREFFILE executable
RUN cobc -x \
         -o /build/LOADER_XREFFILE \
         harness/LOADER_XREFFILE.cbl

# Step 6 – LOADER_ACCTFILE executable
RUN cobc -x \
         -o /build/LOADER_ACCTFILE \
         harness/LOADER_ACCTFILE.cbl

# Step 7 – LOADER_DISCGRP executable
RUN cobc -x \
         -o /build/LOADER_DISCGRP \
         harness/LOADER_DISCGRP.cbl

# Step 8 – UNLOADER_ACCTFILE executable
RUN cobc -x \
         -o /build/UNLOADER_ACCTFILE \
         harness/UNLOADER_ACCTFILE.cbl

# Step 9 – Cbact04c Java rewrite
RUN mkdir -p /build/java && \
    javac -encoding UTF-8 -d /build/java bob_outputs/Cbact04c.java

# ── runtime environment ────────────────────────────────────────────
ENV PATH="/build:${PATH}"
ENV COB_LIBRARY_PATH="/build"

# ── pre-warm: run the demo proof so report exists at startup ──────
RUN python3 -m parity.runner --seed 7 --accounts 2000

# ── web server ────────────────────────────────────────────────────
CMD python3 -m uvicorn ui.app:app --host 0.0.0.0 --port ${PORT:-8080}
