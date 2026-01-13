FROM python:3.11-slim
WORKDIR /app
COPY sub_latency_telemetry.py /app/sub_latency_telemetry.py
RUN pip install --no-cache-dir paho-mqtt==1.6.1
ENV PYTHONUNBUFFERED=1
CMD ["python","-u","/app/sub_latency_telemetry.py"]

