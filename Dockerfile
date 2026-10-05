FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY robotrss ./robotrss
ENV DB_PATH=/data/robotrss.sqlite
VOLUME /data
CMD ["python", "-m", "robotrss"]
