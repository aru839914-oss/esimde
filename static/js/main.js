(function () {
  'use strict';

  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const CSRF = csrfMeta ? csrfMeta.content : '';

  async function api(url, options = {}) {
    const opts = Object.assign({ headers: {} }, options);
    opts.headers['Accept'] = 'application/json';
    if (opts.body && typeof opts.body !== 'string') {
      opts.body = JSON.stringify(opts.body);
      opts.headers['Content-Type'] = 'application/json';
    }
    if (opts.method && opts.method !== 'GET') opts.headers['X-CSRFToken'] = CSRF;
    const res = await fetch(url, opts);
    if (res.status === 401) { window.location.href = '/login'; throw new Error('unauthorized'); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Сұраныс орындалмады. Қайталап көріңіз.');
    return data;
  }

  const ICONS = { success: 'bi-check-lg', danger: 'bi-x-lg', warning: 'bi-exclamation-lg', info: 'bi-info-lg', reminder: 'bi-bell-fill' };

  function showToast(message, type = 'info', delay = 4500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast app-toast ${type}`;
    el.setAttribute('role', type === 'danger' ? 'alert' : 'status');
    el.innerHTML = `<div class="toast-body">
        <span class="t-icon"><i class="bi ${ICONS[type] || ICONS.info}"></i></span>
        <div class="flex-fill"></div>
        <button type="button" class="btn-close btn-sm" data-bs-dismiss="toast" aria-label="Жабу"></button>
      </div>`;
    el.querySelector('.flex-fill').textContent = message;
    container.appendChild(el);
    const toast = new bootstrap.Toast(el, { delay: delay, autohide: delay > 0 });
    el.addEventListener('hidden.bs.toast', () => el.remove());
    toast.show();
  }

  function showReminderToast(n) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const el = document.createElement('div');
    el.className = 'toast app-toast reminder';
    el.setAttribute('role', 'alert');
    el.innerHTML = `<div class="toast-body">
        <span class="t-icon"><i class="bi bi-bell-fill"></i></span>
        <div class="flex-fill"><div class="t-text"></div>
          <div class="t-actions">
            <button type="button" class="btn btn-sm btn-primary" data-act="done"><i class="bi bi-check2"></i> Орындалды</button>
            <button type="button" class="btn btn-sm btn-outline" data-act="snooze" data-min="10"><i class="bi bi-alarm"></i> 10 мин</button>
            <button type="button" class="btn btn-sm btn-outline" data-act="snooze" data-min="60">1 сағат</button>
          </div>
        </div>
        <button type="button" class="btn-close btn-sm" data-bs-dismiss="toast" aria-label="Жабу"></button>
      </div>`;
    el.querySelector('.t-text').textContent = n.message;
    if (!n.event_id) el.querySelector('.t-actions').remove();
    container.appendChild(el);
    const toast = new bootstrap.Toast(el, { autohide: false });
    el.addEventListener('hidden.bs.toast', () => el.remove());
    el.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-act]');
      if (!btn) return;
      btn.disabled = true;
      try {
        if (btn.dataset.act === 'done') {
          const data = await api(`/api/events/${n.event_id}/complete`, { method: 'POST', body: { completed: true } });
          document.querySelectorAll(`[data-item="${n.event_id}"]`).forEach((item) => applyCompleted(item, data.event));
          updateStats(data.stats);
          showToast(data.message, 'success', 3000);
        } else {
          const data = await api(`/api/events/${n.event_id}/snooze`, { method: 'POST', body: { minutes: Number(btn.dataset.min) } });
          showToast(data.message, 'info', 3500);
        }
        toast.hide();
        document.dispatchEvent(new CustomEvent('events:changed'));
      } catch (err) {
        btn.disabled = false;
        if (err.message !== 'unauthorized') showToast(err.message, 'danger');
      }
    });
    toast.show();
  }

  document.querySelectorAll('#flashData span').forEach((s) => {
    const type = { message: 'info', error: 'danger' }[s.dataset.type] || s.dataset.type;
    showToast(s.textContent.trim(), type);
  });

  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  const toggle = document.getElementById('sidebarToggle');
  function closeSidebar() { sidebar && sidebar.classList.remove('open'); backdrop && backdrop.classList.remove('show'); }
  if (toggle) toggle.addEventListener('click', () => { sidebar.classList.add('open'); backdrop.classList.add('show'); });
  if (backdrop) backdrop.addEventListener('click', closeSidebar);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeSidebar(); });

  const COLLAPSE_KEY = 'esimde.sidebarCollapsed';
  const collapseBtn = document.getElementById('sidebarCollapse');
  try { if (localStorage.getItem(COLLAPSE_KEY) === '1') document.body.classList.add('sb-collapsed'); } catch (e) {  }
  if (collapseBtn) {
    collapseBtn.addEventListener('click', () => {
      if (window.matchMedia('(max-width: 991.98px)').matches) { closeSidebar(); return; }
      const collapsed = document.body.classList.toggle('sb-collapsed');
      try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch (e) {  }
      window.dispatchEvent(new Event('resize'));
    });
  }

  document.querySelectorAll('[data-toggle-password]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = document.getElementById(btn.dataset.togglePassword);
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.querySelector('i').className = show ? 'bi bi-eye-slash' : 'bi bi-eye';
      btn.setAttribute('aria-label', show ? 'Құпиясөзді жасыру' : 'Құпиясөзді көрсету');
    });
  });

  function updateStats(stats) {
    if (!stats) return;
    Object.keys(stats).forEach((key) => {
      document.querySelectorAll(`[data-stat="${key}"]`).forEach((el) => { el.textContent = stats[key]; });
    });
  }

  async function toggleComplete(id) {
    try {
      const data = await api(`/api/events/${id}/complete`, { method: 'POST', body: {} });
      document.querySelectorAll(`[data-item="${id}"]`).forEach((item) => applyCompleted(item, data.event));
      updateStats(data.stats);
      showToast(data.message, 'success', 2500);
      document.dispatchEvent(new CustomEvent('events:changed'));
      return data.event;
    } catch (err) {
      if (err.message !== 'unauthorized') showToast(err.message, 'danger');
      return null;
    }
  }

  function applyCompleted(item, ev) {
    item.classList.toggle('is-completed', ev.is_completed);
    item.classList.toggle('is-overdue', ev.is_overdue);
    const rel = item.querySelector('[data-relative]');
    if (rel) rel.textContent = ev.relative;
    const btn = item.querySelector('.complete-btn');
    if (btn) {
      btn.title = ev.is_completed ? 'Белсенді ету' : 'Орындалды деп белгілеу';
      btn.querySelector('i').className = 'bi ' + (ev.is_completed ? 'bi-check-circle-fill' : 'bi-check2-circle');
    }
  }

  function confirmDelete(url, title) {
    document.getElementById('deleteForm').action = url;
    document.getElementById('deleteTitle').textContent = title;
    const onEditPage = /\/events\/\d+\/edit/.test(window.location.pathname);
    document.getElementById('deleteNext').value = onEditPage ? '/events' : window.location.pathname + window.location.search;
    bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteModal')).show();
  }

  let currentEvent = null;

  async function openEvent(id) {
    const modalEl = document.getElementById('eventModal');
    if (!modalEl) return;
    document.getElementById('emLoading').classList.remove('d-none');
    document.getElementById('emBody').classList.add('d-none');
    document.getElementById('emCategory').textContent = '';
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
    try {
      currentEvent = await api(`/api/events/${id}`);
      renderEventModal(currentEvent);
    } catch (err) {
      bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      if (err.message !== 'unauthorized') showToast(err.message, 'danger');
    }
  }

  function renderEventModal(ev) {
    const cat = document.getElementById('emCategory');
    cat.style.setProperty('--cat', ev.category_color);
    cat.innerHTML = `<i class="bi ${ev.category_icon}"></i> `;
    cat.append(ev.category_label);
    document.getElementById('emTitle').textContent = ev.title;
    document.getElementById('emDesc').textContent = ev.description || '';
    document.getElementById('emDate').textContent = ev.date_display;
    document.getElementById('emTime').textContent = ev.event_time;
    document.getElementById('emPriority').innerHTML = `<span class="prio"><i class="bi bi-flag-fill flag-${ev.priority}"></i>${ev.priority_label}</span>`;
    document.getElementById('emRelative').textContent = ev.relative;
    let reminder = ev.reminder_display ? `Келесі: ${ev.reminder_display} · ${ev.reminder_label}` : 'Еске салусыз';
    if (ev.reminder_display && ev.reminder_sent) reminder = `${ev.reminder_label} — барлығы жіберілді`;
    document.getElementById('emReminder').textContent = reminder;
    document.getElementById('emRecurrence').textContent = ev.recurrence_label || 'Қайталанбайды';
    const status = document.getElementById('emStatus');
    status.innerHTML = ev.is_completed ? '<span class="status-pill success"><i class="bi bi-check2"></i> Орындалды</span>'
      : ev.is_overdue ? '<span class="status-pill danger">Мерзімі өткен</span>'
      : '<span class="status-pill info">Жоспарланған</span>';
    document.getElementById('emEdit').href = `/events/${ev.id}/edit`;
    const btn = document.getElementById('emComplete');
    btn.querySelector('span').textContent = ev.is_completed ? 'Белсенді ету' : 'Орындалды';
    btn.classList.toggle('btn-primary', !ev.is_completed);
    btn.classList.toggle('btn-light', ev.is_completed);
    document.getElementById('emLoading').classList.add('d-none');
    document.getElementById('emBody').classList.remove('d-none');
  }

  const emComplete = document.getElementById('emComplete');
  if (emComplete) {
    emComplete.addEventListener('click', async () => {
      if (!currentEvent) return;
      const updated = await toggleComplete(currentEvent.id);
      if (updated) { currentEvent = updated; renderEventModal(updated); }
    });
    document.getElementById('emDelete').addEventListener('click', () => {
      if (!currentEvent) return;
      bootstrap.Modal.getOrCreateInstance(document.getElementById('eventModal')).hide();
      confirmDelete(`/events/${currentEvent.id}/delete`, currentEvent.title);
    });
  }

  document.addEventListener('click', (e) => {
    const title = e.target.closest('[data-event-id]');
    if (title) { e.preventDefault(); openEvent(title.dataset.eventId); return; }
    const complete = e.target.closest('[data-complete]');
    if (complete) { e.preventDefault(); toggleComplete(complete.dataset.complete); return; }
    const del = e.target.closest('[data-delete-url]');
    if (del) { e.preventDefault(); confirmDelete(del.dataset.deleteUrl, del.dataset.deleteTitle); }
  });

  document.querySelectorAll('[data-autosubmit]').forEach((el) => {
    el.addEventListener('change', () => el.form.submit());
  });

  const form = document.getElementById('eventForm');
  if (form) {
    const chips = [...form.querySelectorAll('input[name="reminders"]')];
    const customChip = form.querySelector('#rem-custom');
    const customWrap = document.getElementById('customReminderWrap');
    const custom = form.querySelector('#reminder_custom');
    const date = form.querySelector('#event_date');
    const time = form.querySelector('#event_time');
    const recurrence = form.querySelector('#recurrence');
    const pastWarning = document.getElementById('pastWarning');
    const preview = document.getElementById('reminderPreview');
    const noHint = document.getElementById('noReminderHint');
    const MONTHS = ['қаңтар', 'ақпан', 'наурыз', 'сәуір', 'мамыр', 'маусым', 'шілде', 'тамыз', 'қыркүйек', 'қазан', 'қараша', 'желтоқсан'];
    const pad = (n) => String(n).padStart(2, '0');
    const fmt = (d) => `${d.getDate()} ${MONTHS[d.getMonth()]}, ${pad(d.getHours())}:${pad(d.getMinutes())}`;

    function eventDate() {
      if (!date.value || !time.value) return null;
      const d = new Date(`${date.value}T${time.value}`);
      return isNaN(d) ? null : d;
    }

    function refresh() {
      customWrap.classList.toggle('d-none', !customChip.checked);
      const ev = eventDate();
      const now = new Date();
      pastWarning.classList.toggle('d-none', !(ev && ev < now) || recurrence.value !== 'none');

      const times = [];
      chips.forEach((c) => {
        if (!c.checked) return;
        if (c === customChip) { if (custom.value) times.push(new Date(custom.value)); }
        else if (ev && c.dataset.minutes) times.push(new Date(ev.getTime() - Number(c.dataset.minutes) * 60000));
      });
      const valid = times.filter((t) => !isNaN(t)).sort((a, b) => a - b);
      noHint.classList.toggle('d-none', chips.some((c) => c.checked));
      if (!valid.length) { preview.textContent = ''; return; }
      preview.innerHTML = '<i class="bi bi-bell"></i> Еске салу уақыттары:<ul class="mb-0 mt-1 ps-3"></ul>';
      const list = preview.querySelector('ul');
      valid.forEach((t) => { const li = document.createElement('li'); li.textContent = fmt(t); list.appendChild(li); });
    }

    [custom, date, time, recurrence].forEach((el) => el.addEventListener('input', refresh));
    chips.forEach((c) => c.addEventListener('change', refresh));
    customChip.addEventListener('change', () => {
      if (customChip.checked && !custom.value) {
        const ev = eventDate();
        if (ev) {
          const d = new Date(ev.getTime() - 3600000);
          custom.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        }
      }
      refresh();
    });

    form.querySelectorAll('input[name="category"]').forEach((r) => r.addEventListener('change', () => {
      if (r.checked && r.value === 'birthday' && recurrence.value === 'none') {
        recurrence.value = 'yearly';
        showToast('Туған күн үшін «Жыл сайын» қайталану таңдалды.', 'info', 2500);
      }
    }));
    refresh();

    form.addEventListener('submit', (e) => {
      let ok = true;
      const titleInput = form.querySelector('#title');
      const setInvalid = (el, msg) => {
        el.classList.add('is-invalid');
        const fb = el.parentElement.querySelector('.invalid-feedback');
        if (fb && msg) fb.textContent = msg;
        ok = false;
      };
      form.querySelectorAll('.is-invalid').forEach((el) => el.classList.remove('is-invalid'));
      if (!titleInput.value.trim()) setInvalid(titleInput, 'Оқиға атауын енгізіңіз.');
      if (!date.value) setInvalid(date, 'Күнді таңдаңыз.');
      if (!time.value) setInvalid(time, 'Уақытты таңдаңыз.');
      if (customChip.checked) {
        const ev = eventDate();
        if (!custom.value) setInvalid(custom, 'Еске салу күні мен уақытын көрсетіңіз.');
        else if (ev && new Date(custom.value) > ev) setInvalid(custom, 'Еске салу уақыты оқиға басталғаннан кейін болмауы керек.');
      }
      if (!ok) {
        e.preventDefault();
        showToast('Формада қателер бар. Белгіленген өрістерді тексеріңіз.', 'danger');
        const first = form.querySelector('.is-invalid');
        if (first) first.focus();
      }
    });
  }

  const tgCard = document.getElementById('telegramCard');
  if (tgCard && tgCard.dataset.configured === '1') {
    const el = (id) => document.getElementById(id);
    let pollTimer = null;

    function renderTelegram(s) {
      el('tgTitle').textContent = s.linked ? 'Қосылған' : 'Қосылмаған';
      el('tgDesc').textContent = s.linked
        ? [s.name ? '@' + s.name : '', s.linked_at || ''].filter(Boolean).join(' · ')
        : 'Еске салуларды Telegram ботынан алыңыз — сайт жабық болса да келеді.';
      tgCard.classList.toggle('is-linked', s.linked);
      el('tgLinkBtn').classList.toggle('d-none', s.linked);
      el('tgTestBtn').classList.toggle('d-none', !s.linked);
      el('tgUnlinkBtn').classList.toggle('d-none', !s.linked);
      if (s.linked) el('tgWaiting').classList.add('d-none');
    }

    el('tgLinkBtn').addEventListener('click', async () => {
      try {

        const link = await api('/api/telegram/link', { method: 'POST', body: {} });
        const qr = el('tgQr');
        qr.innerHTML = '';
        if (window.QRCode) new QRCode(qr, { text: link.url, width: 168, height: 168, correctLevel: QRCode.CorrectLevel.M });
        else qr.innerHTML = `<a href="${link.url}" target="_blank" rel="noopener">${link.url}</a>`;
        el('tgAppLink').href = link.app_url;
        el('tgWebLink').href = link.web_url;
        el('tgCommand').textContent = link.command;
        el('tgWaiting').classList.remove('d-none');
        el('tgLinkBtn').classList.add('d-none');
        const started = Date.now();
        clearInterval(pollTimer);
        pollTimer = setInterval(async () => {
          if (Date.now() - started > 15 * 60000) { clearInterval(pollTimer); el('tgWaiting').classList.add('d-none'); return; }
          const s = await api('/api/telegram/status').catch(() => null);
          if (s && s.linked) {
            clearInterval(pollTimer);
            renderTelegram(s);
            showToast('Telegram аккаунты сәтті қосылды!', 'success');
          }
        }, 3000);
      } catch (err) {
        if (err.message !== 'unauthorized') showToast(err.message, 'danger');
      }
    });

    el('tgCopy').addEventListener('click', async () => {
      const text = el('tgCommand').textContent;
      try { await navigator.clipboard.writeText(text); showToast('Команда көшірілді. Оны ботқа жіберіңіз.', 'success', 2500); }
      catch (e) { window.prompt('Команданы көшіріңіз:', text); }
    });

    el('tgTestBtn').addEventListener('click', async () => {
      try { showToast((await api('/api/telegram/test', { method: 'POST', body: {} })).message, 'success'); }
      catch (err) { if (err.message !== 'unauthorized') showToast(err.message, 'danger'); }
    });

    el('tgUnlinkBtn').addEventListener('click', async () => {
      if (!window.confirm('Telegram аккаунтын ажыратасыз ба?')) return;
      try {
        showToast((await api('/api/telegram/unlink', { method: 'POST', body: {} })).message, 'info');
        renderTelegram(await api('/api/telegram/status'));
      } catch (err) { if (err.message !== 'unauthorized') showToast(err.message, 'danger'); }
    });
  }

  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {  });
    });
  }

  const eventParam = new URLSearchParams(window.location.search).get('event');
  if (eventParam && /^\d+$/.test(eventParam) && document.getElementById('eventModal')) {
    openEvent(eventParam);
    history.replaceState(null, '', window.location.pathname);
  }

  window.App = { api, showToast, showReminderToast, openEvent, updateStats };
})();
