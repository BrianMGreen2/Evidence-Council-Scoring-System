# Evidence Council — Demo
# Builds a self-contained image that runs the governance pipeline demo.
#
# Build:
#   docker build -t evidence-council-demo .
#
# Run (interactive, pauses between scenarios):
#   docker run -it --rm evidence-council-demo
#
# Run (non-interactive, no pauses — good for recording):
#   docker run -it --rm evidence-council-demo non-interactive
#
# Run + save the knowledge layer JSONL to your host machine:
#   docker run -it --rm -v "$(pwd)/output":/demo/output evidence-council-demo

FROM python:3.12-slim

# Metadata
LABEL maintainer="BrianMGreen2"
LABEL description="Evidence Council governance pipeline demo"
LABEL org.opencontainers.image.source="https://github.com/BrianMGreen2/evidence-council"

# Keep the image minimal — no cache, no extras
RUN pip install --no-cache-dir numpy==2.2.4

# Create a non-root user — good hygiene even for a demo image
RUN useradd --create-home --shell /bin/bash demo
WORKDIR /demo
USER demo

# Copy demo files
COPY --chown=demo:demo demo_evidence_council.py .
COPY --chown=demo:demo governance_knowledge_layer_demo.jsonl .

# TERM ensures ANSI colors render correctly in Docker Desktop's terminal
ENV TERM=xterm-256color
ENV PYTHONUNBUFFERED=1

# Entrypoint: default is interactive (pauses between scenarios).
# Pass "non-interactive" as the first argument to auto-advance.
ENTRYPOINT ["python", "demo_evidence_council.py"]
