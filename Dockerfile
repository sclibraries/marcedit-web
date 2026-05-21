FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY marcedit_web ./marcedit_web
COPY data ./data
COPY .streamlit ./.streamlit

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health').read().startswith(b'ok') else 1)"

CMD ["streamlit", "run", "marcedit_web/Home.py", "--server.address=0.0.0.0", "--server.port=8501"]
