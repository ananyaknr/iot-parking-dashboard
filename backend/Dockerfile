FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home parking
COPY main.py model.py ./
USER parking
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
