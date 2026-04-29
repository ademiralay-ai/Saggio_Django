import ctypes
import time
import unicodedata
from ctypes import wintypes


user32 = ctypes.WinDLL('user32', use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

GWL_STYLE = -16
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BM_CLICK = 0x00F5
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_RETURN = 0x0D
BST_UNCHECKED = 0x0000
BST_CHECKED = 0x0001
SW_RESTORE = 9
SMTO_NORMAL = 0x0000
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002

BS_PUSHBUTTON = 0x00000000
BS_DEFPUSHBUTTON = 0x00000001
BS_CHECKBOX = 0x00000002
BS_AUTOCHECKBOX = 0x00000003
BS_RADIOBUTTON = 0x00000004
BS_3STATE = 0x00000005
BS_AUTO3STATE = 0x00000006
BS_GROUPBOX = 0x00000007
BS_AUTORADIOBUTTON = 0x00000009
BS_COMMANDLINK = 0x0000000E
BS_DEFCOMMANDLINK = 0x0000000F

_BUTTON_KIND_BY_STYLE = {
    BS_CHECKBOX: 'checkbox',
    BS_AUTOCHECKBOX: 'checkbox',
    BS_3STATE: 'checkbox',
    BS_AUTO3STATE: 'checkbox',
    BS_RADIOBUTTON: 'radio',
    BS_AUTORADIOBUTTON: 'radio',
    BS_PUSHBUTTON: 'button',
    BS_DEFPUSHBUTTON: 'button',
    BS_COMMANDLINK: 'button',
    BS_DEFCOMMANDLINK: 'button',
}


def _safe_text(hwnd):
    try:
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return str(buf.value or '').strip()
    except Exception:
        return ''


def _safe_class(hwnd):
    try:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 255)
        return str(buf.value or '').strip()
    except Exception:
        return ''


def _safe_style(hwnd):
    try:
        return int(user32.GetWindowLongW(hwnd, GWL_STYLE) or 0)
    except Exception:
        return 0


def _normalize(value):
    text = str(value or '').strip()
    if not text:
        return ''
    # Remove Windows mnemonic markers and normalize Turkish/Unicode variants.
    text = text.replace('&', '')
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    # Turkish dotless-I chars survive NFKD; map them to ASCII equivalents for matching.
    text = text.replace('\u0131', 'i').replace('\u0130', 'I')
    text = ' '.join(text.split())
    return text.casefold()


_TEXT_ALIASES = {
    'allow': {'izin ver', 'allow', 'permit', 'ok', 'tamam'},
    'izin ver': {'izin ver', 'allow', 'permit', 'ok', 'tamam'},
    'deny': {'reddet', 'deny', 'reject', 'no', 'hayir'},
    'reddet': {'reddet', 'deny', 'reject', 'no', 'hayir'},
    'remember my decision': {'remember my decision', 'kararimi hatirla', 'remember decision', 'karari hatirla'},
    'kararimi hatirla': {'remember my decision', 'kararimi hatirla', 'remember decision', 'karari hatirla'},
    'help': {'help', 'yardim'},
    'yardim': {'help', 'yardim'},
    'yes': {'yes', 'evet', 'ok', 'tamam'},
    'no': {'no', 'hayir', 'reddet'},
}


def _expand_aliases(text):
    base = _normalize(text)
    expanded = {base}
    if not base:
        return expanded
    for key, values in _TEXT_ALIASES.items():
        nkey = _normalize(key)
        if nkey == base or nkey in base or base in nkey:
            expanded.update({_normalize(v) for v in values})
    return {x for x in expanded if x}


def _text_matches(actual, expected, mode='contains'):
    actual_text = _normalize(actual)
    expected_text = _normalize(expected)
    if not expected_text:
        return True
    actual_aliases = _expand_aliases(actual_text)
    expected_aliases = _expand_aliases(expected_text)
    if mode == 'exact':
        return any(a == e for a in actual_aliases for e in expected_aliases)
    return any((e in a) or (a in e) for a in actual_aliases for e in expected_aliases)


def _classify_control(hwnd):
    class_name = _safe_class(hwnd)
    style = _safe_style(hwnd)
    if class_name.casefold() == 'button':
        kind = _BUTTON_KIND_BY_STYLE.get(style & 0x0F, 'button')
        if kind == 'button' and (style & 0x0F) == BS_GROUPBOX:
            kind = 'groupbox'
        return kind
    if class_name.casefold() in ('edit', 'richedit20w', 'richedit50w'):
        return 'input'
    return class_name or 'control'


