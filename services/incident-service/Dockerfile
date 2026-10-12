FROM python:3.12-slim
WORKDIR /srv
COPY services/incident-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/incident-service/incident_svc ./incident_svc
COPY ml/models /srv/models
ENV MODEL_DIR=/srv/models
EXPOSE 8000
CMD ["uvicorn", "incident_svc.main:app", "--host", "0.0.0.0", "--port", "8000"]
