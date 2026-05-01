"""Lightweight HTTP request helpers used by API views.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import json


def _read_json_body(request):
	try:
		return json.loads(request.body or b'{}')
	except (json.JSONDecodeError, TypeError):
		return None


def _request_ip(request):
	forwarded = str(request.META.get('HTTP_X_FORWARDED_FOR', '') or '').strip()
	if forwarded:
		return forwarded.split(',')[0].strip()
	return str(request.META.get('REMOTE_ADDR', '') or '').strip()
