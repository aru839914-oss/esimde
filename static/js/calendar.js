(function () {
  'use strict';
  const el = document.getElementById('calendar');
  if (!el || !window.FullCalendar) {
    if (el) el.innerHTML = '<div class="empty-mini text-danger p-4"><i class="bi bi-wifi-off"></i> Күнтізбе кітапханасы жүктелмеді. Интернет байланысын тексеріңіз.</div>';
    return;
  }
  const loading = document.getElementById('calendarLoading');
  const isMobile = window.matchMedia('(max-width: 767.98px)').matches;
  const pad = (n) => String(n).padStart(2, '0');

  const MONTHS = ['қаңтар', 'ақпан', 'наурыз', 'сәуір', 'мамыр', 'маусым', 'шілде', 'тамыз', 'қыркүйек', 'қазан', 'қараша', 'желтоқсан'];
  const DAYS_SHORT = ['Жс', 'Дс', 'Сс', 'Ср', 'Бс', 'Жм', 'Сб'];
  const DAYS_FULL = ['Жексенбі', 'Дүйсенбі', 'Сейсенбі', 'Сәрсенбі', 'Бейсенбі', 'Жұма', 'Сенбі'];
  const PRIORITY = { high: 'Жоғары', medium: 'Орташа', low: 'Төмен' };
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const short = (m) => MONTHS[m].slice(0, 3);
  const esc = (s) => { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; };

  const filters = { category: '', priority: ['high', 'medium', 'low'], completed: true };

  function rangeText(view) {
    const s = view.currentStart;
    const e = new Date(view.currentEnd.getTime() - 86400000);
    if (view.type === 'timeGridDay') return `${s.getDate()} ${MONTHS[s.getMonth()]} ${s.getFullYear()}`;
    if (view.type === 'multiMonthYear') return `${s.getFullYear()} жыл`;
    if (view.type === 'dayGridMonth') return `1 ${short(s.getMonth())} – ${e.getDate()} ${short(e.getMonth())} ${e.getFullYear()}`;
    return `${s.getDate()} ${short(s.getMonth())} – ${e.getDate()} ${short(e.getMonth())} ${e.getFullYear()}`;
  }

  function eventCard(arg) {
    const p = arg.event.extendedProps;
    const isMonth = arg.view.type === 'dayGridMonth' || arg.view.type === 'multiMonthYear';
    if (isMonth) {
      return { html: `<div class="evm"><span class="evm-time">${esc(p.event_time)}</span><span class="evm-title">${esc(p.title)}</span></div>` };
    }
    return {
      html: `<div class="evc">
        <div class="evc-title">${esc(p.title)}</div>
        <div class="evc-line"><i class="bi bi-clock"></i>${esc(p.time_range)}${p.recurrence_label ? ' <i class="bi bi-arrow-repeat ms-1" title="' + esc(p.recurrence_label) + '"></i>' : ''}</div>
        <div class="evc-line"><i class="bi bi-flag-fill flag-${esc(p.priority)}"></i>${PRIORITY[p.priority] || ''}
          ${p.is_completed ? '<span class="evc-done"><i class="bi bi-check2"></i> Орындалды</span>' : ''}</div>
      </div>`,
    };
  }

  const calendar = new FullCalendar.Calendar(el, {
    initialView: isMobile ? 'timeGridDay' : 'timeGridWeek',
    headerToolbar: false,
    firstDay: 1,
    height: isMobile ? 'auto' : 760,
    expandRows: false,
    nowIndicator: true,
    allDaySlot: false,
    dayMaxEvents: 3,
    eventDisplay: 'block',
    slotDuration: '00:30:00',
    slotLabelInterval: '01:00',
    slotMinTime: '06:00:00',
    scrollTime: '07:30:00',
    eventMinHeight: 40,
    slotEventOverlap: false,
    moreLinkText: (n) => `+${n} тағы`,
    noEventsText: 'Оқиғалар жоқ',
    eventTimeFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
    slotLabelFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
    multiMonthMaxColumns: 3,
    events: (info, success, failure) => {
      const params = new URLSearchParams({ start: info.startStr, end: info.endStr });
      if (filters.category) params.set('category', filters.category);
      if (filters.priority.length < 3) params.set('priority', filters.priority.join(',') || 'none');
      if (!filters.completed) params.set('completed', '0');
      fetch(`${el.dataset.feed}?${params}`, { headers: { Accept: 'application/json' } })
        .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
        .then(success)
        .catch(() => { failure(new Error('feed')); App.showToast('Оқиғаларды жүктеу мүмкін болмады.', 'danger'); });
    },
    loading: (isLoading) => loading.classList.toggle('d-none', !isLoading),
    eventContent: eventCard,
    eventDidMount: (info) => {
      const p = info.event.extendedProps;
      info.el.style.setProperty('--ev', p.category_color);
      info.el.title = `${p.title} · ${p.category_label} · ${PRIORITY[p.priority]}`;
    },
    dayHeaderContent: (arg) => {
      const d = arg.date;
      if (arg.view.type === 'dayGridMonth') return DAYS_SHORT[d.getDay()];
      if (arg.view.type === 'multiMonthYear') return DAYS_SHORT[d.getDay()];
      return { html: `<div class="dh-name">${DAYS_FULL[d.getDay()]}</div><div class="dh-date">${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}</div>` };
    },
    multiMonthTitleFormat: (arg) => cap(MONTHS[arg.date.month]),
    eventClick: (info) => { info.jsEvent.preventDefault(); App.openEvent(info.event.extendedProps.id); },
    dateClick: (info) => {

      const d = info.date;
      const params = new URLSearchParams({ date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, return_to: 'calendar' });
      if (!info.allDay) params.set('time', `${pad(d.getHours())}:${pad(d.getMinutes())}`);
      if (filters.category) params.set('category', filters.category);
      window.location.href = `${el.dataset.addUrl}?${params}`;
    },
    datesSet: (info) => {
      const cur = calendar.getDate();
      document.getElementById('calTitle').textContent = info.view.type === 'multiMonthYear'
        ? `${cur.getFullYear()}` : `${cap(MONTHS[cur.getMonth()])} ${cur.getFullYear()}`;
      document.getElementById('calRange').textContent = rangeText(info.view);
      document.querySelectorAll('#viewSwitch button').forEach((b) => b.classList.toggle('active', b.dataset.view === info.view.type));
    },
  });
  calendar.render();

  document.getElementById('calPrev').addEventListener('click', () => calendar.prev());
  document.getElementById('calNext').addEventListener('click', () => calendar.next());
  document.getElementById('calToday').addEventListener('click', () => calendar.today());
  document.querySelectorAll('#viewSwitch button').forEach((b) => b.addEventListener('click', () => calendar.changeView(b.dataset.view)));

  document.querySelectorAll('#categoryTabs button').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('#categoryTabs button').forEach((t) => t.classList.toggle('active', t === tab));
      filters.category = tab.dataset.category;
      calendar.refetchEvents();
    });
  });

  const filterBox = document.getElementById('calendarFilter');
  filterBox.addEventListener('change', () => {
    filters.priority = [...filterBox.querySelectorAll('input[name=priority]:checked')].map((i) => i.value);
    filters.completed = filterBox.querySelector('input[name=completed]').checked;
    const active = (3 - filters.priority.length) + (filters.completed ? 0 : 1);
    const badge = document.getElementById('filterCount');
    badge.textContent = active;
    badge.classList.toggle('d-none', active === 0);
    calendar.refetchEvents();
  });

  document.addEventListener('events:changed', () => calendar.refetchEvents());
  document.addEventListener('reminders:updated', () => calendar.refetchEvents());
})();
