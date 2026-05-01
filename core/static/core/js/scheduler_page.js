(function () {
    const boot = window.SCHED_BOOT || {};
    const urls = boot.urls || {};
    const csrf = boot.csrf || '';

    const state = {
        processes: Array.isArray(boot.processes) ? boot.processes : [],
        agents: Array.isArray(boot.agents) ? boot.agents : [],
        items: [],
    };

    const el = {
        form: document.getElementById('sch-form'),
        id: document.getElementById('sch-id'),
        name: document.getElementById('sch-name'),
        process: document.getElementById('sch-process'),
        agent: document.getElementById('sch-agent'),
        frequency: document.getElementById('sch-frequency'),
        interval: document.getElementById('sch-interval'),
        time: document.getElementById('sch-time'),
        weekdaysWrap: document.getElementById('sch-wrap-weekdays'),
        weekdays: document.getElementById('sch-weekdays'),
        domWrap: document.getElementById('sch-wrap-dom'),
        dom: document.getElementById('sch-dom'),
        timeWrap: document.getElementById('sch-wrap-time'),
        intervalWrap: document.getElementById('sch-wrap-interval'),
        priority: document.getElementById('sch-priority'),
        note: document.getElementById('sch-note'),
        payload: document.getElementById('sch-payload'),
        maintStart: document.getElementById('sch-maint-start'),
        maintEnd: document.getElementById('sch-maint-end'),
        preventOverlap: document.getElementById('sch-prevent-overlap'),
        overlapBuffer: document.getElementById('sch-overlap-buffer'),
        enabled: document.getElementById('sch-enabled'),
        save: document.getElementById('sch-save'),
        reset: document.getElementById('sch-reset'),
        refresh: document.getElementById('sch-refresh'),
        runDue: document.getElementById('sch-run-due'),
        body: document.getElementById('sch-body'),
        jobsBody: document.getElementById('sch-jobs-body'),
        total: document.getElementById('sch-total'),
        active: document.getElementById('sch-active'),
        due: document.getElementById('sch-due'),
        timeline: document.getElementById('sch-timeline'),
    };

    function toast(msg, type) {
        if (typeof window.showToast === 'function') {
            window.showToast(msg, type || 'info');
        }
    }

    function esc(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function fmtDate(iso) {
        if (!iso) return '-';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '-';
        return d.toLocaleString('tr-TR', { hour12: false });
    }

    async function getJson(url) {
        const r = await fetch(url, { headers: { Accept: 'application/json' } });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) throw new Error(data.error || ('HTTP ' + r.status));
        return data;
    }

    async function postJson(url, body) {
        const r = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrf,
            },
            body: JSON.stringify(body || {}),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) throw new Error(data.error || ('HTTP ' + r.status));
        return data;
    }

    function syncFrequencyUi() {
        if (!el.frequency || !el.intervalWrap || !el.timeWrap || !el.weekdaysWrap || !el.domWrap) return;
        const f = el.frequency.value;
        el.intervalWrap.style.display = f === 'interval' ? '' : 'none';
        el.timeWrap.style.display = f === 'daily' || f === 'weekly' || f === 'monthly' ? '' : 'none';
        el.weekdaysWrap.style.display = f === 'weekly' ? '' : 'none';
        el.domWrap.style.display = f === 'monthly' ? '' : 'none';
    }

    function resetForm() {
        el.id.value = '';
        el.name.value = '';
        el.process.value = '';
        el.agent.value = '';
        el.frequency.value = 'interval';
        el.interval.value = '15';
        el.time.value = '09:00';
        el.dom.value = '1';
        el.priority.value = '300';
        el.note.value = '';
        el.payload.value = '';
        if (el.maintStart) el.maintStart.value = '';
        if (el.maintEnd) el.maintEnd.value = '';
        if (el.preventOverlap) el.preventOverlap.checked = true;
        if (el.overlapBuffer) el.overlapBuffer.value = '10';
        el.enabled.checked = true;
        el.weekdays.querySelectorAll('input[type="checkbox"]').forEach((x) => { x.checked = false; });
        syncFrequencyUi();
    }

    function collectWeekdays() {
        return Array.from(el.weekdays.querySelectorAll('input[type="checkbox"]:checked')).map((x) => x.value).join(',');
    }

    function formToPayload() {
        let payloadObj = {};
        const rawPayload = (el.payload.value || '').trim();
        if (rawPayload) {
            try {
                const parsed = JSON.parse(rawPayload);
                if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                    payloadObj = parsed;
                } else {
                    throw new Error('Ek payload JSON object olmalı.');
                }
            } catch (err) {
                throw new Error('Ek payload JSON hatalı: ' + err.message);
            }
        }

        return {
            id: el.id.value ? Number(el.id.value) : null,
            name: el.name.value.trim(),
            sap_process_id: Number(el.process.value || 0),
            target_agent_id: el.agent.value ? Number(el.agent.value) : null,
            frequency: el.frequency.value,
            interval_minutes: Number(el.interval.value || 0),
            run_time: el.time.value || '',
            weekdays: collectWeekdays(),
            day_of_month: Number(el.dom.value || 0),
            priority: Number(el.priority.value || 300),
            note: el.note.value.trim(),
            payload: payloadObj,
            maintenance_window_start: el.maintStart ? (el.maintStart.value || '') : '',
            maintenance_window_end: el.maintEnd ? (el.maintEnd.value || '') : '',
            prevent_overlap: el.preventOverlap ? !!el.preventOverlap.checked : true,
            overlap_buffer_minutes: el.overlapBuffer ? Number(el.overlapBuffer.value || 10) : 10,
            enabled: !!el.enabled.checked,
        };
    }

    function fillForm(item) {
        el.id.value = item.id || '';
        el.name.value = item.name || '';
        el.process.value = item.sap_process_id ? String(item.sap_process_id) : '';
        el.agent.value = item.target_agent_id ? String(item.target_agent_id) : '';
        el.frequency.value = item.frequency || 'daily';
        el.interval.value = item.interval_minutes || 15;
        el.time.value = item.run_time || '09:00';
        el.dom.value = item.day_of_month || 1;
        el.priority.value = item.priority || 300;
        el.note.value = item.note || '';
        el.payload.value = item.payload && Object.keys(item.payload).length ? JSON.stringify(item.payload, null, 2) : '';
        if (el.maintStart) el.maintStart.value = item.maintenance_window_start || '';
        if (el.maintEnd) el.maintEnd.value = item.maintenance_window_end || '';
        if (el.preventOverlap) el.preventOverlap.checked = item.prevent_overlap !== false;
        if (el.overlapBuffer) el.overlapBuffer.value = item.overlap_buffer_minutes || 10;
        el.enabled.checked = !!item.enabled;

        const wk = new Set(String(item.weekdays || '').split(',').map((x) => x.trim()).filter(Boolean));
        el.weekdays.querySelectorAll('input[type="checkbox"]').forEach((x) => {
            x.checked = wk.has(x.value);
        });

        syncFrequencyUi();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function renderOptions() {
        el.process.innerHTML = ['<option value="">Süreç seçin</option>'].concat(
            state.processes.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`)
        ).join('');

        el.agent.innerHTML = ['<option value="">Müsait robot</option>'].concat(
            state.agents.map((a) => `<option value="${a.id}">${esc(a.code)} - ${esc(a.name)}</option>`)
        ).join('');
    }

    function renderSchedules(items) {
        if (!items.length) {
            el.body.innerHTML = '<tr><td colspan="8" class="empty-cell">Plan bulunamadı.</td></tr>';
            return;
        }

        el.body.innerHTML = items.map((x) => `
            <tr>
                <td>${esc(x.name)}</td>
                <td>${esc(x.sap_process_name || '-')}</td>
                <td>${esc(x.target_agent_code || 'any')}</td>
                <td>${esc(x.frequency)}</td>
                <td>${x.enabled ? 'Evet' : 'Hayır'}</td>
                <td>${fmtDate(x.last_run_at)}</td>
                <td>${fmtDate(x.next_run_at)}</td>
                <td>
                    <div class="action-btns">
                        <button class="icon-btn" type="button" data-act="edit" data-id="${x.id}" title="Düzenle"><i class="fas fa-pen"></i></button>
                        <button class="icon-btn" type="button" data-act="toggle" data-id="${x.id}" title="Aktif/Pasif"><i class="fas fa-power-off"></i></button>
                        <button class="icon-btn" type="button" data-act="run" data-id="${x.id}" title="Şimdi çalıştır"><i class="fas fa-play"></i></button>
                        <button class="icon-btn delete" type="button" data-act="delete" data-id="${x.id}" title="Sil"><i class="fas fa-trash"></i></button>
                    </div>
                </td>
            </tr>
        `).join('');

        el.body.querySelectorAll('[data-act]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const id = Number(btn.getAttribute('data-id') || 0);
                const action = btn.getAttribute('data-act');
                const item = state.items.find((s) => s.id === id);
                if (!item) return;

                try {
                    if (action === 'edit') {
                        fillForm(item);
                        return;
                    }
                    if (action === 'toggle') {
                        await postJson(urls.toggle, { id, enabled: !item.enabled });
                        toast('Plan durumu güncellendi.', 'success');
                    }
                    if (action === 'run') {
                        const r = await postJson(urls.runNow, { id });
                        if (r && r.warning === 'agent_offline') {
                            toast('⚠ ' + r.warning_msg, 'warning');
                        } else {
                            toast('Plan hemen kuyruğa alındı.', 'success');
                        }
                    }
                    if (action === 'delete') {
                        if (!confirm('Plan silinsin mi?')) return;
                        await postJson(urls.delete, { id });
                        toast('Plan silindi.', 'success');
                    }
                    await refreshList();
                } catch (err) {
                    toast(err.message || 'İşlem hatası', 'error');
                }
            });
        });
    }

    function renderJobs(rows) {
        if (!rows.length) {
            el.jobsBody.innerHTML = '<tr><td colspan="7" class="empty-cell">Henüz scheduler işi yok.</td></tr>';
            return;
        }
        el.jobsBody.innerHTML = rows.map((j) => `
            <tr>
                <td>#${j.job_id}</td>
                <td>${esc(j.schedule_name || '-')}</td>
                <td>${esc(j.sap_process_name || '-')}</td>
                <td>${esc(j.target_agent_code || 'any')}</td>
                <td>${esc(j.status || '-')}</td>
                <td>${esc(j.message || '-')}</td>
                <td>${fmtDate(j.created_at)}</td>
            </tr>
        `).join('');
    }

    // ── 7 günlük takvim ──────────────────────────────────────────────
    function _parseTime(timeStr) {
        // '09:00' → {h, m}
        const parts = String(timeStr || '').split(':');
        return { h: parseInt(parts[0] || '0', 10), m: parseInt(parts[1] || '0', 10) };
    }

    function _buildOccurrences(items) {
        const now = new Date();
        const endDate = new Date(now.getTime() + 7 * 86400000);
        const occ = []; // {date, item}

        (items || []).forEach((item) => {
            if (!item.enabled) return;
            const freq = item.frequency;

            if (freq === 'daily' && item.run_time) {
                const { h, m } = _parseTime(item.run_time);
                for (let i = 0; i < 7; i++) {
                    const d = new Date(now);
                    d.setDate(d.getDate() + i);
                    d.setHours(h, m, 0, 0);
                    if (d > now) occ.push({ date: d, item });
                }
                return;
            }

            if (freq === 'weekly' && item.run_time && item.weekdays) {
                const { h, m } = _parseTime(item.run_time);
                // weekdays: "0,1,4" → Mon=0 .. Sun=6  (JS: Sun=0 Mon=1 ... Sat=6)
                const wdSet = new Set(
                    String(item.weekdays).split(',').map((x) => {
                        const v = parseInt(x.trim(), 10);
                        // convert Mon=0 to JS Sun=0 convention: Mon=1 ... Sun=0
                        return (v + 1) % 7;
                    })
                );
                for (let i = 0; i < 7; i++) {
                    const d = new Date(now);
                    d.setDate(d.getDate() + i);
                    d.setHours(h, m, 0, 0);
                    if (wdSet.has(d.getDay()) && d > now) occ.push({ date: d, item });
                }
                return;
            }

            if (freq === 'interval' && item.interval_minutes > 0) {
                let d = item.next_run_at ? new Date(item.next_run_at) : new Date(now.getTime() + item.interval_minutes * 60000);
                const step = item.interval_minutes * 60000;
                let count = 0;
                while (d < endDate && count < 8) {
                    if (d > now) { occ.push({ date: new Date(d), item }); count++; }
                    d = new Date(d.getTime() + step);
                }
                return;
            }

            // monthly / fallback – just use next_run_at
            if (item.next_run_at) {
                const d = new Date(item.next_run_at);
                if (d > now && d < endDate) occ.push({ date: d, item });
            }
        });

        return occ.sort((a, b) => a.date - b.date);
    }

    function renderTimeline(items) {
        if (!el.timeline) return;

        const activeItems = (items || []).filter((x) => x.enabled);
        if (!activeItems.length) {
            el.timeline.className = 'sch-timeline-empty';
            el.timeline.textContent = 'Aktif plan bulunmuyor.';
            return;
        }

        const occs = _buildOccurrences(activeItems);
        const now = new Date();
        const TR_DAYS = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];
        const TR_MONTHS = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];

        // Build 7 day buckets
        const days = [];
        for (let i = 0; i < 7; i++) {
            const d = new Date(now);
            d.setDate(d.getDate() + i);
            d.setHours(0, 0, 0, 0);
            days.push({ date: d, chips: [] });
        }

        occs.forEach(({ date, item }) => {
            const dayStart = new Date(date);
            dayStart.setHours(0, 0, 0, 0);
            const idx = days.findIndex((d) => d.date.getTime() === dayStart.getTime());
            if (idx >= 0) days[idx].chips.push({ date, item });
        });

        const cols = days.map((day, idx) => {
            const isToday = idx === 0;
            const dayName = isToday ? 'Bugün' : TR_DAYS[day.date.getDay()];
            const dayNum = `${day.date.getDate()} ${TR_MONTHS[day.date.getMonth()]}`;
            const MAX_CHIPS = 5;
            const shown = day.chips.slice(0, MAX_CHIPS);
            const extra = day.chips.length - shown.length;

            const chipsHtml = shown.map(({ date, item }) => {
                const hh = String(date.getHours()).padStart(2, '0');
                const mm = String(date.getMinutes()).padStart(2, '0');
                const freq = item.frequency || 'daily';
                return `<div class="sch-cal-chip ${esc(freq)}" title="${esc(item.name)} · ${esc(item.sap_process_name || '')}">
                    <span class="sch-chip-time">${hh}:${mm}</span>
                    <span class="sch-chip-name">${esc(item.name)}</span>
                </div>`;
            }).join('');

            const emptyHtml = !day.chips.length ? '<div class="sch-cal-empty">—</div>' : '';
            const moreHtml = extra > 0 ? `<div class="sch-cal-more">+${extra} daha</div>` : '';

            return `<div class="sch-cal-col${isToday ? ' sch-cal-today' : ''}">
                <div class="sch-cal-day-head">
                    <div class="sch-cal-day-name">${dayName}</div>
                    <div class="sch-cal-day-num">${dayNum}</div>
                </div>
                <div class="sch-cal-day-body">${chipsHtml}${emptyHtml}${moreHtml}</div>
            </div>`;
        }).join('');

        el.timeline.className = 'sch-cal-grid';
        el.timeline.innerHTML = cols;
    }

    async function refreshList() {
        const data = await getJson(urls.list);
        state.items = Array.isArray(data.items) ? data.items : [];
        renderSchedules(state.items);
        renderJobs(Array.isArray(data.recent_jobs) ? data.recent_jobs : []);
        renderTimeline(state.items);

        const stats = data.stats || {};
        el.total.textContent = String(stats.total || 0);
        el.active.textContent = String(stats.active || 0);
        el.due.textContent = String(stats.due_now || 0);

        // Agent online/offline göstergesi
        const agentSt = data.agent_status || {};
        let agentBadge = document.getElementById('sch-agent-status');
        if (!agentBadge) {
            agentBadge = document.createElement('div');
            agentBadge.id = 'sch-agent-status';
            agentBadge.style.cssText = 'font-size:12px;padding:6px 12px;border-radius:8px;border:1px solid;margin-bottom:10px;';
            const statsRow = document.querySelector('.sch-stats-row');
            if (statsRow) statsRow.parentNode.insertBefore(agentBadge, statsRow);
        }
        if (agentSt.any_online) {
            agentBadge.style.background = 'rgba(159,255,110,.08)';
            agentBadge.style.borderColor = 'rgba(159,255,110,.3)';
            agentBadge.style.color = '#9fff6e';
            agentBadge.innerHTML = '<i class="fas fa-circle" style="font-size:8px;margin-right:6px;"></i>Robot agent çevrimiçi — işler anında çalışacak.';
        } else {
            agentBadge.style.background = 'rgba(255,100,80,.08)';
            agentBadge.style.borderColor = 'rgba(255,100,80,.3)';
            agentBadge.style.color = '#ff7b6b';
            agentBadge.innerHTML = '<i class="fas fa-circle-exclamation" style="margin-right:6px;"></i>Robot agent <b>çevrimdışı</b> — tetiklediğiniz işler kuyruğa alınır, agent başladığında çalışır.';
        }
    }

    async function saveSchedule() {
        const payload = formToPayload();
        await postJson(urls.save, payload);
        toast('Plan kaydedildi.', 'success');
        resetForm();
        await refreshList();
    }

    function bind() {
        if (!el.form) return;
        el.frequency.addEventListener('change', syncFrequencyUi);

        el.reset.addEventListener('click', resetForm);

        el.refresh.addEventListener('click', async () => {
            try {
                await refreshList();
                toast('Scheduler verileri yenilendi.', 'info');
            } catch (err) {
                toast(err.message || 'Yenileme hatası', 'error');
            }
        });

        el.runDue.addEventListener('click', async () => {
            try {
                const resp = await postJson(urls.dispatchDue, {});
                toast(`${resp.count || 0} plan tetiklendi.`, 'success');
                await refreshList();
            } catch (err) {
                toast(err.message || 'Tetikleme hatası', 'error');
            }
        });

        el.form.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            el.save.disabled = true;
            try {
                await saveSchedule();
            } catch (err) {
                toast(err.message || 'Kaydetme hatası', 'error');
            } finally {
                el.save.disabled = false;
            }
        });
    }

    async function init() {
        if (!el.form) return;
        renderOptions();
        resetForm();
        bind();
        await refreshList();
    }

    document.addEventListener('DOMContentLoaded', init);
})();
