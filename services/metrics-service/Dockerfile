FROM python:3.12-slim
WORKDIR /srv
COPY services/metrics-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/metrics-service/metrics_svc ./metrics_svc
EXPOSE 8000
CMD ["uvicorn", "metrics_svc.main:app", "--host", "0.0.0.0", "--port", "8000"]
