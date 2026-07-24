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

# فحص الجلسة عند فتح الصفحة هو فحص عام؛ عدم وجود جلسة يعيد 200 بدل 401.
RUN python -c "from pathlib import Path; p=Path('app/main.py'); s=p.read_text(encoding='utf-8'); old='''@app.get(\"/api/auth/me\")\ndef auth_me(identity: dict[str, Any] = Depends(get_identity)):\n    return {\"authenticated\": True, \"user\": {key: identity.get(key, \"\") for key in (\"username\", \"name\", \"phone\", \"role\")}}'''; new='''@app.get(\"/api/auth/me\")\ndef auth_me(request: Request, db: Session = Depends(get_db)):\n    token = request.cookies.get(SESSION_COOKIE, \"\")\n    payload = decode_session_token(token)\n    if not payload:\n        return {\"authenticated\": False, \"user\": None}\n\n    username = str(payload.get(\"sub\") or \"\")\n    role = str(payload.get(\"role\") or \"\")\n    if role == \"admin\":\n        if username != settings.admin_username:\n            return {\"authenticated\": False, \"user\": None}\n        return {\"authenticated\": True, \"user\": {\"username\": username, \"name\": \"مدير منصة يُمن\", \"phone\": \"\", \"role\": \"admin\"}}\n\n    account = db.get(ParticipantAccount, username)\n    if not account or not account.active or account.role not in ALLOWED_PARTICIPANT_ROLES:\n        return {\"authenticated\": False, \"user\": None}\n    if int(payload.get(\"ver\", 0)) != account.session_version:\n        return {\"authenticated\": False, \"user\": None}\n    return {\"authenticated\": True, \"user\": response_user(account)}'''; assert old in s, 'auth_me block not found'; p.write_text(s.replace(old,new,1), encoding='utf-8')"

# إعادة بناء الواجهة والتحقق منها، ثم تطبيق تحديثات النص والحفظ المركزي والجلسات الآمنة.
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
    sed -i 's|نبني الهوية المؤسسية<br>قبل أن نبني الخطة|إطار الاستراتيجية والتوجّه|g' frontend/index.html; \
    sed -i 's|منصة إعداد الرؤية والرسالة والقيم|ورشة بناء الرؤية والرسالة والقيم|g' frontend/index.html; \
    sed -i 's~جمعية يُمن الصحية • نموذج التوجه الاستراتيجي وخطة المائة يوم</span>~جمعية يُمن الصحية • نموذج التوجه الاستراتيجي وخطة المائة يوم | فاس التنموية | 2026</span>~g' frontend/index.html; \
    python -c "from pathlib import Path; p=Path('frontend/index.html'); a=Path('frontend/database-primary.js').read_text(encoding='utf-8'); b=Path('frontend/secure-public.js').read_text(encoding='utf-8'); c=Path('frontend/final-tweaks.js').read_text(encoding='utf-8'); s=p.read_text(encoding='utf-8'); i='<script>var restoreCurrentResponseFromServer,centralUpdateParticipant,centralResetParticipantPin;</script>\n<script>\n'+a+'\n</script>\n<script>\n'+b+'\n</script>\n<script>\n'+c+'\n</script>\n</body>'; p.write_text(s.replace('</body>', i, 1), encoding='utf-8')"; \
    sed -i 's|دخول محمي برمز شخصي لا يظهر لمدير المنصة|دخول محمي برمز شخصي|g' frontend/index.html; \
    sed -i 's|جلسة آمنة تمنع فتح استجابة مشارك آخر|جلسة آمنة وتحليل فوري للإجابات|g' frontend/index.html; \
    grep -q 'var restoreCurrentResponseFromServer' frontend/index.html; \
    grep -q 'إطار الاستراتيجية والتوجّه' frontend/index.html; \
    grep -q 'ورشة بناء الرؤية والرسالة والقيم' frontend/index.html; \
    grep -q 'فاس التنموية | 2026' frontend/index.html; \
    grep -q 'حفظ مركزي تلقائي مع نسخة احتياطية مؤقتة' frontend/index.html; \
    grep -q 'دخول محمي برمز شخصي' frontend/index.html; \
    grep -q 'جلسة آمنة وتحليل فوري للإجابات' frontend/index.html; \
    grep -q 'انتقال سلس من عناصر قمع الرؤية والرسالة' frontend/index.html; \
    grep -q 'قاعدة البيانات هي المصدر الأساسي' frontend/index.html; \
    grep -q 'جاهزية النشر العام' frontend/index.html; \
    rm -f /tmp/index.html.gz frontend/database-primary.js frontend/secure-public.js frontend/final-tweaks.js frontend/deploy.b64.part-* frontend/index.html.gz.b64.part-*

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
