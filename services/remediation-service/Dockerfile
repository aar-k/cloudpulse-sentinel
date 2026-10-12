FROM python:3.12-slim
WORKDIR /srv
COPY services/remediation-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/remediation-service/remediation_svc ./remediation_svc
EXPOSE 8000
CMD ["uvicorn", "remediation_svc.main:app", "--host", "0.0.0.0", "--port", "8000"]
