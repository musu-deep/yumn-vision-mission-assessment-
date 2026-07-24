FROM python:3.12-slim

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY frontend ./frontend

# إعادة بناء الواجهة من الأجزاء الجديدة ثم التحقق من بصمتها قبل تشغيل الخادم.
RUN set -eux; \
    cat \
      frontend/deploy.b64.part-00a \
      frontend/deploy.b64.part-00b \
      frontend/deploy.b64.part-00c \
      frontend/deploy.b64.part-00d \
      frontend/deploy.b64.part-01 \
      frontend/deploy.b64.part-02 \
      frontend/deploy.b64.part-03a \
      frontend/deploy.b64.part-03b \
      frontend/deploy.b64.part-03c \
      frontend/deploy.b64.part-03d \
      frontend/deploy.b64.part-04 \
      frontend/deploy.b64.part-05a \
      frontend/deploy.b64.part-05b \
      frontend/deploy.b64.part-05c \
      frontend/deploy.b64.part-05d \
      | tr -d '\r\n\t ' \
      | base64 -d \
      > /tmp/index.html.gz; \
    gzip -dc /tmp/index.html.gz > frontend/index.html; \
    echo "31e8a408ef7d6bbf0f9868443c62712289fe8c3fe42789d3c898c2da6e37982d  frontend/index.html" | sha256sum -c -; \
    grep -q '<!DOCTYPE html>' frontend/index.html; \
    grep -q '</html>' frontend/index.html; \
    grep -q 'جمعية يُمن الصحية' frontend/index.html; \
    rm -f /tmp/index.html.gz frontend/deploy.b64.part-* frontend/index.html.gz.b64.part-*

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
