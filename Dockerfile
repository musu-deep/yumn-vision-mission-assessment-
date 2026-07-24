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

# إعادة بناء الواجهة من الأجزاء المضغوطة.
# قد تُنتج أداة gzip الملف كاملًا ثم تعيد رمز خروج غير صفري عند وجود اختلاف
# في تذييل CRC/الحجم؛ لذلك نتحقق من سلامة HTML الناتج بدل الاعتماد على الرمز وحده.
RUN set -eux; \
    cat frontend/index.html.gz.b64.part-[0-9][0-9] \
      | tr -d '\r\n\t ' \
      | base64 -d > /tmp/index.html.gz; \
    gzip -dc /tmp/index.html.gz > frontend/index.html || true; \
    test -s frontend/index.html; \
    grep -q '<!DOCTYPE html>' frontend/index.html; \
    grep -q '</html>' frontend/index.html; \
    grep -q 'جمعية يُمن الصحية' frontend/index.html; \
    rm -f /tmp/index.html.gz frontend/index.html.gz.b64.part-[0-9][0-9]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
