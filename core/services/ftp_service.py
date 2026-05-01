"""FTP / FTPS / SFTP helpers.

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

import os
import ftplib
import fnmatch

try:
	import paramiko
except Exception:  # pragma: no cover
	paramiko = None


def _ftp_list_files(account, remote_path='.', file_pattern='*'):
	remote_path = str(remote_path or '.').strip() or '.'
	file_pattern = str(file_pattern or '*').strip() or '*'
	items = []

	if account.protocol == 'sftp':
		if paramiko is None:
			raise RuntimeError('SFTP için paramiko kurulu değil.')
		transport = paramiko.Transport((account.host, int(account.port or 22)))
		try:
			transport.connect(username=account.username, password=account.get_password())
			sftp = paramiko.SFTPClient.from_transport(transport)
			for attr in sftp.listdir_attr(remote_path):
				name = attr.filename
				if fnmatch.fnmatch(name, file_pattern):
					items.append(name)
			sftp.close()
		finally:
			transport.close()
		return items

	if account.protocol == 'ftps':
		ftp = ftplib.FTP_TLS()
		ftp.connect(account.host, int(account.port or 21), timeout=20)
		ftp.login(account.username, account.get_password())
		ftp.prot_p()
		ftp.cwd(remote_path)
		try:
			items = [n for n in ftp.nlst() if fnmatch.fnmatch(os.path.basename(n), file_pattern)]
		finally:
			ftp.quit()
		return items

	ftp = ftplib.FTP()
	ftp.connect(account.host, int(account.port or 21), timeout=20)
	ftp.login(account.username, account.get_password())
	ftp.cwd(remote_path)
	try:
		items = [n for n in ftp.nlst() if fnmatch.fnmatch(os.path.basename(n), file_pattern)]
	finally:
		ftp.quit()
	return items


def _ftp_download(account, remote_path, local_path, file_pattern='*', limit=0):
	remote_path = str(remote_path or '.').strip() or '.'
	local_path = str(local_path or '').strip()
	if not local_path:
		raise RuntimeError('local_path zorunlu.')
	os.makedirs(local_path, exist_ok=True)

	files = _ftp_list_files(account, remote_path=remote_path, file_pattern=file_pattern)
	if limit and limit > 0:
		files = files[:limit]

	downloaded = []
	if account.protocol == 'sftp':
		if paramiko is None:
			raise RuntimeError('SFTP için paramiko kurulu değil.')
		transport = paramiko.Transport((account.host, int(account.port or 22)))
		try:
			transport.connect(username=account.username, password=account.get_password())
			sftp = paramiko.SFTPClient.from_transport(transport)
			for name in files:
				remote_file = f"{remote_path.rstrip('/')}/{os.path.basename(name)}"
				local_file = os.path.join(local_path, os.path.basename(name))
				sftp.get(remote_file, local_file)
				downloaded.append(local_file)
			sftp.close()
		finally:
			transport.close()
		return downloaded

	if account.protocol == 'ftps':
		ftp = ftplib.FTP_TLS()
		ftp.connect(account.host, int(account.port or 21), timeout=20)
		ftp.login(account.username, account.get_password())
		ftp.prot_p()
		ftp.cwd(remote_path)
		try:
			for name in files:
				base = os.path.basename(name)
				local_file = os.path.join(local_path, base)
				with open(local_file, 'wb') as fp:
					ftp.retrbinary(f'RETR {base}', fp.write)
				downloaded.append(local_file)
		finally:
			ftp.quit()
		return downloaded

	ftp = ftplib.FTP()
	ftp.connect(account.host, int(account.port or 21), timeout=20)
	ftp.login(account.username, account.get_password())
	ftp.cwd(remote_path)
	try:
		for name in files:
			base = os.path.basename(name)
			local_file = os.path.join(local_path, base)
			with open(local_file, 'wb') as fp:
				ftp.retrbinary(f'RETR {base}', fp.write)
			downloaded.append(local_file)
	finally:
		ftp.quit()
	return downloaded


def _ftp_upload(account, local_file, remote_path):
	local_file = str(local_file or '').strip()
	remote_path = str(remote_path or '.').strip() or '.'
	if not local_file:
		raise RuntimeError('local_file zorunlu.')
	if not os.path.isfile(local_file):
		raise RuntimeError(f'Yerel dosya bulunamadı: {local_file}')
	base = os.path.basename(local_file)

	if account.protocol == 'sftp':
		if paramiko is None:
			raise RuntimeError('SFTP için paramiko kurulu değil.')
		transport = paramiko.Transport((account.host, int(account.port or 22)))
		try:
			transport.connect(username=account.username, password=account.get_password())
			sftp = paramiko.SFTPClient.from_transport(transport)
			remote_file = f"{remote_path.rstrip('/')}/{base}"
			sftp.put(local_file, remote_file)
			sftp.close()
		finally:
			transport.close()
		return remote_file

	if account.protocol == 'ftps':
		ftp = ftplib.FTP_TLS()
		ftp.connect(account.host, int(account.port or 21), timeout=20)
		ftp.login(account.username, account.get_password())
		ftp.prot_p()
		ftp.cwd(remote_path)
		try:
			with open(local_file, 'rb') as fp:
				ftp.storbinary(f'STOR {base}', fp)
		finally:
			ftp.quit()
		return f"{remote_path.rstrip('/')}/{base}"

	ftp = ftplib.FTP()
	ftp.connect(account.host, int(account.port or 21), timeout=20)
	ftp.login(account.username, account.get_password())
	ftp.cwd(remote_path)
	try:
		with open(local_file, 'rb') as fp:
			ftp.storbinary(f'STOR {base}', fp)
	finally:
		ftp.quit()
	return f"{remote_path.rstrip('/')}/{base}"


