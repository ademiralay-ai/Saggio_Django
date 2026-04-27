import json

from django.core.management.base import BaseCommand

from core.firebase_service import SAPTemplateService
from core.models import SapProcess, SapProcessStep


class Command(BaseCommand):
    help = "Yapay Zeka Iade Sureci ve ilgili SAP sablonunu olusturur/gunceller."

    PROCESS_NAME = "Yapay Zeka Iade Sureci"
    TEMPLATE_NAME = "Yapay Zeka Iade Sablonu"

    def handle(self, *args, **options):
        raw = self._source_payload()
        template_state = self._build_template_state(raw)

        save_result = SAPTemplateService.save_template(self.TEMPLATE_NAME, template_state)
        if not save_result.get("ok"):
            self.stdout.write(self.style.ERROR(f"Sablon kaydedilemedi: {save_result.get('error') or 'bilinmeyen hata'}"))
            return

        proc, created = SapProcess.objects.get_or_create(
            name=self.PROCESS_NAME,
            defaults={
                "description": "Eski iade_sureci.py akisina gore olusturulan yeni surec.",
                "ghost_overlay_enabled": True,
                "office_express_auto_close": True,
            },
        )
        if not created:
            proc.description = "Eski iade_sureci.py akisina gore olusturulan yeni surec."
            proc.ghost_overlay_enabled = True
            proc.office_express_auto_close = True
            proc.save(update_fields=["description", "ghost_overlay_enabled", "office_express_auto_close", "updated_at"])

        steps = self._build_steps(raw)
        proc.steps.all().delete()
        for i, step in enumerate(steps):
            SapProcessStep.objects.create(
                process=proc,
                order=i,
                step_type=step["step_type"],
                label=step.get("label", ""),
                config=step.get("config", {}),
            )

        self.stdout.write(self.style.SUCCESS(f"Surec hazir: {proc.name} (id={proc.id})"))
        self.stdout.write(self.style.SUCCESS(f"Sablon: {self.TEMPLATE_NAME} | Kayit: {save_result.get('storage', 'unknown')}"))
        self.stdout.write(f"Adim sayisi: {len(steps)}")

    def _map_source_type(self, source_type, value):
        src = str(source_type or "").strip().casefold()
        if src == "dinamik tarih":
            return "dinamik"
        if src in ("cari kod", "satici kodu"):
            return "dongu"
        if src == "sabit deger":
            return "sabit"
        return "sabit"

    def _build_template_state(self, payload):
        conn = payload.get("connection", {}) if isinstance(payload.get("connection"), dict) else {}
        fields = payload.get("fields", {}) if isinstance(payload.get("fields"), dict) else {}

        rows = {}
        for element_id, meta in fields.items():
            if not isinstance(meta, dict):
                continue
            value = str(meta.get("value", "") or "")
            action_type = self._map_source_type(meta.get("source_type"), value)

            checked = False
            if action_type in ("dinamik", "dongu"):
                checked = True
            elif value.strip():
                checked = True
            elif str(meta.get("type", "") or "").casefold() == "guicheckbox" and value.strip().casefold() in ("x", "true", "1", "evet"):
                checked = True

            rows[str(element_id)] = {
                "checked": checked,
                "action_type": action_type,
                "value_text": value,
                "value_date": value if action_type == "dinamik" else "today",
                "value_select": "",
            }

        branch_list = payload.get("branch_list") or payload.get("account_list") or []
        if not isinstance(branch_list, list):
            branch_list = []
        loop_values = ",".join([str(x).strip() for x in branch_list if str(x).strip()])

        telegram = payload.get("telegram", {}) if isinstance(payload.get("telegram"), dict) else {}
        email_list = str(payload.get("email_list", "") or "").strip()

        return {
            "form": {
                "sys_id": str(conn.get("sys_id", "") or ""),
                "client": str(conn.get("client", "") or ""),
                "user": str(conn.get("user", "") or ""),
                "pwd": str(conn.get("pwd", "") or ""),
                "lang": str(conn.get("lang", "TR") or "TR"),
                "t_code": "ZSD0029",
                "extra_wait": "0",
                "loop_values": loop_values,
            },
            "notification": {
                "telegram_bot_id": "",
                "telegram_group_id": "",
                "mail_account_id": "",
                "telegram_start_message": "",
                "telegram_end_message": "",
                "mail_to": email_list,
                "mail_subject": "AI Iade Sureci Bildirimi",
                "mail_start_message": "",
                "mail_end_message": "",
                "legacy_telegram_chat_id": str(telegram.get("chat_id", "") or ""),
                "legacy_telegram_enabled": bool(telegram.get("enabled", True)),
            },
            "rows": rows,
        }

    def _build_steps(self, payload):
        email_list = str(payload.get("email_list", "") or "").strip()

        return [
            {
                "step_type": SapProcessStep.TYPE_SAP_FILL,
                "label": "1) ZSD0029 filtrelerini doldur",
                "config": {
                    "template_name": self.TEMPLATE_NAME,
                    "t_code_override": "ZSD0029",
                    "branch_loop_order": "template_loop_values",
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_RUN,
                "label": "2) F8 ile raporu calistir",
                "config": {"key": "F8", "delay_after_ms": 500},
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_BRANCH_NO_DATA_GUARD,
                "label": "3) Grid yoksa sonraki subeye gec ve tekrar baslat",
                "config": {
                    "grid_id": "wnd[0]/usr/cntlGRID1/shellcont/shell",
                    "timeout_sec": 5,
                    "restart_step_order": 1,
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_POPUP_DECIDE,
                "label": "4) Masum popup varsa kapat",
                "config": {
                    "popup_root_id": "wnd[1]",
                    "popup_action": "close_enter",
                    "fail_if_not_found": False,
                    "fail_if_not_match": False,
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_SELECT_ROW,
                "label": "5) Ilk satiri sec",
                "config": {
                    "grid_id": "wnd[0]/usr/cntlGRID1/shellcont/shell",
                    "row_index": 1,
                    "wait_timeout_sec": 25,
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_PRESS_BUTTON,
                "label": "6) Iade olusturma adimi (btn[13])",
                "config": {
                    "button_id": "wnd[0]/tbar[1]/btn[13]",
                    "wait_timeout_sec": 25,
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_POPUP_DECIDE,
                "label": "7) Referans/Fatura popup kontrol",
                "config": {
                    "popup_root_id": "wnd[1]",
                    "popup_text_contains": "referans",
                    "popup_action": "press_button_id",
                    "popup_button_id": "wnd[1]/usr/btnBUTTON_2",
                    "send_mail_on_match": True,
                    "mail_account_id": "",
                    "mail_to": email_list,
                    "mail_subject": "Iade sureci popup uyarisi",
                    "mail_body": "Referans popup tespit edildi. Manuel kontrol gerekir.",
                    "fail_if_not_found": False,
                    "fail_if_not_match": False,
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_PRESS_BUTTON,
                "label": "8) Sonraki adim (btn[2])",
                "config": {
                    "button_id": "wnd[0]/tbar[1]/btn[2]",
                    "wait_timeout_sec": 25,
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_POPUP_DECIDE,
                "label": "9) Devam popupinda karar",
                "config": {
                    "popup_root_id": "wnd[1]",
                    "popup_text_contains": "devam",
                    "popup_action": "press_button_id",
                    "popup_button_id": "wnd[1]/usr/btnBUTTON_2",
                    "send_mail_on_match": True,
                    "mail_account_id": "",
                    "mail_to": email_list,
                    "mail_subject": "Iade sureci karar popupi",
                    "mail_body": "Devam popupi geldi, BUTTON_2 ile aksiyon uygulandi.",
                    "fail_if_not_found": False,
                    "fail_if_not_match": False,
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_PRESS_BUTTON,
                "label": "10) Popup DVM butonu",
                "config": {
                    "button_id": "wnd[1]/usr/btnDVM",
                    "wait_timeout_sec": 25,
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_PRESS_BUTTON,
                "label": "11) Kaydet (btn[17])",
                "config": {
                    "button_id": "wnd[0]/tbar[1]/btn[17]",
                    "wait_timeout_sec": 25,
                },
            },
            {
                "step_type": SapProcessStep.TYPE_SAP_POPUP_DECIDE,
                "label": "12) Kaydetme sonrasi popup kontrolu",
                "config": {
                    "popup_root_id": "wnd[1]",
                    "popup_action": "press_button_id",
                    "popup_button_id": "wnd[1]/usr/btnBUTTON_2",
                    "send_mail_on_match": True,
                    "mail_account_id": "",
                    "mail_to": email_list,
                    "mail_subject": "Iade sureci kaydetme popupi",
                    "mail_body": "Kaydetme sonrasi popup tespit edildi.",
                    "fail_if_not_found": False,
                    "fail_if_not_match": False,
                },
            },
        ]

    def _source_payload(self):
        raw = {
            "connection": {
                "sys_id": "00-A-Robot-app02",
                "client": "300",
                "user": "ademiralay",
                "pwd": "aa118755",
                "lang": "TR",
            },
            "telegram": {
                "enabled": True,
                "chat_id": "-1003335111711",
            },
            "fields": {
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtS_ERDAT-LOW": {"source_type": "Dinamik Tarih", "value": "15 Gün Önce", "name": "Yaratma tarihi", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtS_ERDAT-HIGH": {"source_type": "Dinamik Tarih", "value": "Bugün", "name": "son", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtS_WERKS-LOW": {"source_type": "Cari Kod", "value": "LOOP_ITEM", "name": "Üretim yeri", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtS_ECZANE-LOW": {"source_type": "Sabit Değer", "value": "", "name": "Eczane Kodu", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtS_ECZANE-HIGH": {"source_type": "Sabit Değer", "value": "", "name": "son", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtS_MATNR-LOW": {"source_type": "Sabit Değer", "value": "", "name": "Malzeme", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtS_MATNR-HIGH": {"source_type": "Sabit Değer", "value": "", "name": "son", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtP_VKORG": {"source_type": "Sabit Değer", "value": "", "name": "Satış organizasyonu", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtP_VTWEG": {"source_type": "Sabit Değer", "value": "", "name": "Dağıtım kanalı", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtP_SPART": {"source_type": "Sabit Değer", "value": "", "name": "Bölüm", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/chkP_INC": {"source_type": "Sabit Değer", "value": "", "name": "P_INC", "type": "GuiCheckBox"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtS_VBELN-LOW": {"source_type": "Sabit Değer", "value": "", "name": "Teklif", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/ctxtS_VBELN-HIGH": {"source_type": "Sabit Değer", "value": "", "name": "son", "type": "GuiCTextField"},
                "/app/con[0]/ses[0]/wnd[0]/usr/chkP_JOB": {"source_type": "Sabit Değer", "value": "", "name": "P_JOB", "type": "GuiCheckBox"},
            },
            "branch_list": [
                "1100", "1101", "1104", "1105", "1106", "1107", "1108", "1109", "1111", "1112", "1114", "1115", "1116", "1117", "1118", "1119", "1121", "1123", "1124", "1125", "1126", "1127", "1128", "1129", "1130", "1131", "1132", "1194"
            ],
            "email_list": "yedorbay@bek.org.tr",
        }
        return raw
