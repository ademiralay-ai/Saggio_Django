# Saggio RPA — Proje Kuralları (AI Asistan Rehberi)

> Bu dosya, AI kodlama asistanının (GitHub Copilot / Claude / Cursor) projede dikkat etmesi gereken **mimari, standart ve kuralları** tanımlar. Her görevde önce bu dosyayı baz al, sonra koda dokun.

---

## 1. Proje Kimliği

- **Ad:** Saggio RPA — SAP süreç otomasyonu + Robot Ajan + Telegram bot platformu
- **Backend:** Django 5.x (Python 3.13), SQLite (geliştirme), Firebase Realtime DB (eu-west-1) eşleme
- **Frontend:** React (CRA) — `frontend/` altında, build edilip Django `static/`'e deploy edilir (`build_and_deploy.ps1`)
- **Robot Ajan:** Bağımsız Python servisi (`robot_agent/`), Django HTTP API üzerinden iş çeker
- **OS:** Geliştirme Windows, üretim Plesk + Passenger (Linux)

---

## 2. Dizin / Modül Mimarisi (Refactor Sonrası)

```
core/
├── views/        # HTML render eden Django view'lar
├── api/          # JSON / webhook / agent endpoint'leri
├── services/     # İş mantığı (request bağımsız, test edilebilir)
├── utils/        # Saf yardımcılar (state'siz; runtime_state, parsing, date_utils, http_utils, placeholders)
├── gui/          # Tkinter overlay/dialog bileşenleri
├── models.py, admin.py, forms.py, urls.py
├── sap_service.py, sap_keyboard_utils.py, sap_popup_utils.py
├── windows_dialog_utils.py, security_utils.py
├── firebase_service.py
├── migrations/
├── management/commands/
└── templates/, static/
```

**Yön:** Yeni iş mantığı önce `services/`'e yazılır, view ince controller olur. Hiçbir view 200 satırı geçmemeli.

---

## 3. Kodlama Standartları

### Genel
- Bu dosya kuralı dışında **sadece istenen değişikliği** yap. Bonus refactor, "iyileştirme" veya bağımsız docstring ekleme **yapma**.
- Her dosya **tek sorumluluk** taşımalı (Single Responsibility).
- Public sembollerin geriye dönük uyumu kırma — eski import yolları çalışmaya devam etmeli (re-export ile).
- `views.py` veya benzer monolit dosyaları **büyütme**; yeni kodu uygun `services/` veya `api/` modülüne yaz.

### Python
- **Indent:** Tab (mevcut kod tab kullanıyor — uyumlu kal).
- **Imports:** stdlib → 3rd party → Django → local (`.utils`, `.services`, ...).
- **Naming:** `snake_case` fonksiyon/değişken, `PascalCase` sınıf, `_leading_underscore` modül-içi private.
- **Type hints:** Yeni public fonksiyonlarda zorunlu, mevcut koda eklemek için izin iste.
- **Hata yönetimi:** Sistem sınırlarında (HTTP, DB, dış servis) yakala. İç fonksiyonlarda `try/except: pass` yazma.
- **f-string** kullan; `%` ve `.format()` yeni kodda yok.

### Django
- View'lar: `@require_POST`, `@csrf_exempt` gibi dekoratörler bilinçli. CSRF gevşetme ancak agent/webhook için.
- ORM sorguları: `select_related` / `prefetch_related` ile N+1'i engelle.
- Migration: Her model değişikliği için `makemigrations` çalıştır, **boş migration commit etme**.
- Settings: Sırlar (Firebase key, SMTP şifre) `firebase_service`/`security_utils` üzerinden. **Kodda hardcoded sır olmaz.**

### Frontend (React)
- Yeni component fonksiyonel + hooks. Class component **eklenmez**.
- API çağrıları `fetch` veya tek bir `apiClient` modülü; component içinde URL hardcode etme.
- `App.js` 1000 satırı geçmemeli; yeni view'lar `components/`'e.

---

## 4. Güvenlik (Zorunlu)

- **OWASP Top 10** ihlali olabilecek pattern'leri (SQL injection, XSS, path traversal, SSRF) yazma.
- Agent endpoint'leri **mutlaka** `_authenticate_agent()` ile token doğrulasın.
- `firebase-key.json`, `.env`, gerçek secret'lar **GitHub'a gitmez** (Push Protection açık).
- Yeni dış HTTP isteğinde timeout zorunlu (`timeout=15` minimum).
- File upload/path birleştirmede `os.path.normpath` + tabanın altında olduğunu doğrula.

---

## 5. Çalışma Akışı (AI ile)

### Yedekleme
- Büyük refactor öncesi:
  1. Lokal zip yedek: `C:\Util\SaggioDjango_Backups\`
  2. GitHub backup branch: `backup/<açıklama>-<YYYYMMDD_HHMMSS>`
- DB dosyalarını branch'e zorla ekle (`git add -f`), `firebase-key.json` **push etme**.

### Refactor / Büyük Değişiklik
1. Önce **plan sun**, kod yazma.
2. Plan onaylanınca **küçük adımlar** halinde ilerle.
3. Her adım sonunda `manage.py check` çalıştır.
4. `progress.md`'yi güncelle.

### Sohbet Reset Protokolü
- Kullanıcı **"Sohbeti sıfırlayacağım, progress.md'yi güncelle"** derse:
  1. Tamamlanan, devam eden ve TODO'ları `progress.md`'ye yaz.
  2. Devam eden işin **bir sonraki ilk adımını** çok net yaz.
  3. Yeni sohbet **"progress.md'den devam et"** komutuyla başlar.

### İletişim
- **Kısa ve öz** yanıt ver. 1-3 cümle hedef.
- Tool çağrısı yaparken kullanıcıya tool ismini söyleme.
- Türkçe yanıt ver (varsayılan locale: tr).
- Emoji kullanma (kullanıcı istemedikçe).

---

## 6. Test ve Doğrulama

- Tüm kod değişiklikleri sonrası: `python manage.py check`
- Migration: `python manage.py migrate --plan` ile ön kontrol
- Runserver smoke test: `python manage.py runserver` + dashboard yüklenmeli
- Production deploy öncesi: `python manage.py collectstatic --noinput`

---

## 7. Asla Yapma Listesi

- `git push --force` (kullanıcı izni olmadan)
- `git reset --hard HEAD` (commit'leri uçurabilir)
- DB drop / migration rollback (uyarı + onay olmadan)
- `*.bak` dosyalarını silme (kullanıcı yedeği olabilir)
- `.venv`, `node_modules`, `media/`, `db.sqlite3` git'e ekleme
- Bilinmeyen URL'lere `requests.get()` (SSRF)
- Senin için "daha güzel" olduğu için spontane refactor

---

## 8. Bilinen Sorunlar / Notlar

- Robot ajan `localhost:8000`'e bağlanamıyor → ajan farklı makinede ise sunucu IP'si gerekir; `agent_runtime.py` config'inde `server_url` doğru ayarlanmalı.
- Python 3.13/3.14'te subprocess `cp1254` decode hatası → `subprocess.Popen(..., encoding='utf-8', errors='replace')` kullan.
- SAP keyboard send'lerde Türkçe karakter için `sap_keyboard_utils.build_sendkeys_from_config()` kullan.
- Firebase `databaseURL` formatı: `https://<project>-default-rtdb.europe-west1.firebasedatabase.app`
- `{% extends %}` template'in **ilk** tag'i olmalı, `{% load %}` öncesi.

---

> Güncellemek için: yeni bir kural eklerken numaralı bölümün altına yaz, ezme. Ana mimariyi değiştirirsen `progress.md` ile senkronize et.
