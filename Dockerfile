FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY evaluation ./evaluation
COPY .streamlit ./.streamlit

RUN useradd --create-home appuser
USER appuser

EXPOSE 8501

HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["python", "-m", "streamlit", "run", "app/ui/dashboard.py", "--server.address=0.0.0.0", "--server.port=8501"]
