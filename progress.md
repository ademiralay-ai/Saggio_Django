# Saggio RPA — İlerleme Kayıt Noktası (Progress / Save Point)

> **Kullanım:** Sohbet reset protokolü. Yeni sohbete geçerken `"progress.md'den devam et"` de.
> AI bu dosyayı okuyarak son duruma kalır kalmaz devam eder.

**Son güncelleme:** 30 Nisan 2026 — **REFACTOR TAMAMLANDI** ✅ (Adım 7 + 8). `core/views.py` artık `core/views/` paketi (pages.py + contacts.py + __init__.py re-export). Dashboard runserver smoke testi 200 OK.

---

## 1. Şu Ana Kadar Tamamlananlar

### Yedeklemeler
- **Lokal zip yedek:** `C:\Util\SaggioDjango_Backups\SaggioDjango_20260430_133707.zip` (~177 MB; `.venv` hariç tüm kod + 3 SQLite DB + firebase-key)
- **GitHub backup branch:** [`backup/pre-views-split-20260430_133749`](https://github.com/ademiralay-ai/Saggio_Django/tree/backup/pre-views-split-20260430_133749) — kod + DB'ler (firebase-key.json Push Protection nedeniyle push edilmedi, lokal yedekte mevcut)
- `main` dalına henüz refactor commit'i atılmadı; tüm değişiklikler working tree'de duruyor.

### Refactor Adım 1 — `core/utils/` paketi ✅
- `core/views.py`: 7302 → 6928 satır (-374 satır)
- Oluşturulan modüller:
  - `core/utils/__init__.py`
  - `core/utils/runtime_state.py` — `_PROCESS_RUNTIME`, `_PROCESS_RUNTIME_LOCK`, `_runtime_init/get/touch/set_controls/set_step/push_log/finish`
  - `core/utils/date_utils.py` — `_calc_dynamic_date`
  - `core/utils/placeholders.py` — `_resolve_placeholders`
  - `core/utils/http_utils.py` — `_read_json_body`, `_request_ip`
  - `core/utils/parsing.py` — `_re`, `_normalize_session_element_id`, `_parse_toolbar_context_command`, `_is_menu_target`, `_invoke_button_or_menu`, `_parse_loop_values`, `_as_bool`, `_parse_decimal_text`, `_resolve_step_no_to_index`, `_resolve_step_target_index`, `_resolve_rule_target_index`, `_normalize_match_text`, `_normalize_allowed_user_ids`, `_safe_release_version`, `_extract_telegram_http_error`
- `core/views.py` üst kısmında `from .utils.* import ...` ile re-import — geri uyum korundu.
- Doğrulama: `python manage.py check` → "no issues".

### Refactor Adım 2 — `core/gui/` paketi ✅
- `core/views.py`: 6928 → 6418 satır (-510 satır)
- Oluşturulan modüller:
  - `core/gui/__init__.py`
  - `core/gui/blocking_dialog.py` — `_show_blocking_message_dialog`
  - `core/gui/ghost_overlay.py` — `_GhostOverlayWindow` (~530 satırlık Tk overlay sınıfı; `runtime_state` helper'larını yeni paketten import eder)
- `core/views.py` üst kısmına `from .gui.blocking_dialog import _show_blocking_message_dialog` ve `from .gui.ghost_overlay import _GhostOverlayWindow` eklendi.
- Eski tanımlar PowerShell ile satır 2569-3131 arasından temiz silindi.
- Not: `core/views.py` içindeki `import tkinter as tk` / `tk_messagebox` import'ları **bilinçli korundu** (Excel sheet picker dialog'unda hala kullanılıyor — Adım 3'te dahil edilebilir).
- Doğrulama: `python manage.py check` → "no issues".

### Refactor Adım 3 — `core/services/` 1. parti ✅
- `core/views.py`: 6418 → 5515 satır (-903 satır)
- Oluşturulan modüller:
  - `core/services/__init__.py`
  - `core/services/excel_service.py` — 9 fonksiyon (cursor + value resolution)
  - `core/services/ftp_service.py` — `_ftp_list_files`, `_ftp_download`, `_ftp_upload`
  - `core/services/notification_service.py` — 9 fonksiyon (telegram/mail/ftp test + send + `_notify_sap_event` + `_generate_row_report_xlsx` + `_safe_send_popup_mail`)
- `core/views.py` üst kısmına `from .services.* import ...` ile re-import — geri uyum korundu.
- Doldurma Python script'iyle atomik yapıldı (PowerShell satır-aralığı yerine), encoding (UTF-8 BOM) korundu.
- Doğrulama: `python manage.py check` → "no issues"; tüm semboller `from core import views` ile hâlâ erişilebilir.

### Refactor Adım 4 — `core/services/` 2. parti (SAP runtime) ✅
- `core/views.py`: 5515 → 4693 satır (-822 satır)
- Oluşturulan modüller:
  - `core/services/sap_runtime_service.py` — 11 fn (`_read_sap_element_text`, `_read_sap_statusbar`, `_ensure_runtime_loop_state`, `_iter_children`, `_build_actions_from_template_state_with_runtime`, `_send_sap_hotkey`, `_extract_runtime_steps`, `_resolve_connection_from_steps`, `_find_loop_next_step_index`, `_advance_loop_runtime`, `_advance_excel_loop_runtime`)
  - `core/services/sap_grid_service.py` — 6 fn (`find_alv_grid`, `_get_grid_row_count`, `_resolve_grid_row_by_text`, `_read_grid_row_data`, `_select_row_on_grid`, `_find_grid`)
  - `core/services/sap_popup_service.py` — 7 fn (`_close_office_express_popups`, `_has_popup_window`, `_collect_node_text`, `_collect_popup_message_text`, `_collect_popup_text_legacy`, `_press_popup_button_by_text`, `_popup_has_button_by_text`)
- Cross-paket import: grid + popup `from .sap_runtime_service import _iter_children`.
- `core/views.py` re-import — geri uyum tam.
- Doğrulama: `python manage.py check` → "no issues"; tüm 24 sembol `from core import views` ile hâlâ erişilebilir.

### Refactor Adım 5 — `core/services/` 3. parti (telegram + robot_release) ✅
- `core/views.py`: 4693 → 4527 satır (-166 satır)
- Oluşturulan modüller:
  - `core/services/telegram_service.py` — 7 fn (`_is_user_allowed_for_bot`, `_telegram_api_call`, `_telegram_send_with_keyboard`, `_telegram_answer_callback`, `_render_menu_inline_keyboard`, `_trigger_sap_process_for_telegram`, `process_telegram_update`)
  - `core/services/robot_release_service.py` — 4 fn (`_authenticate_agent`, `_serialize_job`, `_package_zip_path`, `_create_agent_event`)
- **İlk denemede yan etki:** Ekstrakt sınırı `process_telegram_update` başlangıcından bir satır geri kaydı; `@csrf_exempt` dekoratörü tarafından `telegram_bot_webhook` view'ından koparak telegram_service'e düştü → `manage.py check` `NameError: csrf_exempt`. Düzeltme: dekoratör telegram_service'ten silindi ve views.py'da `telegram_bot_webhook` üzerine geri eklendi.
- Doğrulama: `python manage.py check` → "no issues"; tüm 12 sembol re-export ile erişilebilir.

### Toplam refactor ilerlemesi
- `core/views.py`: 7302 → 529 satır (**-6773 satır, %93 azalma**)
- Yeni paket yapısı: `core/utils/` (5 modül), `core/gui/` (2 modül), `core/services/` (8 modül), `core/api/` (7 modül)

### Refactor Adım 6 — `core/api/` paketi ✅
- `core/views.py`: 4527 → 529 satır (-3998 satır)
- Oluşturulan modüller:
  - `core/api/__init__.py`
  - `core/api/telegram_webhook_api.py` — 10 fn (telegram_bot_studio + menu_save/menus/menu_delete/simulate + bot_save/set_webhook/webhook_info/delete_webhook + telegram_bot_webhook)
  - `core/api/robot_agent_api.py` — 6 fn (agent_register/heartbeat/check_update/log_event/pull_job/job_update; ajan tarafı endpoints)
  - `core/api/robot_admin_api.py` — 14 fn (robot_agent_status/job_list/event_list, release_list/save/download/download_package/deploy, build_setup_exe, build_install_package, set_desired_version, agent_upsert, cancel_job, dispatch_job)
  - `core/api/sap_template_api.py` — 7 fn (sap_scan + sap_apply + sap_run + sap_template_list/get/save/delete)
  - `core/api/sap_process_api.py` — 12 fn (sap_process_list/builder/backup/delete/step_save/rename + runtime_settings_save/runtime_control/runtime_status + excel_browse/sheets/columns)
  - `core/api/sap_scan_api.py` — 8 fn (_sap_process_scan_popups_impl + sap_process_scan_popups + scan_buttons/selectables/inputs/windows_dialogs/screens/grids)
  - `core/api/sap_runtime_api.py` — 1 fn (sap_process_run_preview ~2000 satır; en büyük endpoint)
- Sub-step yaklaşımı: 6a→6g sırayla (en küçükten en büyüğe). Her adım ayrı bir Python script ile atomik extract + re-import + `manage.py check` doğrulaması.
- `core/views.py` üst kısmında `from .api.* import ...` ile re-import — `core/urls.py` değişmedi (geri uyum tam).
- Doğrulama: `python manage.py check` → "no issues"; 69 view sembolü `from core import views` ile hâlâ erişilebilir; `from core import urls` import OK.

### Yönetim dosyaları
- `RULES.md` — proje kuralları, mimari, AI çalışma protokolü, sohbet reset.
- `.aiignore` — context'e girmemesi gereken dosyalar.
- `progress.md` — bu dosya.

---

## 2. Şu An Üzerinde Çalışılan İş

### `core/views.py` Refactor — Adım 7: `core/views/` paketi

**Hedef:** Kalan ~530 satırı (HTML render eden page view'lar + helper'lar) `core/views/` paketine bölmek. Sonra `core/views.py` ya silinecek ya da yalnızca re-export içeren ince bir `__init__.py` olacak.

**Kalan içerik (`core/views.py` 529 satır):**
- Üstte: tüm `from .utils/.gui/.services/.api/...` re-import'ları (~140 satır)
- Helper: `get_dashboard_stats()`, `_manage_contact_entity(...)`
- Sayfa view'ları: `dashboard`, `robots`, `processes`, `queues`, `scheduler`, `reports`, `settings_page`, `robot_control_center`
- Contact yönetim view'ları: `telegram_bots_manage`, `telegram_groups_manage`, `mail_accounts_manage`, `ftp_accounts_manage`

**Önerilen modüller:**
- `core/views/pages.py` — dashboard + robots + processes + queues + scheduler + reports + settings_page + robot_control_center + `get_dashboard_stats`
- `core/views/contacts.py` — telegram_bots_manage + telegram_groups_manage + mail_accounts_manage + ftp_accounts_manage + `_manage_contact_entity`
- `core/views/__init__.py` — tüm api/services/utils/gui re-export'ları (geri uyum)
- Eski `core/views.py` silinecek (Django paket olarak `views/` dizinini bulacak).

---

## 3. Yapılacaklar (TODO)

### Refactor Sırası (Onaylanmış Plan)
- [x] **Adım 1:** `core/utils/`
- [x] **Adım 2:** `core/gui/`
- [x] **Adım 3:** `core/services/` — `notification_service.py`, `ftp_service.py`, `excel_service.py`
- [x] **Adım 4:** `core/services/` — `sap_grid_service.py`, `sap_popup_service.py`, `sap_runtime_service.py` (sap_process_run_preview'in iş mantığı)
- [x] **Adım 5:** `core/services/` — `telegram_service.py`, `robot_release_service.py`
- [x] **Adım 6:** `core/api/` paketi — telegram_webhook + robot_agent + robot_admin + sap_template + sap_process + sap_scan + sap_runtime
- [x] **Adım 7:** `core/views/` paketi — pages.py + contacts.py + `__init__.py` re-export (eski `views.py` silindi)
- [x] **Adım 8:** Final smoke test — `manage.py check` no issues + `runserver` 127.0.0.1:8765 + `GET /` → 200 (36 KB dashboard render)
- [ ] (Opsiyonel) `core/urls.py` import yollarını yeni paketlere taşı (geri uyum re-export sayesinde gerekli değil).

### Refactor Sonrası (Ayrı Bakım)
- [ ] **Robot ajan iş gönderememe sorunu** — Ekran görüntüsünde `ConnectionRefusedError: localhost:8000`. Ajan farklı makinedeyse `agent_runtime.py` config'indeki `server_url` host IP'sine çevrilmeli; ayrıca `manage.py runserver 0.0.0.0:8000` ile dış erişim açılmalı + Windows Defender Firewall kuralı.
- [ ] **Subprocess UnicodeDecodeError (`cp1254`)** — `agent_runtime.py` log thread'inde `_readerthread`'in encoding'i `utf-8`'e zorlanmalı.
- [ ] Üretim deploy testi (Plesk + Passenger).
- [ ] Telegram webhook canlı test (TLS sertifikası gereksinimi).

---

## Notlar (Tarihçe)

- **30/04/2026 (1)** — Plan onaylandı, yedekler alındı, Adım 1 (utils) tamamlandı.
- **30/04/2026 (2)** — Yönetim dosyaları (RULES.md, .aiignore, progress.md) oluşturuldu.
- **30/04/2026 (3)** — Adım 2 (gui) tamamlandı.
- **30/04/2026 (4)** — Adım 3 (services 1. parti) tamamlandı; views.py 5515 satıra indi.
- **30/04/2026 (5)** — Adım 4 (services 2. parti, SAP runtime) tamamlandı; views.py 4693 satıra indi (toplam %36 azalma).
- **30/04/2026 (6)** — Adım 5 (services 3. parti, telegram + robot_release) tamamlandı; views.py 4527 satıra indi (toplam %38 azalma). Yan etki: dekoratör kayşı yaşandı, fix ile geri alındı.
- **30/04/2026 (7)** — Adım 6 (api/ paketi, 7 modül) tamamlandı; views.py **529 satıra** indi (toplam **%93 azalma**). Sub-step (6a→6g) yaklaşımı ile en küçükten en büyüğe (telegram_webhook → sap_runtime_api 2095 satır) sırayla extract edildi. Tüm 69 view sembolü erişilebilir, `core/urls.py` değişmedi.
- **30/04/2026 (8)** — **Adım 7 + 8 tamamlandı, refactor bitti.** `core/views.py` (529 satır) silindi, yerine `core/views/` paketi geldi: `pages.py` (163 satır, 9 fn), `contacts.py` (163 satır, 5 fn), `__init__.py` (117 satır, sadece re-export). Toplam orijinal 7302 → 326 satır iş kodu (geri kalanı re-export). Final smoke: `manage.py check` no issues, `runserver` start temiz, `GET /` dashboard → 200/36 KB. `core/urls.py` ve diğer çağıran kodda hiçbir değişiklik gerekmedi (geri uyum tam).
- views.py orijinal: 7302 satır, 159+ fonksiyon, 1 sınıf (`_GhostOverlayWindow`).
- Hedef: Tüm refactor sonrası `core/views.py` ya silinecek ya da sadece geri-uyumluluk re-export'u içeren ince bir `__init__.py` olacak.
