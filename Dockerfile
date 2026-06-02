FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY marcedit_web ./marcedit_web
COPY data ./data
COPY .streamlit ./.streamlit

# Stage 21: run as an unprivileged user. A compromised user-task that
# survives the sandbox no longer comes back as root.
#
# TASK-029 / Stage Medium 1: only ``/app/data`` is writable by the
# marcedit user — application code under ``/app/marcedit_web`` etc.
# stays root-owned and mode 0755 (readable by all, writable by no
# one). A sandboxed task that escapes its workdir can no longer
# overwrite the sandbox driver itself, page render code, etc.
RUN groupadd --system --gid 10001 marcedit \
    && useradd --system --uid 10001 --gid marcedit --no-create-home --shell /usr/sbin/nologin marcedit \
    && mkdir -p /app/data /app/data/audit /app/data/tasks \
    && chown -R marcedit:marcedit /app/data

USER marcedit

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health').read().startswith(b'ok') else 1)"

CMD ["streamlit", "run", "marcedit_web/App.py", "--server.address=0.0.0.0", "--server.port=8501"]
