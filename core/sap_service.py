import os
import subprocess
import time
import xml.etree.ElementTree as ET


class SAPScanService:
    def __init__(self):
        self.session = None

    def _get_application(self):
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                sap_gui_auto = win32com.client.GetObject("SAPGUI")
                return sap_gui_auto.GetScriptingEngine, None
            except Exception:
                saplogon_path = r"C:\Program Files (x86)\SAP\FrontEnd\SAPgui\saplogon.exe"
                subprocess.Popen(saplogon_path)
                for _ in range(20):
                    time.sleep(1)
                    try:
                        sap_gui_auto = win32com.client.GetObject("SAPGUI")
                        return sap_gui_auto.GetScriptingEngine, None
                    except Exception:
                        continue
                return None, "SAP GUI acilamadi veya scripting erisimi yok."
        except ModuleNotFoundError as ex:
            return None, (
                "SAP kutuphane eksigi: pywin32 yuklenmeli. "
                f"Detay: {ex}"
            )
        except Exception as ex:
            return None, f"SAP baglantisi icin gerekli kutuphane hatasi: {ex}"

    def get_system_list(self):
        """SAP Logon landscape dosyalarindan sistem adlarini okur."""
        systems = []
        seen = set()

        candidates = [
            os.path.join(os.getenv("APPDATA", ""), "SAP", "Common", "SAPUILandscape.xml"),
            os.path.join(os.getenv("APPDATA", ""), "SAP", "Common", "SAPUILandscapeGlobal.xml"),
        ]

        for path in candidates:
            if not path or not os.path.exists(path):
                continue
            try:
                root = ET.parse(path).getroot()
                for elem in root.iter():
                    tag = elem.tag.lower()
                    if not any(t in tag for t in ("service", "item", "msgserver", "router")):
                        continue
                    name = str(elem.attrib.get("name", "") or "").strip()
                    if not name:
                        continue
                    key = name.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    systems.append(name)
            except Exception:
                continue

        if systems:
            systems.sort(key=lambda x: x.casefold())
            return systems

        # Fallback: acik baglantilardan description topla
        application, err = self._get_application()
        if err or not application:
            return []
        try:
            for conn in application.Children:
                name = str(getattr(conn, "Description", "") or "").strip()
                if not name:
                    continue
                key = name.casefold()
                if key in seen:
                    continue
                seen.add(key)
                systems.append(name)
        except Exception:
            pass

        systems.sort(key=lambda x: x.casefold())
        return systems

    def _get_or_open_connection(self, application, sys_id):
        connection = None
        try:
            for conn in application.Children:
                if getattr(conn, "Description", "") == sys_id:
                    connection = conn
                    break
        except Exception:
            connection = None

        if connection is None:
            try:
                connection = application.OpenConnection(sys_id, True)
            except Exception as ex:
                return None, f"Sistem bulunamadi: {sys_id}. Detay: {ex}"

        return connection, None

    def _safe_find(self, session, element_id):
        try:
            return session.findById(element_id, False)
        except Exception:
            return None

    def _is_login_screen(self, session):
        return bool(
            self._safe_find(session, "wnd[0]/usr/txtRSYST-BNAME")
            and self._safe_find(session, "wnd[0]/usr/pwdRSYST-BCODE")
            and self._safe_find(session, "wnd[0]/usr/txtRSYST-MANDT")
        )

    def _get_status_text(self, session):
        try:
            sbar = self._safe_find(session, "wnd[0]/sbar/pane[0]")
            if sbar:
                return str(getattr(sbar, "Text", "") or "").strip()
        except Exception:
            pass
        return ""

    def _get_window_title(self, session):
        try:
            wnd = self._safe_find(session, "wnd[0]")
            if wnd:
                return str(getattr(wnd, "Text", "") or "").strip()
        except Exception:
            pass
        return ""

    def _is_command_ready(self, session):
        return bool(self._safe_find(session, "wnd[0]/tbar[0]/okcd"))

    def _pick_best_session(self, connection):
        """Dogru session'i sec: once login ekrani, sonra komut bari hazir session."""
        try:
            children_count = int(connection.Children.Count)
        except Exception:
            children_count = 0

        if children_count <= 0:
            return None

        sessions = []
        for idx in range(children_count):
            try:
                sessions.append(connection.Children(idx))
            except Exception:
                continue

        # Login ekranini bulursak onu kullan.
        for s in sessions:
            if self._is_login_screen(s):
                return s

        # Komut bari hazir olan bir session varsa onu kullan.
        for s in sessions:
            if self._is_command_ready(s):
                return s

        # Son care: ilk session.
        return sessions[0]

    def _login_if_needed(self, session, client, user, pwd, lang="TR"):
        # Login ekranina gelmissek alanlari doldur, degilsek mevcut oturumla devam et.
        if not self._is_login_screen(session):
            return

        try:
            session.findById("wnd[0]/usr/txtRSYST-BNAME").text = str(user or "")
            session.findById("wnd[0]/usr/pwdRSYST-BCODE").text = str(pwd or "")
            session.findById("wnd[0]/usr/txtRSYST-MANDT").text = str(client or "")
            lang_box = self._safe_find(session, "wnd[0]/usr/txtRSYST-LANGU")
            if lang_box:
                lang_box.text = str(lang or "TR")
            session.findById("wnd[0]").sendVKey(0)
            self._wait_until_idle(session, timeout_sec=20)
        except Exception:
            pass

        try:
            if session.Children.Count > 1:
                popup = session.findById("wnd[1]")
                popup.findById("usr/radMULTI_LOGON_OPT2").select()
                popup.findById("tbar[0]/btn[0]").press()
        except Exception:
            pass

    def _wait_until_idle(self, session, timeout_sec=30, stable_checks=2):
        deadline = time.time() + timeout_sec
        stable_count = 0
        while time.time() < deadline:
            try:
                if not session.Busy:
                    stable_count += 1
                    if stable_count >= stable_checks:
                        return True
                    time.sleep(0.15)
                else:
                    stable_count = 0
                    time.sleep(0.2)
            except Exception:
                time.sleep(0.2)
        return False

    def _wait_for_element(self, session, element_id, timeout_sec=30):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            self._wait_until_idle(session, timeout_sec=3, stable_checks=1)
            try:
                obj = session.findById(element_id, False)
                if obj:
                    return obj
            except Exception:
                pass
            time.sleep(0.2)
        return None

    def _apply_extra_wait(self, extra_wait):
        try:
            value = float(extra_wait)
        except (TypeError, ValueError):
            value = 0.0

        if value > 0:
            time.sleep(min(max(value, 0.0), 5.0))

    def _go_tcode(self, session, t_code):
        if not t_code:
            return
        self._wait_until_idle(session, timeout_sec=20)
        okcd = self._wait_for_element(session, "wnd[0]/tbar[0]/okcd", timeout_sec=20)
        if not okcd:
            raise RuntimeError("Komut alani (okcd) hazir degil.")
        session.findById("wnd[0]/tbar[0]/okcd").text = f"/n{t_code}"
        session.findById("wnd[0]").sendVKey(0)
        self._wait_until_idle(session, timeout_sec=30)

    # SAP'de ComboBox/ListBox girileri olan tipler
    _COMBO_TYPES = {"GuiComboBox", "GuiComboBoxEntry"}

    def _read_entries(self, sap_obj):
        """GuiComboBox gibi elemanlarin Entries koleksiyonunu okur."""
        entries = []
        seen = set()

        def _add_entry(key, value):
            k = str(key or "").strip()
            v = str(value or "").strip()
            if not k and not v:
                return
            if not k:
                k = v
            token = (k, v)
            if token in seen:
                return
            seen.add(token)
            entries.append({"key": k, "value": v})

        try:
            obj_type = str(getattr(sap_obj, "Type", ""))
            if obj_type not in self._COMBO_TYPES:
                return entries
            entries_col = sap_obj.Entries

            # COM koleksiyonu farkli SAP surumlerinde farkli sekilde expose edilebilir.
            try:
                count = int(entries_col.Count)
            except Exception:
                try:
                    count = int(entries_col.count)
                except Exception:
                    count = 0

            def _get_entry(i):
                getters = (
                    lambda: entries_col(i),
                    lambda: entries_col(i + 1),
                    lambda: entries_col.Item(i),
                    lambda: entries_col.Item(i + 1),
                    lambda: entries_col.Item(str(i)),
                    lambda: entries_col.Item(str(i + 1)),
                    lambda: entries_col.ElementAt(i),
                )
                for g in getters:
                    try:
                        return g()
                    except Exception:
                        continue
                return None

            for i in range(count):
                try:
                    entry = _get_entry(i)
                    if entry is None:
                        continue
                    key = getattr(entry, "Key", None)
                    if key is None:
                        key = getattr(entry, "key", "")
                    value = getattr(entry, "Value", None)
                    if value is None:
                        value = getattr(entry, "Text", None)
                    if value is None:
                        value = getattr(entry, "value", None)
                    if value is None:
                        value = getattr(entry, "text", "")
                    _add_entry(key, value)
                except Exception:
                    pass

            # Bazı COM sürümlerinde koleksiyon yalnızca iterable olarak gelebiliyor.
            if not entries:
                try:
                    for entry in entries_col:
                        key = getattr(entry, "Key", None)
                        if key is None:
                            key = getattr(entry, "key", "")
                        value = getattr(entry, "Value", None)
                        if value is None:
                            value = getattr(entry, "Text", None)
                        if value is None:
                            value = getattr(entry, "value", None)
                        if value is None:
                            value = getattr(entry, "text", "")
                        _add_entry(key, value)
                except Exception:
                    pass

            # Son care: bazi ortamlarda tek bir metin listesi property'de tutulabiliyor.
            if not entries:
                try:
                    raw = str(getattr(sap_obj, "List", "") or "")
                    if raw:
                        parts = [p.strip() for p in raw.replace("\r", "").split("\n") if p.strip()]
                        for p in parts:
                            _add_entry(p, p)
                except Exception:
                    pass
        except Exception:
            pass
        return entries

    def _scan_recursive(self, sap_obj, found_list, level=0):
        try:
            entries = self._read_entries(sap_obj)
            found_list.append(
                {
                    "id": str(getattr(sap_obj, "Id", "")),
                    "type": str(getattr(sap_obj, "Type", "")),
                    "name": str(getattr(sap_obj, "Name", "")),
                    "text": str(getattr(sap_obj, "Text", "")),
                    "changeable": bool(getattr(sap_obj, "Changeable", False)),
                    "level": level,
                    "entries": entries,
                }
            )
        except Exception:
            pass

        try:
            if hasattr(sap_obj, "Children"):
                for child in sap_obj.Children:
                    self._scan_recursive(child, found_list, level + 1)
        except Exception:
            pass

    def scan_screen(self, sys_id, client, user, pwd, t_code, root_id="wnd[0]", extra_wait=0, lang="TR"):
        application, err = self._get_application()
        if err:
            return False, err

        connection, err = self._get_or_open_connection(application, sys_id)
        if err:
            return False, err

        try:
            self.session = self._pick_best_session(connection)
            if self.session is None:
                return False, "Uygun SAP session bulunamadi."
        except Exception as ex:
            return False, f"Session acilamadi: {ex}"

        self._wait_until_idle(self.session, timeout_sec=20)

        self._login_if_needed(self.session, client, user, pwd, lang=lang)

        # Login denemesi sonrasinda komut bari hazir degilse bir sure daha bekle.
        if not self._is_command_ready(self.session):
            self._wait_for_element(self.session, "wnd[0]/tbar[0]/okcd", timeout_sec=20)

        # Hala login ekranindaysa veya status bar hata veriyorsa, kullaniciya net sebep don.
        if self._is_login_screen(self.session):
            title = self._get_window_title(self.session)
            status = self._get_status_text(self.session)

            if "yeni parola" in title.lower():
                return False, (
                    "SAP girisi Yeni parola ekranina dustu. Bu kullanici icin sifre degisimi gerekiyor. "
                    "Once SAP'de manuel sifre degistirip tekrar dene."
                )

            if status:
                return False, f"SAP girisi tamamlanmadi. Durum: {status}"

            return False, "SAP girisi tamamlanmadi. Kullanici/sifre/client/dil bilgilerini kontrol et."

        status_after_login = self._get_status_text(self.session)
        if status_after_login and "islev olanaksiz" in status_after_login.lower():
            return False, (
                "SAP Islev olanaksiz hatasi verdi. Genellikle login tamamlanmadan komut denenir veya bilgiler uyumsuz olur. "
                f"Durum: {status_after_login}"
            )

        self._apply_extra_wait(extra_wait)

        try:
            self._go_tcode(self.session, t_code)
        except Exception as ex:
            return False, f"T-Code acilirken hata: {ex}"

        self._apply_extra_wait(extra_wait)

        root = self._wait_for_element(self.session, root_id or "wnd[0]", timeout_sec=30)
        if not root:
            return False, f"Kok alan bulunamadi ({root_id}). Ekran henuz acilmamis olabilir."

        self._apply_extra_wait(extra_wait)

        found = []
        self._scan_recursive(root, found, level=0)
        return True, found

    def close_all_sap_windows(self):
        """Açık tüm SAP pencerelerini kapatıp oturumu sonlandırır."""
        if self.session is None:
            return
        
        try:
            # /nex komutu ile SAP'tan çık
            okcd = self._safe_find(self.session, "wnd[0]/tbar[0]/okcd")
            if okcd:
                okcd.text = "/nex"
                self.session.findById("wnd[0]").sendVKey(0)
                time.sleep(1)
        except Exception:
            pass
        
        try:
            # Kalan pencere varsa ALT+F4 gönder
            children = getattr(self.session, "Children", None)
            if children is not None:
                count = int(getattr(children, "Count", 0) or 0)
                for idx in range(count):
                    try:
                        wnd = children(idx)
                        if wnd:
                            wnd.sendKey(4)  # ALT+F4
                    except Exception:
                        try:
                            wnd = children.Item(idx)
                            if wnd:
                                wnd.sendKey(4)
                        except Exception:
                            pass
            time.sleep(0.5)
        except Exception:
            pass
        
        self.session = None

    def apply_to_screen(self, sys_id, client, user, pwd, actions, t_code="", root_id="wnd[0]", extra_wait=0, lang="TR", execute_f8=False):
        """
        actions: [{"element_id": "wnd[0]/...", "action_type": "sabit|dinamik|radio|chk|secilecek|selectbox", "value": "..."}]
        """
        application, err = self._get_application()
        if err:
            return False, err

        connection, err = self._get_or_open_connection(application, sys_id)
        if err:
            return False, err

        try:
            self.session = self._pick_best_session(connection)
            if self.session is None:
                return False, "Uygun SAP session bulunamadi."
        except Exception as ex:
            return False, f"Session acilamadi: {ex}"

        self._wait_until_idle(self.session, timeout_sec=20)
        self._login_if_needed(self.session, client, user, pwd, lang=lang)

        if not self._is_command_ready(self.session):
            self._wait_for_element(self.session, "wnd[0]/tbar[0]/okcd", timeout_sec=20)

        if self._is_login_screen(self.session):
            return False, "SAP girisi tamamlanmadi."

        self._apply_extra_wait(extra_wait)

        if t_code:
            try:
                self._go_tcode(self.session, t_code)
            except Exception as ex:
                return False, f"T-Code acilirken hata: {ex}"

        self._apply_extra_wait(extra_wait)

        results = []
        for action in actions:
            element_id  = action.get("element_id", "")
            action_type = action.get("action_type", "")
            value       = action.get("value", "")

            if not element_id:
                continue

            try:
                obj = self._safe_find(self.session, element_id)
                if obj is None:
                    results.append({"id": element_id, "ok": False, "msg": "Element bulunamadi"})
                    continue

                if action_type in ("sabit", "dinamik", "dongu"):
                    obj.text = str(value)
                    results.append({"id": element_id, "ok": True, "msg": f"Deger yazildi: {value}"})

                elif action_type == "selectbox":
                    obj.key = str(value)
                    results.append({"id": element_id, "ok": True, "msg": f"Secildi: {value}"})

                elif action_type == "chk":
                    obj.selected = not bool(getattr(obj, "selected", False))
                    results.append({"id": element_id, "ok": True, "msg": "Checkbox toggle edildi"})

                elif action_type in ("radio", "secilecek"):
                    try:
                        obj.select()
                    except Exception:
                        obj.setFocus()
                    results.append({"id": element_id, "ok": True, "msg": "Secildi/tiklandi"})

                else:
                    results.append({"id": element_id, "ok": False, "msg": f"Bilinmeyen aksiyon: {action_type}"})

            except Exception as ex:
                results.append({"id": element_id, "ok": False, "msg": str(ex)})

        if execute_f8:
            try:
                self._wait_until_idle(self.session, timeout_sec=15)
                self.session.findById("wnd[0]").sendVKey(8)
                self._wait_until_idle(self.session, timeout_sec=30)
                status = self._get_status_text(self.session)
                msg = "Calistirildi (F8)"
                if status:
                    msg = f"{msg} - Durum: {status}"
                results.append({"id": "wnd[0]", "ok": True, "msg": msg})
            except Exception as ex:
                results.append({"id": "wnd[0]", "ok": False, "msg": f"F8 hatasi: {ex}"})

        return True, results
