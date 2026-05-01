(function () {
    const TABLE_SELECTOR = '.container table:not([data-table-enhance="off"])';
    const PAGE_SIZES = [10, 25, 50, 100];

    const toSafeNumber = (value, fallback) => {
        const n = parseInt(String(value || ''), 10);
        return Number.isFinite(n) ? n : fallback;
    };

    const makeStorageKey = (table, suffix) => {
        const idPart = table.id ? `#${table.id}` : '';
        const clsPart = (table.className || '').trim().replace(/\s+/g, '.');
        const indexPart = Array.from(document.querySelectorAll(TABLE_SELECTOR)).indexOf(table);
        return `table-enhancer::${window.location.pathname}::${idPart}::${clsPart}::${indexPart}::${suffix}`;
    };

    const readJson = (key, fallback) => {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (_) {
            return fallback;
        }
    };

    const writeJson = (key, value) => {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch (_) {
            // localStorage kapalıysa sessizce geç.
        }
    };

    const removeStorage = (key) => {
        try {
            localStorage.removeItem(key);
        } catch (_) {
            // localStorage kapalıysa sessizce geç.
        }
    };

    const toast = (message, type) => {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type || 'info');
        }
    };

    const getDefaults = (table) => {
        const allTables = Array.from(document.querySelectorAll(TABLE_SELECTOR));
        const tableIndex = allTables.indexOf(table);
        const tableKey = table.dataset.tableKey || table.id || `table-${tableIndex}`;
        const globalDefaults = window.TABLE_ENHANCER_DEFAULTS || {};
        const pageDefaults = globalDefaults[window.location.pathname] || {};
        const tableDefaults = ((pageDefaults.tables || {})[tableKey]) || {};

        const readNum = (...values) => {
            for (const v of values) {
                const n = toSafeNumber(v, -1);
                if (n > 0) return n;
            }
            return 25;
        };

        const readOptionalIndex = (...values) => {
            for (const v of values) {
                const n = toSafeNumber(v, -1);
                if (n >= 0) return n;
            }
            return -1;
        };

        const directionCandidate = String(
            table.dataset.tableDefaultSortDirection ||
            (tableDefaults.sort || {}).direction ||
            (pageDefaults.sort || {}).direction ||
            'asc'
        ).toLowerCase();

        return {
            pageSize: readNum(table.dataset.tableDefaultPageSize, tableDefaults.pageSize, pageDefaults.pageSize, 25),
            sort: {
                columnKey:
                    table.dataset.tableDefaultSortCol ||
                    (tableDefaults.sort || {}).columnKey ||
                    (pageDefaults.sort || {}).columnKey ||
                    '',
                columnIndex: readOptionalIndex(
                    table.dataset.tableDefaultSortIndex,
                    (tableDefaults.sort || {}).columnIndex,
                    (pageDefaults.sort || {}).columnIndex
                ),
                direction: directionCandidate === 'desc' ? 'desc' : 'asc',
            },
            tableKey,
        };
    };

    const collectRows = (table) => {
        const expected = table.querySelectorAll('thead th').length;
        return Array.from(table.querySelectorAll('tbody tr')).filter((row) => row.children.length === expected);
    };

    const ensureSelectionColumn = (table) => {
        const hasSapSelection = !!table.querySelector('.sap-row-chk');
        if (hasSapSelection) {
            return { mode: 'sap', selector: '.sap-row-chk', headerToggle: table.querySelector('#select-all-chk') || null };
        }

        const headRow = table.querySelector('thead tr');
        if (!headRow) return { mode: 'none', selector: null, headerToggle: null };

        const alreadyExists = !!headRow.querySelector('th[data-te-select-col="1"]');
        if (!alreadyExists) {
            const th = document.createElement('th');
            th.dataset.teSelectCol = '1';
            th.dataset.colKey = '__select';
            th.dataset.colMinWidth = '42';
            th.className = 'te-select-col';

            const allChk = document.createElement('input');
            allChk.type = 'checkbox';
            allChk.className = 'te-select-all';
            allChk.setAttribute('aria-label', 'Tum satirlari sec');
            th.appendChild(allChk);
            headRow.insertBefore(th, headRow.firstChild);

            Array.from(table.querySelectorAll('tbody tr')).forEach((row) => {
                const td = document.createElement('td');
                td.className = 'te-select-cell';
                const rowChk = document.createElement('input');
                rowChk.type = 'checkbox';
                rowChk.className = 'te-row-select';
                rowChk.setAttribute('aria-label', 'Satiri sec');
                td.appendChild(rowChk);
                row.insertBefore(td, row.firstChild);
            });
        }

        return {
            mode: 'built-in',
            selector: '.te-row-select',
            headerToggle: headRow.querySelector('th[data-te-select-col="1"] .te-select-all'),
        };
    };

    const ensureColKeys = (table) => {
        const headers = Array.from(table.querySelectorAll('thead th'));
        headers.forEach((th, idx) => {
            if (!th.dataset.colKey) {
                const base = (th.textContent || `col-${idx}`).trim().toLowerCase().replace(/\s+/g, '-');
                th.dataset.colKey = `${base || 'col'}-${idx}`;
            }
            if (!th.dataset.colMinWidth) {
                th.dataset.colMinWidth = th.dataset.teSelectCol === '1' ? '42' : '64';
            }
        });
    };

    const isSelectionHeader = (th) => {
        if (!th) return false;
        if (th.dataset.teSelectCol === '1') return true;
        const key = String(th.dataset.colKey || '').toLowerCase();
        if (key === '__select' || key === 'chk' || key === 'check') return true;
        return !!th.querySelector('input[type="checkbox"]');
    };

    const getRowCheckbox = (row, state) => {
        if (!row || !state.selectionSelector) return null;
        return row.querySelector(state.selectionSelector);
    };

    const syncBuiltInSelectionRows = (state) => {
        if (state.selectionSelector !== '.te-row-select') return;
        const table = state.table;
        const headCount = table.querySelectorAll('thead th').length;
        const bodyRows = Array.from(table.querySelectorAll('tbody tr'));

        bodyRows.forEach((row) => {
            if (row.querySelector('.te-row-select')) return;
            if (row.children.length === headCount - 1) {
                const td = document.createElement('td');
                td.className = 'te-select-cell';
                const rowChk = document.createElement('input');
                rowChk.type = 'checkbox';
                rowChk.className = 'te-row-select';
                rowChk.setAttribute('aria-label', 'Satiri sec');
                rowChk.addEventListener('change', () => applyFilterAndPagination(table, state));
                td.appendChild(rowChk);
                row.insertBefore(td, row.firstChild);
            }
        });
    };

    const moveColumn = (table, fromIndex, toIndex) => {
        if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return;
        const headRow = table.querySelector('thead tr');
        if (!headRow) return;

        const headers = Array.from(headRow.children);
        const movingHead = headers[fromIndex];
        const targetHead = headers[toIndex];
        if (!movingHead || !targetHead) return;

        if (fromIndex < toIndex) {
            headRow.insertBefore(movingHead, targetHead.nextSibling);
        } else {
            headRow.insertBefore(movingHead, targetHead);
        }

        collectRows(table).forEach((row) => {
            const cells = Array.from(row.children);
            const moving = cells[fromIndex];
            const target = cells[toIndex];
            if (!moving || !target) return;
            if (fromIndex < toIndex) {
                row.insertBefore(moving, target.nextSibling);
            } else {
                row.insertBefore(moving, target);
            }
        });
    };

    const saveOrder = (table) => {
        const key = makeStorageKey(table, 'order');
        const headers = Array.from(table.querySelectorAll('thead th')).map((th) => th.dataset.colKey || '');
        writeJson(key, headers);
    };

    const restoreOrder = (table) => {
        const key = makeStorageKey(table, 'order');
        const saved = readJson(key, []);
        if (!Array.isArray(saved) || saved.length === 0) return;
        const headRow = table.querySelector('thead tr');
        if (!headRow) return;

        saved.forEach((colKey, targetIndex) => {
            const headers = Array.from(headRow.children);
            const fromIndex = headers.findIndex((th) => (th.dataset.colKey || '') === colKey);
            if (fromIndex >= 0 && fromIndex !== targetIndex) {
                moveColumn(table, fromIndex, targetIndex);
            }
        });
    };

    const saveWidths = (table) => {
        const key = makeStorageKey(table, 'widths');
        const payload = {};
        Array.from(table.querySelectorAll('thead th')).forEach((th) => {
            const colKey = th.dataset.colKey || '';
            if (!colKey || th.dataset.teSelectCol === '1') return;
            const width = toSafeNumber(th.style.width, 0);
            if (width > 0) payload[colKey] = width;
        });
        writeJson(key, payload);
    };

    const restoreWidths = (table) => {
        const key = makeStorageKey(table, 'widths');
        const payload = readJson(key, {});
        if (!payload || typeof payload !== 'object') return;

        Array.from(table.querySelectorAll('thead th')).forEach((th) => {
            const colKey = th.dataset.colKey || '';
            if (th.dataset.teSelectCol === '1') return;
            const width = payload[colKey];
            if (typeof width !== 'number' || width < 48) return;
            th.style.width = `${width}px`;
        });
    };

    const initColumnDnD = (table) => {
        const headRow = table.querySelector('thead tr');
        if (!headRow) return;

        let dragIndex = -1;
        Array.from(headRow.children).forEach((th) => {
            if (isSelectionHeader(th)) return;
            th.draggable = true;
            th.classList.add('te-head-draggable');

            th.addEventListener('dragstart', () => {
                dragIndex = Array.from(headRow.children).indexOf(th);
            });

            th.addEventListener('dragover', (event) => event.preventDefault());

            th.addEventListener('drop', (event) => {
                event.preventDefault();
                const toIndex = Array.from(headRow.children).indexOf(th);
                moveColumn(table, dragIndex, toIndex);
                saveOrder(table);
            });
        });
    };

    const initColumnResize = (table) => {
        const headers = Array.from(table.querySelectorAll('thead th'));
        headers.forEach((th) => {
            if (th.querySelector('.te-col-resizer') || isSelectionHeader(th)) return;

            const handle = document.createElement('span');
            handle.className = 'te-col-resizer';
            th.appendChild(handle);

            let startX = 0;
            let startWidth = 0;

            const onMove = (event) => {
                const minW = toSafeNumber(th.dataset.colMinWidth, 64);
                const delta = event.clientX - startX;
                th.style.width = `${Math.max(minW, startWidth + delta)}px`;
            };

            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                saveWidths(table);
            };

            handle.addEventListener('mousedown', (event) => {
                event.preventDefault();
                event.stopPropagation();
                startX = event.clientX;
                startWidth = th.getBoundingClientRect().width;
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            });

            handle.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
            });
        });
    };

    const syncHeaderSelection = (state) => {
        if (!state.headerSelectToggle) return;
        const scopeRows = state.visibleRows || [];
        const selected = scopeRows.filter((row) => !!getRowCheckbox(row, state)?.checked);
        state.headerSelectToggle.indeterminate = selected.length > 0 && selected.length < scopeRows.length;
        state.headerSelectToggle.checked = scopeRows.length > 0 && selected.length === scopeRows.length;
    };

    const selectedCount = (state) => collectRows(state.table).filter((row) => !!getRowCheckbox(row, state)?.checked).length;

    const initSort = (table, state) => {
        const headRow = table.querySelector('thead tr');
        if (!headRow) return;

        const runSort = (th, preferredDirection) => {
            const colKey = th.dataset.colKey || '';
            const colIndex = Array.from(headRow.children).indexOf(th);
            if (colIndex < 0) return;

            const nextDirection = preferredDirection || (state.sort.colKey === colKey && state.sort.direction === 'asc' ? 'desc' : 'asc');
            state.sort = { colKey, direction: nextDirection, columnIndex: colIndex };

            const rows = collectRows(table);
            rows.sort((a, b) => {
                const aText = (a.children[colIndex]?.textContent || '').trim().toLowerCase();
                const bText = (b.children[colIndex]?.textContent || '').trim().toLowerCase();
                const cmp = aText.localeCompare(bText, 'tr', { numeric: true });
                return nextDirection === 'asc' ? cmp : -cmp;
            });

            const tbody = table.querySelector('tbody');
            rows.forEach((row) => tbody.appendChild(row));

            Array.from(headRow.children).forEach((head) => {
                head.classList.remove('te-sort-asc', 'te-sort-desc');
            });
            th.classList.add(nextDirection === 'asc' ? 'te-sort-asc' : 'te-sort-desc');

            writeJson(makeStorageKey(table, 'sort'), state.sort);
            applyFilterAndPagination(table, state);
        };

        state.runSort = runSort;

        Array.from(headRow.children).forEach((th) => {
            if (isSelectionHeader(th)) return;
            th.classList.add('te-sortable');
            th.addEventListener('click', () => {
                runSort(th, '');
            });
        });
    };

    const renderPager = (state) => {
        const { pagerNode, pageCount, page } = state;
        pagerNode.innerHTML = '';
        if (pageCount <= 1) {
            pagerNode.style.display = 'none';
            return;
        }
        pagerNode.style.display = '';

        const makeBtn = (label, disabled, onClick, extraClass) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = label;
            btn.className = `te-page-btn${extraClass ? ` ${extraClass}` : ''}`;
            btn.disabled = disabled;
            btn.addEventListener('click', onClick);
            return btn;
        };

        pagerNode.appendChild(makeBtn('‹', page <= 1, () => {
            state.page = Math.max(1, state.page - 1);
            applyFilterAndPagination(state.table, state);
        }));

        const start = Math.max(1, page - 2);
        const end = Math.min(pageCount, start + 4);
        for (let i = start; i <= end; i += 1) {
            pagerNode.appendChild(makeBtn(String(i), false, () => {
                state.page = i;
                applyFilterAndPagination(state.table, state);
            }, i === page ? 'active' : ''));
        }

        pagerNode.appendChild(makeBtn('›', page >= pageCount, () => {
            state.page = Math.min(pageCount, state.page + 1);
            applyFilterAndPagination(state.table, state);
        }));
    };

    const escapeCell = (text) => {
        const val = String(text ?? '');
        if (/[",;\n\r\t]/.test(val)) return `"${val.replace(/"/g, '""')}"`;
        return val;
    };

    let xlsxLibPromise = null;

    const ensureXlsxLib = async () => {
        if (window.XLSX) return window.XLSX;
        if (!xlsxLibPromise) {
            xlsxLibPromise = new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = 'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js';
                script.async = true;
                script.onload = () => resolve(window.XLSX || null);
                script.onerror = () => reject(new Error('xlsx lib load failed'));
                document.head.appendChild(script);
            });
        }
        return xlsxLibPromise;
    };

    const exportRows = (state, rows, asCopy) => {
        const headers = Array.from(state.table.querySelectorAll('thead th'));
        const skipIndexes = headers
            .map((th, idx) => ({ th, idx }))
            .filter(({ th }) => isSelectionHeader(th))
            .map(({ idx }) => idx);

        const headerValues = headers
            .filter((th, idx) => !skipIndexes.includes(idx))
            .map((th) => (th.textContent || '').trim());

        const lines = [headerValues];
        rows.forEach((row) => {
            const values = Array.from(row.children)
                .filter((_, idx) => !skipIndexes.includes(idx))
                .map((cell) => (cell.textContent || '').replace(/\s+/g, ' ').trim());
            lines.push(values);
        });

        if (asCopy) {
            return lines.map((line) => line.join('\t')).join('\n');
        }
        return lines;
    };

    const resolveScopeRows = (state, scope) => {
        if (scope === 'all') return collectRows(state.table);
        if (scope === 'filtered') return state.filteredRows || [];
        if (scope === 'selected') {
            return collectRows(state.table).filter((row) => !!getRowCheckbox(row, state)?.checked);
        }
        return state.filteredRows || [];
    };

    const copyRows = async (state) => {
        const rows = resolveScopeRows(state, state.scopeSelect.value);
        if (!rows.length) {
            toast('Kopyalanacak satır yok.', 'info');
            return;
        }
        const text = exportRows(state, rows, true);
        try {
            await navigator.clipboard.writeText(text);
            toast(`${rows.length} satır panoya kopyalandı.`, 'success');
        } catch (_) {
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            ta.remove();
            toast(`${rows.length} satır panoya kopyalandı.`, 'success');
        }
    };

    const downloadAsCsv = (rows2d) => {
        const csv = rows2d.map((line) => line.map((v) => escapeCell(v)).join(';')).join('\r\n');
        const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const stamp = new Date().toISOString().replace(/[:T]/g, '-').slice(0, 19);
        a.href = url;
        a.download = `table-export-${stamp}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    };

    const downloadAsXlsx = async (rows2d) => {
        const XLSX = await ensureXlsxLib();
        if (!XLSX) throw new Error('xlsx lib unavailable');
        const wb = XLSX.utils.book_new();
        const ws = XLSX.utils.aoa_to_sheet(rows2d);
        XLSX.utils.book_append_sheet(wb, ws, 'Veri');
        const stamp = new Date().toISOString().replace(/[:T]/g, '-').slice(0, 19);
        XLSX.writeFile(wb, `table-export-${stamp}.xlsx`);
    };

    const downloadExcelLike = async (state) => {
        const rows = resolveScopeRows(state, state.scopeSelect.value);
        if (!rows.length) {
            toast('Aktarılacak satır yok.', 'info');
            return;
        }

        const rows2d = exportRows(state, rows, false);
        try {
            await downloadAsXlsx(rows2d);
            toast(`${rows.length} satır .xlsx olarak aktarıldı.`, 'success');
        } catch (_) {
            downloadAsCsv(rows2d);
            toast(`.xlsx üretilemedi, ${rows.length} satır CSV olarak indirildi.`, 'info');
        }
    };

    const applyFilterAndPagination = (table, state) => {
        const allRows = collectRows(table);
        const query = (state.searchInput.value || '').trim().toLocaleLowerCase('tr');

        const filtered = allRows.filter((row) => {
            if (!query) return true;
            return (row.textContent || '').toLocaleLowerCase('tr').includes(query);
        });

        const pageSize = toSafeNumber(state.sizeSelect.value, 25);
        const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
        state.page = Math.min(Math.max(1, state.page), pageCount);
        state.pageCount = pageCount;
        state.filteredRows = filtered;

        const start = (state.page - 1) * pageSize;
        const end = start + pageSize;

        allRows.forEach((row) => {
            row.style.display = 'none';
        });

        const visible = filtered.slice(start, end);
        visible.forEach((row) => {
            row.style.display = '';
        });
        state.visibleRows = visible;

        const selCount = selectedCount(state);
        state.infoNode.textContent = `${filtered.length} kayıt · Sayfa ${state.page}/${pageCount} · ${selCount} seçili`;
        syncHeaderSelection(state);
        renderPager(state);
    };

    const buildToolbar = (table, defaultPageSize) => {
        const toolbar = document.createElement('div');
        toolbar.className = 'te-toolbar';

        const left = document.createElement('div');
        left.className = 'te-toolbar-left';

        const search = document.createElement('input');
        search.type = 'text';
        search.className = 'te-search';
        search.placeholder = 'Tabloda hızlı ara...';
        left.appendChild(search);

        const right = document.createElement('div');
        right.className = 'te-toolbar-right';

        const sizeLabel = document.createElement('label');
        sizeLabel.className = 'te-size-label';
        sizeLabel.textContent = 'Sayfa:';

        const sizeSelect = document.createElement('select');
        sizeSelect.className = 'te-size-select';
        PAGE_SIZES.forEach((size) => {
            const opt = document.createElement('option');
            opt.value = String(size);
            opt.textContent = String(size);
            if (size === defaultPageSize) opt.selected = true;
            sizeSelect.appendChild(opt);
        });

        const scopeSelect = document.createElement('select');
        scopeSelect.className = 'te-scope-select';
        [
            { value: 'all', label: 'Tum satirlar' },
            { value: 'filtered', label: 'Filtrelenenler' },
            { value: 'selected', label: 'Secililer' },
        ].forEach((item) => {
            const opt = document.createElement('option');
            opt.value = item.value;
            opt.textContent = item.label;
            scopeSelect.appendChild(opt);
        });

        const selectBtn = document.createElement('button');
        selectBtn.type = 'button';
        selectBtn.className = 'te-action-btn';
        selectBtn.textContent = 'Tumunu Sec';

        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'te-action-btn';
        copyBtn.textContent = 'Kopyala';

        const exportBtn = document.createElement('button');
        exportBtn.type = 'button';
        exportBtn.className = 'te-action-btn te-action-primary';
        exportBtn.textContent = "Excel'e Aktar";

        const resetBtn = document.createElement('button');
        resetBtn.type = 'button';
        resetBtn.className = 'te-reset-btn';
        resetBtn.textContent = 'Kolonlari Sifirla';

        const info = document.createElement('div');
        info.className = 'te-info';

        right.appendChild(sizeLabel);
        right.appendChild(sizeSelect);
        right.appendChild(scopeSelect);
        right.appendChild(selectBtn);
        right.appendChild(copyBtn);
        right.appendChild(exportBtn);
        right.appendChild(resetBtn);
        right.appendChild(info);

        toolbar.appendChild(left);
        toolbar.appendChild(right);

        const pager = document.createElement('div');
        pager.className = 'te-pager';

        const wrapper = table.closest('.table-container') || table.parentElement;
        wrapper.parentElement.insertBefore(toolbar, wrapper);
        wrapper.parentElement.insertBefore(pager, wrapper.nextSibling);

        return { search, sizeSelect, scopeSelect, selectBtn, copyBtn, exportBtn, info, pager, resetBtn };
    };

    const applyOrderByKeys = (table, keys) => {
        if (!Array.isArray(keys) || keys.length === 0) return;
        const headRow = table.querySelector('thead tr');
        if (!headRow) return;

        keys.forEach((colKey, targetIndex) => {
            const headers = Array.from(headRow.children);
            const fromIndex = headers.findIndex((th) => (th.dataset.colKey || '') === colKey);
            if (fromIndex >= 0 && fromIndex !== targetIndex) {
                moveColumn(table, fromIndex, targetIndex);
            }
        });
    };

    const applyDefaultSortIfNeeded = (table, state) => {
        const savedSort = readJson(makeStorageKey(table, 'sort'), null);
        const hasSavedSort =
            savedSort &&
            typeof savedSort === 'object' &&
            ((savedSort.colKey && String(savedSort.colKey).length > 0) || Number.isFinite(savedSort.columnIndex));
        const sort = hasSavedSort ? savedSort : state.defaults.sort;
        if (!sort) return;

        const headers = Array.from(table.querySelectorAll('thead th'));
        let target = null;

        if (sort.colKey) {
            target = headers.find((th) => (th.dataset.colKey || '') === sort.colKey) || null;
        }

        if (!target && Number.isFinite(sort.columnIndex) && sort.columnIndex >= 0) {
            target = headers[sort.columnIndex] || null;
        }

        if (target && typeof state.runSort === 'function' && !isSelectionHeader(target)) {
            state.runSort(target, sort.direction === 'desc' ? 'desc' : 'asc');
        }
    };

    const resetTableState = (table, state) => {
        removeStorage(makeStorageKey(table, 'order'));
        removeStorage(makeStorageKey(table, 'widths'));
        removeStorage(makeStorageKey(table, 'sort'));
        removeStorage(makeStorageKey(table, 'page-size'));

        applyOrderByKeys(table, state.initialOrder);

        Array.from(table.querySelectorAll('thead th')).forEach((th) => {
            th.style.removeProperty('width');
            th.classList.remove('te-sort-asc', 'te-sort-desc');
        });

        collectRows(table).forEach((row) => {
            const chk = getRowCheckbox(row, state);
            if (chk) chk.checked = false;
        });

        state.searchInput.value = '';
        state.sizeSelect.value = String(state.defaults.pageSize);
        state.scopeSelect.value = 'all';
        state.page = 1;

        applyDefaultSortIfNeeded(table, state);
        applyFilterAndPagination(table, state);
    };

    const enhanceTable = (table) => {
        if (!table || table.dataset.tableEnhanced === '1') return;
        const head = table.querySelector('thead');
        const body = table.querySelector('tbody');
        if (!head || !body) return;

        table.dataset.tableEnhanced = '1';
        table.classList.add('te-table');

        const selection = ensureSelectionColumn(table);

        const defaults = getDefaults(table);
        ensureColKeys(table);
        const initialOrder = Array.from(table.querySelectorAll('thead th')).map((th) => th.dataset.colKey || '');
        restoreOrder(table);
        restoreWidths(table);

        const savedPageSize = toSafeNumber(readJson(makeStorageKey(table, 'page-size'), defaults.pageSize), defaults.pageSize);
        const { search, sizeSelect, scopeSelect, selectBtn, copyBtn, exportBtn, info, pager, resetBtn } = buildToolbar(table, savedPageSize);

        const state = {
            table,
            page: 1,
            pageCount: 1,
            sort: { colKey: '', direction: 'asc', columnIndex: -1 },
            searchInput: search,
            sizeSelect,
            scopeSelect,
            infoNode: info,
            pagerNode: pager,
            initialOrder,
            defaults,
            runSort: null,
            selectionSelector: selection.selector,
            headerSelectToggle: selection.headerToggle,
            filteredRows: [],
            visibleRows: [],
        };

        initColumnDnD(table);
        initColumnResize(table);
        initSort(table, state);

        if (state.headerSelectToggle) {
            state.headerSelectToggle.addEventListener('change', () => {
                const rows = state.visibleRows || [];
                rows.forEach((row) => {
                    const chk = getRowCheckbox(row, state);
                    if (chk) chk.checked = state.headerSelectToggle.checked;
                });
                applyFilterAndPagination(table, state);
            });
        }

        syncBuiltInSelectionRows(state);
        collectRows(table).forEach((row) => {
            const chk = getRowCheckbox(row, state);
            if (chk) {
                chk.addEventListener('change', () => applyFilterAndPagination(table, state));
            }
        });

        search.addEventListener('input', () => {
            state.page = 1;
            applyFilterAndPagination(table, state);
        });

        sizeSelect.addEventListener('change', () => {
            writeJson(makeStorageKey(table, 'page-size'), toSafeNumber(sizeSelect.value, 25));
            state.page = 1;
            applyFilterAndPagination(table, state);
        });

        selectBtn.addEventListener('click', () => {
            const rows = state.visibleRows || [];
            const allSelected = rows.length > 0 && rows.every((row) => !!getRowCheckbox(row, state)?.checked);
            rows.forEach((row) => {
                const chk = getRowCheckbox(row, state);
                if (chk) chk.checked = !allSelected;
            });
            applyFilterAndPagination(table, state);
        });

        copyBtn.addEventListener('click', () => {
            copyRows(state);
        });

        exportBtn.addEventListener('click', () => {
            downloadExcelLike(state);
        });

        resetBtn.addEventListener('click', () => {
            resetTableState(table, state);
        });

        const observer = new MutationObserver(() => {
            if (!document.body.contains(table)) {
                observer.disconnect();
                return;
            }
            syncBuiltInSelectionRows(state);
            applyFilterAndPagination(table, state);
        });
        observer.observe(body, { childList: true, subtree: true });

        applyDefaultSortIfNeeded(table, state);
        applyFilterAndPagination(table, state);
    };

    const init = () => {
        document.querySelectorAll(TABLE_SELECTOR).forEach((table) => enhanceTable(table));
    };

    document.addEventListener('DOMContentLoaded', () => {
        init();

        let scheduled = false;
        const observer = new MutationObserver(() => {
            if (scheduled) return;
            scheduled = true;
            requestAnimationFrame(() => {
                scheduled = false;
                init();
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    });
})();
