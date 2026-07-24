/* جاهزية النشر العام: جلسات آمنة، رمز شخصي، حماية الإدارة، واستعادة مركزية. */
(function () {
  'use strict';

  let publicAuthConfig = {
    participantPinRequired: true,
    pinLength: 6,
    studyCodeRequired: false,
    sessionHours: 12
  };

  function ensureSecureLoginFields() {
    const quick = document.getElementById('quickLoginFields');
    if (!quick || document.getElementById('participantPinField')) return;

    quick.insertAdjacentHTML('beforeend', `
      <div class="auth-field" id="participantPinField">
        <label>الرمز الشخصي</label>
        <input id="participantPin" type="password" inputmode="numeric" autocomplete="current-password"
          minlength="6" maxlength="12" placeholder="6 أرقام تحفظ بها مشاركتك" required />
        <span class="help">أنشئ رمزًا من 6 أرقام عند الدخول الأول، واستخدمه لاحقًا لاستعادة مشاركتك من أي جهاز.</span>
      </div>
      <div class="auth-field hidden" id="studyAccessField">
        <label>رمز مجتمع الدراسة</label>
        <input id="studyAccessCode" type="password" autocomplete="one-time-code" maxlength="64"
          placeholder="الرمز المرفق مع دعوة المشاركة" />
      </div>
    `);

    const intro = document.getElementById('authIntro');
    if (intro) intro.textContent = 'أدخل اسمك ورقم جوالك ورمزك الشخصي، ثم ابدأ تعبئة النموذج أو استعد مشاركتك السابقة.';

    const note = document.querySelector('.auth-note');
    if (note) {
      note.innerHTML = '<strong>تنبيه:</strong> يُنشئ المشارك رمزًا شخصيًا من 6 أرقام لحماية الاستجابة واستعادتها من أي جهاز. لا تشارك الرمز مع الآخرين.';
    }

    const features = document.querySelectorAll('.auth-feature span');
    if (features[0]) features[0].textContent = 'حفظ مركزي تلقائي مع نسخة احتياطية مؤقتة';
    if (features[1]) features[1].textContent = 'دخول محمي برمز شخصي لا يظهر لمدير المنصة';
    if (features[2]) features[2].textContent = 'جلسة آمنة تمنع فتح استجابة مشارك آخر';
  }

  function applyPublicConfig(config) {
    publicAuthConfig = { ...publicAuthConfig, ...(config || {}) };
    const pin = document.getElementById('participantPin');
    if (pin) {
      pin.minLength = Number(publicAuthConfig.pinLength || 6);
      pin.placeholder = `${publicAuthConfig.pinLength || 6} أرقام تحفظ بها مشاركتك`;
    }
    const studyField = document.getElementById('studyAccessField');
    const studyInput = document.getElementById('studyAccessCode');
    if (studyField) studyField.classList.toggle('hidden', !publicAuthConfig.studyCodeRequired);
    if (studyInput) studyInput.required = !adminLoginMode && !!publicAuthConfig.studyCodeRequired;
  }

  function apiBase() {
    return /^https?:$/.test(window.location.protocol) ? window.location.origin : '';
  }

  function parseErrorMessage(payload, statusCode) {
    const detail = payload && typeof payload === 'object' ? payload.detail : '';
    if (statusCode === 401) return detail || 'بيانات الدخول غير صحيحة.';
    if (statusCode === 403) return detail || 'لا تملك صلاحية تنفيذ هذا الإجراء.';
    if (statusCode === 429) return 'تم تجاوز عدد المحاولات المسموح. انتظر قليلًا ثم أعد المحاولة.';
    return detail || `تعذر تنفيذ الطلب (${statusCode}).`;
  }

  apiRequest = async function (path, options = {}) {
    const base = apiBase();
    if (!base) throw new Error('يتطلب الحفظ المركزي فتح المنصة من رابطها المنشور.');

    const settings = getIntegrationSettings ? getIntegrationSettings() : {};
    const headers = {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {})
    };
    if (settings.apiToken) headers['X-API-Key'] = settings.apiToken;

    const response = await fetch(base + path, {
      ...options,
      credentials: 'same-origin',
      headers
    });

    const type = response.headers.get('content-type') || '';
    const payload = type.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) {
      const error = new Error(parseErrorMessage(payload, response.status));
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  };

  defaultIntegrationSettings = function () {
    return {
      apiBaseUrl: apiBase(),
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
      return {
        ...defaultIntegrationSettings(),
        ...stored,
        apiBaseUrl: apiBase(),
        autoSync: true
      };
    } catch (error) {
      return defaultIntegrationSettings();
    }
  };

  function rememberUserLocally(user) {
    const users = getUsers().filter(item => item.username !== user.username || item.role === 'admin');
    if (user.role !== 'admin') {
      users.push({
        username: user.username,
        name: user.name,
        phone: user.phone || '',
        role: user.role || 'editor',
        active: true,
        createdAt: new Date().toISOString()
      });
    }
    saveUsers(users);
  }

  function activateSecureUser(user) {
    rememberUserLocally(user);
    currentUser = {
      username: user.username,
      name: user.name,
      phone: user.phone || '',
      role: user.role
    };
    activeDataOwner = user.username;
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(currentUser));
    document.getElementById('authError').textContent = '';
    document.getElementById('authScreen').classList.add('hidden');
    document.body.classList.remove('auth-locked');
    updateSessionUI();
    loadData();
  }

  const originalToggleAdminLogin = toggleAdminLogin;
  toggleAdminLogin = function (forceParticipant = false) {
    originalToggleAdminLogin(forceParticipant);
    const pin = document.getElementById('participantPin');
    const studyCode = document.getElementById('studyAccessCode');
    if (pin) pin.required = !adminLoginMode;
    if (studyCode) studyCode.required = !adminLoginMode && !!publicAuthConfig.studyCodeRequired;
    if (!adminLoginMode) {
      document.getElementById('authIntro').textContent = 'أدخل اسمك ورقم جوالك ورمزك الشخصي، ثم ابدأ تعبئة النموذج أو استعد مشاركتك السابقة.';
    } else {
      document.getElementById('authIntro').textContent = 'تتم مطابقة بيانات الإدارة على الخادم، ولا تُحفظ كلمة المرور داخل المتصفح.';
    }
  };

  handleLogin = async function (event) {
    event.preventDefault();
    const errorBox = document.getElementById('authError');
    const submitButton = document.getElementById('loginSubmitBtn');
    errorBox.textContent = '';
    submitButton.disabled = true;
    submitButton.textContent = 'جارٍ التحقق...';

    try {
      let result;
      if (adminLoginMode) {
        const username = document.getElementById('adminUsername').value.trim();
        const password = document.getElementById('adminPassword').value;
        result = await apiRequest('/api/auth/admin', {
          method: 'POST',
          body: JSON.stringify({ username, password })
        });
      } else {
        const name = document.getElementById('quickName').value.trim();
        const phone = document.getElementById('quickPhone').value.trim();
        const pin = document.getElementById('participantPin').value.trim();
        const studyCode = document.getElementById('studyAccessCode')?.value.trim() || '';

        if (name.length < 2) throw new Error('فضلاً أدخل الاسم الكامل.');
        if (normalizePhone(phone).length < 8 || normalizePhone(phone).length > 15) throw new Error('فضلاً أدخل رقم جوال صحيحًا.');
        if (!/^\d{6,12}$/.test(pin)) throw new Error('الرمز الشخصي يجب أن يتكون من 6 أرقام على الأقل.');

        result = await apiRequest('/api/auth/participant', {
          method: 'POST',
          body: JSON.stringify({ name, phone, pin, study_code: studyCode })
        });
      }

      activateSecureUser(result.user);
      logAction(adminLoginMode ? 'تسجيل دخول الإدارة الآمن' : (result.created ? 'إنشاء مشاركة آمنة' : 'دخول مشارك آمن'));
      if (result.user.role !== 'admin') await restoreCurrentResponseFromServer();
    } catch (error) {
      errorBox.textContent = error.message || 'تعذر تسجيل الدخول.';
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = adminLoginMode ? 'دخول الإدارة' : 'الدخول إلى المنصة';
    }
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
      if (error.status === 401) {
        showToast('انتهت الجلسة. سجّل الدخول مجددًا لحفظ التعديلات.');
      } else if (showMessage) {
        showToast('تعذر الاتصال بقاعدة البيانات؛ حُفظت نسخة مؤقتة على الجهاز');
      }
      return false;
    }
  };

  restoreCurrentResponseFromServer = async function () {
    if (!currentUser || currentUser.role === 'admin') return false;
    try {
      const payload = await apiRequest('/api/responses/me');
      if (!payload || !payload.data) return false;

      const serverTime = Date.parse(payload.updatedAt || '') || 0;
      const localTime = Date.parse(data?.system?.savedAt || '') || 0;
      if (serverTime >= localTime) {
        data = mergeDeep(deepClone(initialData), payload.data);
        localStorage.setItem(getCurrentDataKey(), JSON.stringify(data));
        renderAll();
        updateSessionUI();
        applyPermissions();
        setSaveIndicator(true, 'تم تحميل آخر نسخة من قاعدة البيانات');
      }
      return true;
    } catch (error) {
      if (error.status !== 404) setSaveIndicator(false, 'تعذر استعادة النسخة المركزية — النسخة المحلية متاحة');
      return false;
    }
  };

  logoutUser = async function () {
    try {
      if (currentUser && currentUser.role !== 'admin') await syncCurrentResponse(false);
      await apiRequest('/api/auth/logout', { method: 'POST', body: '{}' });
    } catch (error) {
      // إنهاء الجلسة محليًا حتى إذا تعذر الوصول إلى الخادم.
    }
    if (currentUser) sessionStorage.removeItem(ADVANCED_ACCESS_SESSION_PREFIX + currentUser.username);
    currentUser = null;
    activeDataOwner = '';
    sessionStorage.removeItem(SESSION_KEY);
    document.getElementById('authScreen').classList.remove('hidden');
    document.body.classList.add('auth-locked');
    document.getElementById('loginForm').reset();
    toggleAdminLogin(true);
    document.getElementById('authError').textContent = '';
  };

  async function fetchCentralParticipants() {
    return apiRequest('/api/admin/participants');
  }

  renderUsersPane = function () {
    const host = document.getElementById('admin-users');
    host.innerHTML = '<div class="admin-card"><h3>المشاركون المسجلون مركزيًا</h3><p>جارٍ تحميل الحسابات من قاعدة البيانات...</p></div>';
    fetchCentralParticipants().then(payload => {
      const participants = payload.participants || [];
      host.innerHTML = `<div class="admin-card">
        <h3>المشاركون المسجلون مركزيًا</h3>
        <p class="mini-note">الحسابات محمية برمز شخصي مشفّر. يمكن إيقاف الحساب، تعديل الصلاحية، أو إصدار رمز شخصي مؤقت عند نسيانه.</p>
        <div class="table-wrap"><table style="min-width:980px"><thead><tr>
          <th>الاسم</th><th>الجوال</th><th>الصلاحية</th><th>الحالة</th><th>الاستجابة</th><th>الإجراءات</th>
        </tr></thead><tbody>${participants.map(item => `
          <tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.phone)}</td>
          <td><select onchange="centralUpdateParticipant('${encodeURIComponent(item.username)}',{role:this.value})">${roleOptions(item.role)}</select></td>
          <td>${item.active ? 'نشط' : 'موقوف'}</td><td>${item.hasResponse ? 'بدأ التعبئة' : 'لم يبدأ'}</td>
          <td><div class="row-actions">
            <button class="icon-btn" title="${item.active ? 'إيقاف' : 'تفعيل'}" onclick="centralUpdateParticipant('${encodeURIComponent(item.username)}',{active:${!item.active}})">${item.active ? '⏸' : '▶'}</button>
            <button class="icon-btn" title="إصدار رمز شخصي مؤقت" onclick="centralResetParticipantPin('${encodeURIComponent(item.username)}')">🔑</button>
          </div></td></tr>`).join('') || '<tr><td colspan="6">لا توجد حسابات مسجلة بعد.</td></tr>'}</tbody></table></div>
      </div>`;
    }).catch(error => {
      host.innerHTML = `<div class="admin-card"><h3>المشاركون</h3><p>${escapeHtml(error.message)}</p></div>`;
    });
  };

  renderResponsesPane = function () {
    const host = document.getElementById('admin-responses');
    host.innerHTML = '<div class="admin-card"><h3>الاستجابات المركزية</h3><p>جارٍ تحميل البيانات...</p></div>';
    fetchCentralParticipants().then(payload => {
      const participants = payload.participants || [];
      const rows = participants.map(item => `<tr>
        <td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.phone)}</td><td>${ROLE_LABELS[item.role] || item.role}</td>
        <td>${item.hasResponse ? 'بدأ التعبئة' : 'لم يبدأ'}</td>
        <td>${item.responseUpdatedAt ? new Intl.DateTimeFormat('ar-SA',{dateStyle:'short',timeStyle:'short'}).format(new Date(item.responseUpdatedAt)) : '—'}</td>
        <td><div class="row-actions">
          <button class="icon-btn" title="فتح" onclick="adminOpenResponse('${encodeURIComponent(item.username)}')">↗</button>
          <button class="icon-btn" title="تنزيل JSON" onclick="adminDownloadResponse('${encodeURIComponent(item.username)}')">↓</button>
          <button class="icon-btn delete" title="حذف الاستجابة" onclick="adminDeleteResponse('${encodeURIComponent(item.username)}')">×</button>
        </div></td></tr>`).join('');
      host.innerHTML = `<div class="admin-card"><h3>استجابات المشاركين في قاعدة البيانات</h3>
        <div class="table-wrap"><table style="min-width:900px"><thead><tr><th>المستخدم</th><th>الجوال</th><th>الصلاحية</th><th>الحالة</th><th>آخر حفظ</th><th>الإجراءات</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="6">لا توجد مشاركات بعد.</td></tr>'}</tbody></table></div></div>`;
    }).catch(error => {
      host.innerHTML = `<div class="admin-card"><h3>الاستجابات</h3><p>${escapeHtml(error.message)}</p></div>`;
    });
  };

  centralUpdateParticipant = async function (encoded, patch) {
    try {
      await apiRequest(`/api/admin/participants/${encoded}`, { method: 'PATCH', body: JSON.stringify(patch) });
      showToast('تم تحديث حساب المشارك');
      renderUsersPane();
      renderResponsesPane();
    } catch (error) {
      alert(error.message);
    }
  };

  centralResetParticipantPin = async function (encoded) {
    if (!confirm('سيتم إلغاء الجلسات السابقة وإصدار رمز شخصي مؤقت جديد. متابعة؟')) return;
    try {
      const payload = await apiRequest(`/api/admin/participants/${encoded}/reset-pin`, { method: 'POST', body: '{}' });
      const pin = payload.temporaryPin;
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(pin).catch(() => {});
      }
      prompt('الرمز الشخصي المؤقت — أرسله للمشارك عبر قناة موثوقة:', pin);
      renderUsersPane();
    } catch (error) {
      alert(error.message);
    }
  };

  adminOpenResponse = async function (encoded) {
    try {
      const payload = await apiRequest(`/api/responses/${encoded}`);
      activeDataOwner = decodeURIComponent(encoded);
      data = mergeDeep(deepClone(initialData), payload.data || {});
      localStorage.setItem(getCurrentDataKey(activeDataOwner), JSON.stringify(data));
      closeAdminPanel();
      renderAll();
      updateOwnerBar();
      applyPermissions();
      showToast('تم تحميل الاستجابة من قاعدة البيانات');
    } catch (error) {
      alert(error.message);
    }
  };

  adminDownloadResponse = async function (encoded) {
    try {
      const payload = await apiRequest(`/api/responses/${encoded}`);
      downloadBlob(JSON.stringify(payload.data || {}, null, 2), `استجابة_${decodeURIComponent(encoded)}.json`, 'application/json;charset=utf-8');
    } catch (error) {
      alert(error.message);
    }
  };

  adminDeleteResponse = async function (encoded) {
    if (!confirm('حذف الاستجابة المركزية لهذا المشارك؟ لا يمكن التراجع عن العملية.')) return;
    try {
      await apiRequest(`/api/admin/responses/${encoded}`, { method: 'DELETE' });
      showToast('تم حذف الاستجابة من قاعدة البيانات');
      renderResponsesPane();
    } catch (error) {
      alert(error.message);
    }
  };

  async function bootstrapSecureAuth() {
    ensureSecureLoginFields();
    document.body.classList.add('auth-locked');
    document.getElementById('authScreen').classList.remove('hidden');

    try {
      const config = await apiRequest('/api/public-config');
      applyPublicConfig(config);
    } catch (error) {
      applyPublicConfig(publicAuthConfig);
    }

    try {
      const session = await apiRequest('/api/auth/me');
      if (session && session.authenticated && session.user) {
        activateSecureUser(session.user);
        if (session.user.role !== 'admin') await restoreCurrentResponseFromServer();
        return;
      }
    } catch (error) {
      sessionStorage.removeItem(SESSION_KEY);
      currentUser = null;
      activeDataOwner = '';
    }

    document.getElementById('authScreen').classList.remove('hidden');
    document.body.classList.add('auth-locked');
    toggleAdminLogin(true);
  }

  const originalRenderIntegrationPane = renderIntegrationPane;
  renderIntegrationPane = function () {
    originalRenderIntegrationPane();
    const host = document.getElementById('admin-integration');
    const paragraph = host?.querySelector('.integration-card p');
    if (paragraph) paragraph.textContent = 'الحفظ المركزي والجلسات الآمنة مفعّلان تلقائيًا. لا يحتاج المشارك إلى API Key.';
    const tokenField = document.getElementById('integrationApiToken')?.closest('.field');
    if (tokenField) tokenField.style.display = 'none';
  };

  bootstrapSecureAuth();
})();
