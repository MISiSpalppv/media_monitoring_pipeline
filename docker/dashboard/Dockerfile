FROM python:3.12-slim

WORKDIR /app

COPY docker/dashboard/requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--client.toolbarMode=viewer"]
