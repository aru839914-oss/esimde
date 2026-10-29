(function () {
  'use strict';
  if (!window.App) return;

  const POLL_MS = 15000;
  const supported = 'Notification' in window;
  const pushSupported = 'serviceWorker' in navigator && 'PushManager' in window && window.isSecureContext;
  const browserEnabled = document.body.dataset.browserNotify === '1';
  const DISMISS_KEY = 'esimde.permissionDismissed';
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  let pushActive = false;

  function permission() {
    return supported ? Notification.permission : 'unsupported';
  }

  function keyToBytes(b64) {
    const pad = '='.repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }

  async function currentSubscription() {
    if (!pushSupported) return null;
    const reg = await navigator.serviceWorker.ready;
    return reg.pushManager.getSubscription();
  }

  async function enablePush(quiet = false) {
    if (!supported) {
      if (!quiet) App.showToast('Бұл браузер хабарландыруларды қолдамайды. Ескертулер сайттың ішінде көрсетіледі.', 'warning');
      return false;
    }
    const perm = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
    hideBanner();
    if (perm !== 'granted') {
      if (!quiet) App.showToast('Рұқсат берілмеді. Еске салулар сайттың ішінде көрсетіледі.', 'warning');
      renderPermissionStatus();
      return false;
    }
    if (!pushSupported) {
      if (!quiet) App.showToast(isIOS && !isStandalone
        ? 'iPhone-да push үшін алдымен сайтты басты экранға қосыңыз (Бөлісу → «Басты экранға»).'
        : 'Бұл браузер push-ты қолдамайды: хабарламалар сайт ашық кезде көрсетіледі.', 'info', 7000);
      renderPermissionStatus();
      return true;
    }
    try {
      const key = await App.api('/api/push/key');
      if (!key.enabled) throw new Error('Push хабарландырулары серверде өшірулі.');
      const reg = await navigator.serviceWorker.ready;
      let sub = await reg.pushManager.getSubscription();
      const appKey = keyToBytes(key.public_key);
      const sameKey = sub && sub.options && sub.options.applicationServerKey &&
        new Uint8Array(sub.options.applicationServerKey).join() === appKey.join();
      if (sub && !sameKey) { await sub.unsubscribe(); sub = null; }
      if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: appKey });
      const res = await App.api('/api/push/subscribe', { method: 'POST', body: sub.toJSON() });
      pushActive = true;
      if (!quiet) App.showToast(res.message, 'success');
    } catch (err) {
      if (!quiet && err.message !== 'unauthorized') App.showToast(err.message || 'Push-ты қосу мүмкін болмады.', 'danger');
    }
    renderPermissionStatus();
    return pushActive;
  }

  async function disablePush() {
    const sub = await currentSubscription().catch(() => null);
    if (sub) {
      await App.api('/api/push/unsubscribe', { method: 'POST', body: { endpoint: sub.endpoint } }).catch(() => null);
      await sub.unsubscribe().catch(() => null);
    }
    pushActive = false;
    App.showToast('Push хабарландырулары осы құрылғыда өшірілді.', 'info');
    renderPermissionStatus();
  }

  function showBrowserNotification(title, body, eventId) {
    if (pushActive) return false;
    if (!supported || !browserEnabled || Notification.permission !== 'granted') return false;
    try {
      const n = new Notification(title, { body: body, tag: eventId ? `event-${eventId}` : undefined });
      n.onclick = () => { window.focus(); if (eventId) App.openEvent(eventId); n.close(); };
      return true;
    } catch (e) {
      return false;
    }
  }

  let polling = false;
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const items = await App.api('/api/notifications/pending');
      if (items.length) {
        items.forEach((n) => {
          App.showReminderToast(n);
          showBrowserNotification('Esimde', n.message, n.event_id);
        });
        await App.api('/api/notifications/ack', { method: 'POST', body: { ids: items.map((n) => n.id) } });
        markNew(items.length);
        document.dispatchEvent(new CustomEvent('reminders:updated'));
      }
    } catch (e) {

    } finally {
      polling = false;
    }
  }

  function markNew(count) {
    const dot = document.getElementById('bellDot');
    const badge = document.getElementById('navReminderBadge');
    if (dot) dot.classList.remove('d-none');
    if (badge) {
      badge.textContent = String((parseInt(badge.textContent, 10) || 0) + count);
      badge.classList.remove('d-none');
    }
  }

  const banner = document.getElementById('permissionBanner');
  function hideBanner() { if (banner) banner.classList.add('d-none'); }
  function dismissed() { try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch (e) { return false; } }

  if (banner && browserEnabled && permission() === 'default' && !dismissed()) {
    banner.classList.remove('d-none');
    document.getElementById('permissionAllow').addEventListener('click', () => enablePush());
    document.getElementById('permissionDismiss').addEventListener('click', () => {
      try { localStorage.setItem(DISMISS_KEY, '1'); } catch (e) {  }
      hideBanner();
    });
  }

  function statusInfo() {
    const state = permission();
    if (state === 'unsupported') return ['unsupported', 'bi-slash-circle', 'Қолдау жоқ', 'Бұл браузер хабарландыруларды қолдамайды. Ескертулер сайттың ішінде көрсетіледі.'];
    if (state === 'denied') return ['denied', 'bi-x-circle-fill', 'Рұқсат берілмеген', 'Ескертулер тек сайттың ішінде көрсетіледі. Рұқсатты браузер баптауларынан өзгертуге болады.'];
    if (state === 'default') return ['default', 'bi-question-circle-fill', 'Қосылмаған', '«Push-ты қосу» батырмасын басып, рұқсат беріңіз.'];
    if (pushActive) return ['granted', 'bi-check-circle-fill', 'Push қосылған', 'Еске салулар осы құрылғыға сайт жабық болса да келеді.'];
    if (!pushSupported) return ['default', 'bi-info-circle-fill', 'Рұқсат бар, push жоқ', isIOS && !isStandalone
      ? 'iPhone-да push үшін сайтты басты экранға қосып, сол жерден ашыңыз.'
      : 'Хабарламалар сайт ашық кезде ғана көрсетіледі (push үшін HTTPS қажет).'];
    return ['default', 'bi-exclamation-circle-fill', 'Рұқсат бар, push қосылмаған', '«Push-ты қосу» батырмасын басыңыз.'];
  }

  function renderPermissionStatus() {
    const box = document.getElementById('permissionStatus');
    if (!box) return;
    const [cls, icon, title, desc] = statusInfo();
    box.className = `permission-status ${cls}`;
    box.querySelector('.ps-icon i').className = `bi ${icon}`;
    box.querySelector('.ps-title').textContent = title;
    box.querySelector('.ps-desc').textContent = desc;
    const enableBtn = document.getElementById('pushEnableBtn');
    const disableBtn = document.getElementById('pushDisableBtn');
    if (enableBtn) enableBtn.classList.toggle('d-none', pushActive || permission() === 'denied' || permission() === 'unsupported');
    if (disableBtn) disableBtn.classList.toggle('d-none', !pushActive);
  }

  const enableBtn = document.getElementById('pushEnableBtn');
  if (enableBtn) enableBtn.addEventListener('click', () => enablePush());
  const disableBtn = document.getElementById('pushDisableBtn');
  if (disableBtn) disableBtn.addEventListener('click', disablePush);
  const testBtn = document.getElementById('testNotificationBtn');
  if (testBtn) {
    testBtn.addEventListener('click', async () => {
      if (pushActive) {
        try { App.showToast((await App.api('/api/push/test', { method: 'POST', body: {} })).message, 'success'); }
        catch (err) { if (err.message !== 'unauthorized') App.showToast(err.message, 'danger'); }
        return;
      }
      const msg = 'Еске салу: бұл тексеру хабарламасы. Хабарландырулар дұрыс жұмыс істейді!';
      App.showToast(msg, 'reminder', 6000);
      if (!browserEnabled) App.showToast('Браузерлік хабарландырулар баптауларда өшірулі.', 'info');
      else if (!showBrowserNotification('Esimde', msg)) App.showToast('Браузерлік хабарландыру көрсетілмеді: рұқсат жоқ.', 'warning');
    });
  }
  renderPermissionStatus();

  if (pushSupported && browserEnabled && permission() === 'granted') {
    currentSubscription()
      .then((sub) => { pushActive = !!sub; renderPermissionStatus(); return enablePush(true); })
      .catch(() => null);
  }

  let installPrompt = null;
  const installBtn = document.getElementById('installBtn');
  const installStatus = document.getElementById('installStatus');
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    installPrompt = e;
    if (installBtn) installBtn.classList.remove('d-none');
  });
  if (installBtn) {
    installBtn.addEventListener('click', async () => {
      if (!installPrompt) return;
      installPrompt.prompt();
      const choice = await installPrompt.userChoice;
      installPrompt = null;
      installBtn.classList.add('d-none');
      if (choice.outcome === 'accepted') App.showToast('Esimde қолданбасы орнатылды!', 'success');
    });
  }
  if (installStatus) {
    if (isStandalone) installStatus.textContent = '✅ Esimde қолданба ретінде ашылған.';
    else if (isIOS) installStatus.innerHTML = 'iPhone/iPad: Safari-де <b>Бөлісу</b> <i class="bi bi-box-arrow-up"></i> → <b>«Басты экранға қосу»</b>.';
    else installStatus.innerHTML = 'Android: Chrome мәзірі <b>⋮</b> → <b>«Қолданбаны орнату»</b>. Компьютерде мекенжай жолағындағы <i class="bi bi-download"></i> белгішесі.';
  }
  window.addEventListener('appinstalled', () => App.showToast('Esimde қолданбасы орнатылды!', 'success'));

  const widget = document.getElementById('reminderWidget');
  const recentBox = document.getElementById('recentNotifications');

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  async function refreshWidget() {
    if (!widget) return;
    try {
      const data = await App.api(widget.dataset.url);
      widget.innerHTML = data.upcoming.length ? data.upcoming.map((r) => `
        <div class="mini-row" style="--cat:${escapeHtml(r.color)}">
          <div class="mini-icon"><i class="bi ${escapeHtml(r.icon)}"></i></div>
          <div class="flex-fill min-w-0">
            <button type="button" class="event-title mini-title" data-event-id="${r.id}">${escapeHtml(r.title)}</button>
            <div class="mini-sub"><i class="bi bi-bell"></i> ${escapeHtml(r.when)}</div>
          </div>
        </div>`).join('')
        : '<div class="empty-mini"><i class="bi bi-bell-slash"></i> Жоспарланған еске салулар жоқ</div>';
      recentBox.innerHTML = data.recent.length ? data.recent.map((n) => `
        <div class="mini-row" style="--cat:${n.status === 'late' ? '#f59e0b' : '#10b981'}">
          <div class="mini-icon"><i class="bi bi-bell-fill"></i></div>
          <div class="mini-sub text-body">${escapeHtml(n.message)}</div>
        </div>`).join('')
        : '<div class="empty-mini"><i class="bi bi-envelope-open"></i> Әзірге хабарландыру жоқ</div>';
    } catch (e) {
      widget.innerHTML = '<div class="empty-mini text-danger"><i class="bi bi-wifi-off"></i> Деректерді жүктеу мүмкін болмады</div>';
    }
  }

  async function refreshStats() {
    if (!document.querySelector('[data-stat]')) return;
    try { App.updateStats(await App.api('/api/stats')); } catch (e) {  }
  }

  document.addEventListener('reminders:updated', () => { refreshWidget(); refreshStats(); });
  document.addEventListener('events:changed', refreshWidget);
  refreshWidget();

  poll();
  setInterval(poll, POLL_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
})();
