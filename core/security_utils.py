import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


PREFIX = 'enc::'


def _fernet():
    digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def is_encrypted(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt_secret(value):
    raw = str(value or '')
    if not raw:
        return ''
    if is_encrypted(raw):
        return raw
    token = _fernet().encrypt(raw.encode('utf-8')).decode('utf-8')
    return f'{PREFIX}{token}'


def decrypt_secret(value):
    raw = str(value or '')
    if not raw:
        return ''
    if not is_encrypted(raw):
        return raw

    token = raw[len(PREFIX):]
    try:
        return _fernet().decrypt(token.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        return ''