def _enum_windows():
    results = []

    @EnumWindowsProc
    def _callback(hwnd, lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            title = _safe_text(hwnd)
            class_name = _safe_class(hwnd)
            if not title and not class_name:
                return True
            results.append({
                'hwnd': int(hwnd),
                'title': title,
                'class_name': class_name,
                'visible': bool(user32.IsWindowVisible(hwnd)),
                'enabled': bool(user32.IsWindowEnabled(hwnd)),
            })
        except Exception:
            pass
        return True

    user32.EnumWindows(_callback, 0)
    return results


def _enum_child_controls(parent_hwnd):
    results = []

    @EnumChildProc
    def _callback(hwnd, lparam):
        try:
            text = _safe_text(hwnd)
            class_name = _safe_class(hwnd)
            kind = _classify_control(hwnd)
            if kind == 'groupbox':
                return True
            results.append({
                'hwnd': int(hwnd),
                'text': text,
                'class_name': class_name,
                'kind': kind,
                'visible': bool(user32.IsWindowVisible(hwnd)),
                'enabled': bool(user32.IsWindowEnabled(hwnd)),
            })
        except Exception:
            pass
        return True

    user32.EnumChildWindows(wintypes.HWND(parent_hwnd), _callback, 0)
    return results


def scan_visible_dialogs(title_filter=''):
    dialogs = []
    for wnd in _enum_windows():
        title = wnd.get('title', '')
        class_name = str(wnd.get('class_name', '') or '')
        if not title:
            continue
        if title_filter and not _text_matches(title, title_filter, mode='contains'):
            continue

        controls = _enum_child_controls(wnd['hwnd'])
        buttons = []
        checkboxes = []
        radios = []
        inputs = []

        for ctrl in controls:
            entry = {
                'hwnd': ctrl['hwnd'],
                'text': ctrl.get('text', ''),
                'class_name': ctrl.get('class_name', ''),
                'visible': bool(ctrl.get('visible')),
                'enabled': bool(ctrl.get('enabled')),
                'label': f"{ctrl.get('text') or ctrl.get('class_name') or ctrl.get('kind')} [{ctrl['hwnd']}]",
            }
            kind = ctrl.get('kind')
            if kind == 'button':
                buttons.append(entry)
            elif kind == 'checkbox':
                checkboxes.append(entry)
            elif kind == 'radio':
                radios.append(entry)
            elif kind == 'input':
                inputs.append(entry)

        if not buttons and not checkboxes and not radios and not inputs and class_name != '#32770':
            continue

        dialogs.append({
            'hwnd': wnd['hwnd'],
            'title': title,
            'class_name': class_name,
            'buttons': buttons,
            'checkboxes': checkboxes,
            'radios': radios,
            'inputs': inputs,
            'label': f"{title} [{wnd['hwnd']}]",
        })

    dialogs.sort(key=lambda x: (x.get('title', '').casefold(), int(x.get('hwnd', 0))))
    return dialogs


def _find_dialog(dialogs, window_title, title_match_mode='contains'):
    for dialog in dialogs:
        if _text_matches(dialog.get('title', ''), window_title, title_match_mode):
            return dialog
    return None


def _find_dialog_by_controls(dialogs, button_text='', checkbox_text='', match_mode='contains'):
    """Fallback finder: match dialog by known control captions when title is unreliable."""
    for dialog in dialogs or []:
        if checkbox_text:
            chk = _find_control(dialog.get('checkboxes', []), checkbox_text, match_mode=match_mode)
            rad = _find_control(dialog.get('radios', []), checkbox_text, match_mode=match_mode)
            if chk is None and rad is None:
                continue
        if button_text:
            btn = _find_control(dialog.get('buttons', []), button_text, match_mode=match_mode)
            if btn is None:
                continue
        return dialog
    return None


def _find_control(controls, control_text, match_mode='contains'):
    for ctrl in controls or []:
        if _text_matches(ctrl.get('text', ''), control_text, match_mode):
            return ctrl
    return None


def _bring_to_front(hwnd):
    try:
        user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
    except Exception:
        pass


def _send_message_timeout(hwnd, msg, wparam=0, lparam=0, timeout_ms=450):
    result = ctypes.c_size_t(0)
    try:
        ret = user32.SendMessageTimeoutW(
            wintypes.HWND(hwnd),
            wintypes.UINT(msg),
            wintypes.WPARAM(wparam),
            wintypes.LPARAM(lparam),
            wintypes.UINT(SMTO_BLOCK | SMTO_ABORTIFHUNG | SMTO_NORMAL),
            wintypes.UINT(max(50, min(int(timeout_ms or 450), 5000))),
            ctypes.byref(result),
        )
        if not ret:
            return False, None
        return True, int(result.value)
    except Exception:
        return False, None
    try:
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
    except Exception:
        pass


def _set_checked(hwnd, checked=True):
    target = BST_CHECKED if checked else BST_UNCHECKED
    ok_set, _ = _send_message_timeout(hwnd, BM_SETCHECK, target, 0, timeout_ms=500)
    if not ok_set:
        return False, 'setcheck-timeout'

    ok_get, current_val = _send_message_timeout(hwnd, BM_GETCHECK, 0, 0, timeout_ms=350)
    current = int(current_val or 0)
    if not ok_get:
        return False, 'getcheck-timeout'
    if current == target:
        return True, f'check={target}'

    ok_click, _ = _send_message_timeout(hwnd, BM_CLICK, 0, 0, timeout_ms=500)
    if not ok_click:
        try:
            # Fallback: asynchronous click so the worker thread does not block.
            user32.PostMessageW(wintypes.HWND(hwnd), BM_CLICK, 0, 0)
        except Exception:
            return False, 'click-timeout'
    time.sleep(0.1)
    ok_get2, current_val2 = _send_message_timeout(hwnd, BM_GETCHECK, 0, 0, timeout_ms=350)
    current = int(current_val2 or 0)
    if not ok_get2:
        return False, 'getcheck2-timeout'
    return current == target, f'click-after-check={current}'


def _click_button(hwnd):
    ok_click, _ = _send_message_timeout(hwnd, BM_CLICK, 0, 0, timeout_ms=700)
    if ok_click:
        return True, 'BM_CLICK(timeout-safe)'
    try:
        user32.PostMessageW(wintypes.HWND(hwnd), BM_CLICK, 0, 0)
        return True, 'BM_CLICK(postmessage-fallback)'
    except Exception:
        return False, 'BM_CLICK-timeout'


def _press_enter(hwnd):
    ok_down, _ = _send_message_timeout(hwnd, WM_KEYDOWN, VK_RETURN, 0, timeout_ms=300)
    ok_up, _ = _send_message_timeout(hwnd, WM_KEYUP, VK_RETURN, 0, timeout_ms=300)
    if ok_down and ok_up:
        return True, 'ENTER(sendmessage)'
    try:
        user32.PostMessageW(wintypes.HWND(hwnd), WM_KEYDOWN, VK_RETURN, 0)
        user32.PostMessageW(wintypes.HWND(hwnd), WM_KEYUP, VK_RETURN, 0)
        return True, 'ENTER(postmessage-fallback)'
    except Exception:
        return False, 'ENTER-timeout'


def perform_dialog_action(
    window_title,
    button_text='',
    checkbox_text='',
    checkbox_state=True,
    title_match_mode='contains',
    button_match_mode='contains',
    checkbox_match_mode='contains',
    timeout_sec=15,
    poll_ms=250,
    ready_delay_ms=350,
    allow_control_fallback=False,
    on_progress=None,
    progress_interval_ms=1000,
):
    deadline = time.time() + max(1, min(int(timeout_sec or 15), 120))
    sleep_sec = max(0.05, min(int(poll_ms or 250), 5000) / 1000.0)
    ready_delay_sec = max(0.0, min(int(ready_delay_ms or 0), 5000) / 1000.0)
    progress_every_sec = max(0.2, min(int(progress_interval_ms or 1000), 10000) / 1000.0)
    last_progress_at = 0.0
    last_error = 'Dialog bulunamadı.'
    last_seen = None

    while time.time() < deadline:
        now = time.time()
        if callable(on_progress) and (now - last_progress_at) >= progress_every_sec:
            remain_sec = max(0, int(round(deadline - now)))
            try:
                on_progress({'remaining_sec': remain_sec, 'status': 'searching'})
            except Exception:
                pass
            last_progress_at = now

        # Başlık filtresiz tüm pencereleri tara (başlık filtresi bazı pencereleri ıskalar)
        all_dialogs = scan_visible_dialogs(title_filter='')
        # Önce başlık eşleşmesi dene
        dialog = _find_dialog(all_dialogs, window_title, title_match_mode=title_match_mode)
        # Başlık bulunamadıysa VE window_title boşsa, control-bazlı fallback dene
        if dialog is None and not window_title.strip():
            dialog = _find_dialog_by_controls(
                all_dialogs,
                button_text=button_text,
                checkbox_text=checkbox_text,
                match_mode='contains',
            )
        # Başlık dolu ama farklı varyant geldiyse (örn: SAP GUI Security / SAP GUI güvenliği),
        # sadece izin verilen durumda ve SAP pencereleriyle sınırlı control fallback dene.
        if dialog is None and window_title.strip() and allow_control_fallback and (button_text or checkbox_text):
            expected_title_norm = _normalize(window_title)
            candidate_dialogs = all_dialogs
            if 'sap gui' in expected_title_norm:
                candidate_dialogs = [d for d in all_dialogs if 'sap gui' in _normalize(d.get('title', ''))]
            dialog = _find_dialog_by_controls(
                candidate_dialogs,
                button_text=button_text,
                checkbox_text=checkbox_text,
                match_mode='contains',
            )
        dialogs = all_dialogs
        if dialog is None:
            time.sleep(sleep_sec)
            continue

        last_seen = {
            'title': dialog.get('title', ''),
            'buttons': [str(x.get('text', '') or '').strip() for x in (dialog.get('buttons') or []) if str(x.get('text', '') or '').strip()],
            'checkboxes': [str(x.get('text', '') or '').strip() for x in (dialog.get('checkboxes') or []) if str(x.get('text', '') or '').strip()],
            'radios': [str(x.get('text', '') or '').strip() for x in (dialog.get('radios') or []) if str(x.get('text', '') or '').strip()],
        }

        _bring_to_front(dialog['hwnd'])
        if callable(on_progress):
            try:
                on_progress({'remaining_sec': max(0, int(round(deadline - time.time()))), 'status': 'found', 'title': dialog.get('title', '')})
            except Exception:
                pass
        if ready_delay_sec > 0:
            time.sleep(ready_delay_sec)

        if checkbox_text:
            checkbox = _find_control(dialog.get('checkboxes', []), checkbox_text, match_mode=checkbox_match_mode)
            if checkbox is None:
                radio = _find_control(dialog.get('radios', []), checkbox_text, match_mode=checkbox_match_mode)
                checkbox = radio
            if checkbox is None:
                last_error = f'İşaretlenecek kontrol bulunamadı: {checkbox_text}'
                time.sleep(sleep_sec)
                continue
            ok_check, check_msg = _set_checked(checkbox['hwnd'], checked=bool(checkbox_state))
            if not ok_check:
                last_error = f'Kontrol işaretlenemedi: {checkbox_text} | {check_msg}'
                time.sleep(sleep_sec)
                continue

        if button_text:
            button = _find_control(dialog.get('buttons', []), button_text, match_mode=button_match_mode)
            if button is None:
                last_error = f'Buton bulunamadı: {button_text}'
                time.sleep(sleep_sec)
                continue
            ok_click, click_msg = _click_button(button['hwnd'])
            if not ok_click:
                last_error = f'Butona tıklanamadı: {button_text} | {click_msg}'
                time.sleep(sleep_sec)
                continue
            parts = [f'Pencere: {dialog.get("title", "") or dialog["hwnd"]}']
            if checkbox_text:
                parts.append(f'Kontrol işlendi: {checkbox_text}')
            parts.append(f'Buton tıklandı: {button_text}')
            return True, ' | '.join(parts)

        if checkbox_text:
            return True, f'Pencere bulundu ve kontrol işlendi: {checkbox_text}'
        ok_enter, enter_msg = _press_enter(dialog['hwnd'])
        if ok_enter:
            return True, f'Pencere bulundu, varsayılan onay ENTER ile gönderildi ({enter_msg})'
        return False, 'Buton metni boş ve ENTER fallback başarısız.'

    if last_seen:
        btns = ', '.join(last_seen.get('buttons') or []) or '-'
        chks = ', '.join(last_seen.get('checkboxes') or []) or '-'
        rads = ', '.join(last_seen.get('radios') or []) or '-'
        detail = (
            f"Gorulen pencere: {last_seen.get('title', '') or '-'} | "
            f"butonlar: {btns} | checkboxlar: {chks} | radiolar: {rads}"
        )
        return False, f'{last_error} | {detail}'

    return False, last_error
