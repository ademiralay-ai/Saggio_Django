import re


def sap_key_to_sendkeys_token(key_name):
    """Convert user-friendly key names to WScript.Shell SendKeys tokens."""
    key = str(key_name or "").strip()
    if not key:
        return ""
    upper = key.upper()

    if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", upper):
        return "{" + upper + "}"

    special = {
        "ENTER": "{ENTER}",
        "ESC": "{ESC}",
        "ESCAPE": "{ESC}",
        "TAB": "{TAB}",
        "SPACE": " ",
        "BACKSPACE": "{BACKSPACE}",
        "DELETE": "{DELETE}",
        "INSERT": "{INSERT}",
        "HOME": "{HOME}",
        "END": "{END}",
        "PAGEUP": "{PGUP}",
        "PAGEDOWN": "{PGDN}",
        "UP": "{UP}",
        "DOWN": "{DOWN}",
        "LEFT": "{LEFT}",
        "RIGHT": "{RIGHT}",
        "PRINTSCREEN": "{PRTSC}",
    }
    if upper in special:
        return special[upper]

    if len(key) == 1:
        if key in "{}+^%~()[]":
            return "{" + key + "}"
        return key

    return key


def build_sendkeys_from_config(combo_text="", key="", use_ctrl=False, use_alt=False, use_shift=False, use_win=False):
    """Build WScript.Shell SendKeys sequence from UI config values."""
    raw_combo = str(combo_text or "").strip()
    if raw_combo:
        parts = [p.strip() for p in re.split(r"[+]", raw_combo) if p.strip()]
        if not parts:
            return ""
        mods = []
        base = ""
        for p in parts:
            u = p.upper()
            if u in ("CTRL", "CONTROL"):
                mods.append("^")
            elif u == "ALT":
                mods.append("%")
            elif u == "SHIFT":
                mods.append("+")
            elif u in ("WIN", "WINDOWS", "META"):
                continue
            else:
                base = sap_key_to_sendkeys_token(p)
        if not base:
            base = sap_key_to_sendkeys_token(parts[-1])
        return "".join(mods) + base

    prefix = ""
    if bool(use_ctrl):
        prefix += "^"
    if bool(use_alt):
        prefix += "%"
    if bool(use_shift):
        prefix += "+"
    return prefix + sap_key_to_sendkeys_token(key)
