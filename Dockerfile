FROM python:3.11-slim

# ── Security: run as non-root ──────────────────────────────────────────────────
# Running containers as root is a security risk.  Create a dedicated user.
RUN useradd -m -u 1000 sno

WORKDIR /app

# ── Dependencies ───────────────────────────────────────────────────────────────
# Copy only requirements first to leverage Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application Source ─────────────────────────────────────────────────────────
COPY . .

# Create runtime directories and transfer ownership to non-root user
RUN mkdir -p playbooks logs \
    && chown -R sno:sno /app

USER sno

# ── Ports ──────────────────────────────────────────────────────────────────────
# 8000 → SNO MCP Server (FastMCP HTTP transport)
# 8501 → SNO Ops Console (Streamlit)
EXPOSE 8000 8501

# ── Default command: MCP Server ────────────────────────────────────────────────
# Override this in docker-compose.yml for the Streamlit service:
#   command: streamlit run src/ui/app.py --server.port 8501 --server.address 0.0.0.0
CMD ["python", "src/main.py"]
