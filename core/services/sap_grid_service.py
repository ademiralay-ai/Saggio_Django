"""SAP ALV grid / GuiTableControl helpers.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import time

from ..utils.parsing import _normalize_session_element_id, _normalize_match_text
from .sap_runtime_service import _iter_children


def find_alv_grid(root, candidate_id=None, grid_type='main'):
	search_id = _normalize_session_element_id(candidate_id) if candidate_id else ''
	preferred = None
	stack = [root] if root is not None else []
	while stack:
		node = stack.pop(0)
		try:
			node_id = str(getattr(node, 'Id', '') or getattr(node, 'ID', '') or '')
			node_type = str(getattr(node, 'Type', '') or '')
			lower_id = node_id.lower()
			lower_type = node_type.lower()
			if search_id and node_id == search_id:
				return node
			is_grid_like = (
				'grid' in lower_id
				or 'grid' in lower_type
				or 'shell' in lower_type
				or 'tablecontrol' in lower_type
				or lower_id.split('/')[-1].startswith('tbl')
			)
			if is_grid_like:
				if grid_type == 'detail':
					if 'wnd[1]' in node_id or 'alv_ht' in lower_id:
						return node
				else:
					if 'wnd[0]' in node_id:
						return node
					if preferred is None:
						preferred = node
		except Exception:
			pass
		stack.extend(_iter_children(node))
	if search_id:
		return None
	return preferred



def _get_grid_row_count(grid):
	for attr in ('rowCount', 'RowCount', 'visibleRowCount', 'VisibleRowCount'):
		try:
			value = int(getattr(grid, attr, 0) or 0)
			if value >= 0:
				return value
		except Exception:
			continue
	return 0



def _resolve_grid_row_by_text(grid, text_contains):
	needle = _normalize_match_text(text_contains)
	if not needle:
		return None

	row_count = _get_grid_row_count(grid)
	if row_count <= 0:
		return None

	columns = []
	try:
		order = list(getattr(grid, 'ColumnOrder', []) or [])
		columns = [c for c in order if c is not None and str(c).strip()]
	except Exception:
		columns = []

	if not columns:
		try:
			cols_obj = getattr(grid, 'columns', None)
			cnt = int(getattr(cols_obj, 'Count', 0) or 0) if cols_obj is not None else 0
			for ci in range(cnt):
				try:
					col = cols_obj.elementAt(ci)
				except Exception:
					try:
						col = cols_obj.Item(ci)
					except Exception:
						col = None
				if col is None:
					continue
				name = str(getattr(col, 'Name', '') or getattr(col, 'name', '') or '').strip()
				columns.append(name if name else ci)
		except Exception:
			columns = []

	for ridx in range(row_count):
		cell_values = []
		seen_values = set()
		for col in columns:
			try:
				v = str(grid.getCellValue(ridx, col) or '').strip()
				if v and v not in seen_values:
					cell_values.append(v)
					seen_values.add(v)
				continue
			except Exception:
				pass
			try:
				cell = grid.GetCell(ridx, col)
				v = str(getattr(cell, 'Text', '') or getattr(cell, 'text', '') or '').strip()
				if v and v not in seen_values:
					cell_values.append(v)
					seen_values.add(v)
			except Exception:
				continue

		# GuiTableControl için index bazlı hücre okumayı her durumda dene.
		for ci in range(30):
			try:
				cell = grid.GetCell(ridx, ci)
				v = str(getattr(cell, 'Text', '') or getattr(cell, 'text', '') or '').strip()
				if v and v not in seen_values:
					cell_values.append(v)
					seen_values.add(v)
			except Exception:
				if ci > 8:
					break

		row_text = _normalize_match_text(' | '.join(v for v in cell_values if v))
		if row_text and needle in row_text:
			return ridx

	return None



def _read_grid_row_data(grid, row_index):
	"""
	Seçilen grid satırındaki tüm hücre değerlerini sutun_1, sutun_2, ... olarak döndürür.
	Boş hücreler dahil edilmez; her sutun_N için hem sütun adı hem değer saklanır.
	Dönüş: {'sutun_1': 'değer', 'sutun_2': 'değer', ...}  (en fazla 50 sütun)
	"""
	result = {}
	ridx = max(0, int(row_index or 0))
	columns = []

	try:
		order = list(getattr(grid, 'ColumnOrder', []) or [])
		columns = [c for c in order if c is not None and str(c).strip()]
	except Exception:
		columns = []

	if not columns:
		try:
			cols_obj = getattr(grid, 'columns', None)
			cnt = int(getattr(cols_obj, 'Count', 0) or 0) if cols_obj is not None else 0
			for ci in range(min(cnt, 50)):
				try:
					col = cols_obj.elementAt(ci)
				except Exception:
					try:
						col = cols_obj.Item(ci)
					except Exception:
						col = None
				if col is None:
					continue
				name = str(getattr(col, 'Name', '') or getattr(col, 'name', '') or '').strip()
				columns.append(name if name else ci)
		except Exception:
			columns = []

	slot = 1
	seen_values = set()
	for col in columns[:50]:
		v = ''
		try:
			v = str(grid.getCellValue(ridx, col) or '').strip()
		except Exception:
			pass
		if not v:
			try:
				cell = grid.GetCell(ridx, col)
				v = str(getattr(cell, 'Text', '') or getattr(cell, 'text', '') or '').strip()
			except Exception:
				pass
		if v and v not in seen_values:
			result[f'sutun_{slot}'] = v
			seen_values.add(v)
			slot += 1

	# GuiTableControl index bazlı fallback
	if not result:
		for ci in range(50):
			try:
				cell = grid.GetCell(ridx, ci)
				v = str(getattr(cell, 'Text', '') or getattr(cell, 'text', '') or '').strip()
				if v and v not in seen_values:
					result[f'sutun_{slot}'] = v
					seen_values.add(v)
					slot += 1
			except Exception:
				if ci > 8:
					break

	return result



def _select_row_on_grid(grid, row_index):
	"""Hem ALV grid hem GuiTableControl için satır seçmeyi dener."""
	try:
		idx = max(0, int(row_index or 0))
	except Exception:
		idx = 0

	row_count = _get_grid_row_count(grid)
	if row_count > 0:
		idx = min(idx, row_count - 1)

	errors = []

	# GuiTableControl için en güvenilir yöntem
	try:
		abs_row = grid.getAbsoluteRow(idx)
		abs_row.selected = True
		try:
			grid.currentCellRow = idx
		except Exception:
			pass
		# Eski scriptteki gibi ilk hücreye focus vermeyi dene
		try:
			first_cell = None
			for child in _iter_children(grid):
				try:
					cid = str(getattr(child, 'Id', '') or '')
					if cid.endswith('[0,0]') or cid.endswith(f'[0,{idx}]'):
						first_cell = child
						break
				except Exception:
					pass
			if first_cell is not None:
				first_cell.setFocus()
				try:
					first_cell.caretPosition = 0
				except Exception:
					pass
		except Exception:
			pass
		return True, idx, None
	except Exception as ex:
		errors.append(f'getAbsoluteRow: {ex}')

	# ALV GridView için yaygın yöntem
	try:
		grid.currentCellRow = idx
		try:
			grid.selectedRows = str(idx)
		except Exception:
			pass
		return True, idx, None
	except Exception as ex:
		errors.append(f'currentCellRow/selectedRows: {ex}')

	return False, idx, ' | '.join(errors)



def _find_grid(service, grid_id='', timeout_sec=5, grid_type='main'):
	normalized_id = _normalize_session_element_id(grid_id)
	deadline = time.time() + max(1, timeout_sec)
	while time.time() < deadline:
		service._wait_until_idle(service.session, timeout_sec=3, stable_checks=1)
		grid = None
		if normalized_id:
			grid = service._safe_find(service.session, normalized_id)
			# Bazı kayıtlarda grid yerine hücre id gelebilir; üst segmentlerden gerçek gridi bul.
			if grid is None and '/' in normalized_id:
				parts = normalized_id.split('/')
				for end in range(len(parts) - 1, 0, -1):
					candidate = '/'.join(parts[:end])
					last = candidate.split('/')[-1].lower()
					if not (last.startswith('tbl') or last.startswith('shell') or 'grid' in last):
						continue
					grid = service._safe_find(service.session, candidate)
					if grid is not None:
						break
		if grid is None:
			grid = find_alv_grid(service.session, normalized_id or None, grid_type=grid_type)
		# İstenen id verilmişse ve o bulunamadıysa yanlış grid'e düşmeyelim.
		if normalized_id and grid is not None:
			try:
				gid = _normalize_session_element_id(str(getattr(grid, 'Id', '') or ''))
				if gid != normalized_id and (f'{gid}/' not in f'{normalized_id}/'):
					grid = None
			except Exception:
				pass
		if grid is not None:
			return grid
		time.sleep(0.2)
	return None


