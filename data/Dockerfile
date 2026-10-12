FROM python:3.12-slim
WORKDIR /srv
COPY data/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY data/simulator.py .
CMD ["python", "-u", "simulator.py"]
