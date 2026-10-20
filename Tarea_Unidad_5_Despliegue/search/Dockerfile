FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# UID numérico para que Kubernetes pueda verificar runAsNonRoot.
RUN useradd --uid 10001 --no-create-home app
USER 10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
