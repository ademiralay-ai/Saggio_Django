"""Dynamic date helpers used by SAP runtime placeholders.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations


def _calc_dynamic_date(key):
	"""JS calcDynamicDate'in Python karşılığı — SAP DD.MM.YYYY formatında tarih döner."""
	from datetime import date, timedelta
	import calendar
	today = date.today()
	y, m = today.year, today.month

	if key == 'today':
		d = today
	elif key == 'yesterday':
		d = today - timedelta(days=1)
	elif key == 'year_start':
		d = date(y, 1, 1)
	elif key == 'month_start':
		d = date(y, m, 1)
	elif key == 'year_end':
		d = date(y, 12, 31)
	elif key == 'month_end':
		d = date(y, m, calendar.monthrange(y, m)[1])
	elif key == 'prev_month_start':
		pm = m - 1 if m > 1 else 12
		py = y if m > 1 else y - 1
		d = date(py, pm, 1)
	elif key == 'prev_month_end':
		pm = m - 1 if m > 1 else 12
		py = y if m > 1 else y - 1
		d = date(py, pm, calendar.monthrange(py, pm)[1])
	elif key == 'month_5':
		d = date(y, m, 5)
	elif key == 'prev_year_start':
		d = date(y - 1, 1, 1)
	elif key == 'days_15':
		d = today - timedelta(days=15)
	elif key == 'days_30':
		d = today - timedelta(days=30)
	elif key == 'days_45':
		d = today - timedelta(days=45)
	elif key == 'days_60':
		d = today - timedelta(days=60)
	elif key == 'days_365':
		d = today - timedelta(days=365)
	else:
		return ''

	return f"{d.day:02d}.{d.month:02d}.{d.year}"
