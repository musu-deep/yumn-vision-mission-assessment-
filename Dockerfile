FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY frontend ./frontend

# إعادة بناء ملف الواجهة من الأجزاء المضغوطة أثناء إنشاء الحاوية.
RUN cat frontend/index.html.gz.b64.part-* \
    | base64 -d \
    | gzip -d \
    > frontend/index.html \
    && rm frontend/index.html.gz.b64.part-*

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
