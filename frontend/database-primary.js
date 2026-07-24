/* الحفظ المركزي لمنصة جمعية يُمن الصحية — قاعدة البيانات هي المصدر الأساسي. */
(function () {
  'use strict';

  function sameOriginApiBase() {
    return /^https?:$/.test(window.location.protocol) ? window.location.origin : '';
  }

  defaultIntegrationSettings = function () {
    return {
      apiBaseUrl: sameOriginApiBase(),
      apiToken: '',
      autoSync: true,
      whatsappCountryCode: '966',
      whatsappWebhookUrl: '',
      whatsappTemplate: 'السلام عليكم {name}،\nرمز الوصول إلى الأقسام 9–13 في منصة جمعية يُمن الصحية هو: {code}\nمدة الصلاحية: {days} أيام.\nتاريخ الانتهاء: {expiry}.'
    };
  };

  getIntegrationSettings = function () {
    try {
      const stored = JSON.parse(localStorage.getItem(INTEGRATION_KEY) || '{}');
      const merged = { ...defaultIntegrationSettings(), ...stored };
      if (!merged.apiBaseUrl) merged.apiBaseUrl = sameOriginApiBase();
      merged.autoSync = true;
      return merged;
    } catch (error) {
      return defaultIntegrationSettings();
    }
  };

  apiRequest = async function (path, options = {}) {
    const settings = getIntegrationSettings();
    const base = (settings.apiBaseUrl || sameOriginApiBase()).replace(/\/$/, '');
    if (!base) throw new Error('واجهة الخادم غير متاحة في التشغيل المحلي.');

    const response = await fetch(base + path, {
      ...options,
      headers: {
        ...integrationHeaders(),
        ...(options.headers || {})
      }
    });

    if (!response.ok) {
      const error = new Error(`تعذر تنفيذ الطلب (${response.status}).`);
      error.status = response.status;
      throw error;
    }

    const type = response.headers.get('content-type') || '';
    return type.includes('application/json') ? response.json() : response.text();
  };

  syncCurrentResponse = async function (showMessage = true) {
    if (!currentUser || !activeDataOwner) return false;

    try {
      await apiRequest('/api/responses', {
        method: 'POST',
        body: JSON.stringify({
          username: activeDataOwner,
          user: currentUser,
          data
        })
      });
      if (showMessage) showToast('تم حفظ الاستجابة في قاعدة البيانات');
      return true;
    } catch (error) {
      if (showMessage) showToast('تعذر الاتصال بقاعدة البيانات؛ حُفظت نسخة مؤقتة على الجهاز');
      return false;
    }
  };

  restoreCurrentResponseFromServer = async function () {
    if (!currentUser || currentUser.role === 'admin' || !currentUser.phone) return false;
    if (!activeDataOwner || !activeDataOwner.startsWith('mobile_')) return false;

    try {
      const payload = await apiRequest(
        `/api/responses/${encodeURIComponent(activeDataOwner)}?phone=${encodeURIComponent(currentUser.phone)}`
      );
      if (!payload || !payload.data) return false;

      const serverTime = Date.parse(payload.updatedAt || '') || 0;
      const localTime = Date.parse(data?.system?.savedAt || '') || 0;

      if (serverTime >= localTime) {
        data = mergeDeep(deepClone(initialData), payload.data);
        localStorage.setItem(getCurrentDataKey(), JSON.stringify(data));
        renderAll();
        updateSessionUI();
        applyPermissions();

        if (payload.updatedAt) {
          document.getElementById('footerSavedAt').textContent = new Intl.DateTimeFormat('ar-SA', {
            dateStyle: 'medium',
            timeStyle: 'short'
          }).format(new Date(payload.updatedAt));
        }
        setSaveIndicator(true, 'تم تحميل آخر نسخة من قاعدة البيانات');
      }
      return true;
    } catch (error) {
      if (error.status !== 404) {
        setSaveIndicator(false, 'تعذر الاتصال بقاعدة البيانات — النسخة المحلية متاحة');
      }
      return false;
    }
  };

  saveNow = function (manual = true) {
    data.system = { version: VERSION, savedAt: new Date().toISOString() };
    let localBackupCreated = true;

    try {
      localStorage.setItem(getCurrentDataKey(), JSON.stringify(data));
    } catch (error) {
      localBackupCreated = false;
    }

    const formatted = new Intl.DateTimeFormat('ar-SA', {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(new Date());
    document.getElementById('footerSavedAt').textContent = formatted;

    if (!localBackupCreated) {
      setSaveIndicator(false, 'تعذر إنشاء النسخة الاحتياطية المحلية');
      if (manual) showToast('تعذر حفظ الاستجابة على الجهاز');
      updateProgress();
      return;
    }

    setSaveIndicator(false, 'جارٍ الحفظ في قاعدة البيانات...');
    if (manual) logAction('حفظ الاستجابة', activeDataOwner);
    updateProgress();

    syncCurrentResponse(false).then((savedToDatabase) => {
      setSaveIndicator(
        savedToDatabase,
        savedToDatabase ? 'تم الحفظ في قاعدة البيانات' : 'حُفظت نسخة مؤقتة على الجهاز'
      );
      if (manual) {
        showToast(
          savedToDatabase
            ? 'تم حفظ الاستجابة في قاعدة البيانات'
            : 'تعذر الاتصال بقاعدة البيانات؛ ستبقى النسخة محفوظة على الجهاز مؤقتًا'
        );
      }
    });
  };

  const originalCompleteLogin = completeLogin;
  completeLogin = function (user, action) {
    originalCompleteLogin(user, action);
    window.setTimeout(restoreCurrentResponseFromServer, 80);
  };

  const originalRenderIntegrationPane = renderIntegrationPane;
  renderIntegrationPane = function () {
    originalRenderIntegrationPane();
    const host = document.getElementById('admin-integration');
    if (!host) return;

    const firstCard = host.querySelector('.integration-card');
    const paragraph = firstCard?.querySelector('p');
    if (paragraph) {
      paragraph.textContent = 'الحفظ المركزي مفعّل تلقائيًا لكل مشارك. رمز API مخصص لعمليات الإدارة الشاملة والاستعادة وواتساب فقط.';
    }

    const switchRow = firstCard?.querySelector('.switch-row');
    if (switchRow) {
      switchRow.innerHTML = '<span><strong>الحفظ المركزي</strong><small style="display:block;color:var(--muted)">مفعّل تلقائيًا مع نسخة احتياطية مؤقتة في المتصفح.</small></span><strong style="color:var(--success)">مفعّل</strong>';
    }

    const endpointList = firstCard?.querySelector('.endpoint-list');
    if (endpointList && !endpointList.textContent.includes('استعادة آخر نسخة')) {
      endpointList.insertAdjacentHTML(
        'beforeend',
        '<li><code>GET /api/responses/{username}</code> استعادة آخر نسخة للمشارك</li>'
      );
    }
  };

  const privacyNote = document.querySelector('.privacy-note');
  if (privacyNote) {
    privacyNote.innerHTML = '<strong>تنبيه خصوصية:</strong> تُحفظ استجابات الورشة تلقائيًا في قاعدة البيانات المركزية، مع نسخة احتياطية مؤقتة داخل المتصفح عند انقطاع الاتصال. لا تُدرج بيانات مرضى أو معلومات صحية شخصية حساسة.';
  }

  if (currentUser && currentUser.role !== 'admin') {
    window.setTimeout(restoreCurrentResponseFromServer, 100);
  }
})();
