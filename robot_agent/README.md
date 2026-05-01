# Saggio Robot Agent — Kurulum Paketi

Bu paket bir Windows robot makinesinde **Saggio Robot Agent**'ı tek komutla
çalışan Windows servisi olarak kurar.

## Önkoşullar

- Windows 10 / 11 veya Windows Server 2019+
- Python 3.11+ (`py -3.11` ile çağrılabilmeli)
- Yönetici yetkili (Administrator) PowerShell oturumu
- Merkez sunucuya HTTP erişimi (örn: `http://10.16.88.18:8000`)

## Hızlı Kurulum

1. Bu klasörü robot makinesinde herhangi bir yere açın (örn. `C:\Users\admin\Desktop\`).
2. Klasörde **PowerShell'i Administrator olarak** açın.
3. Aşağıdaki komutu kendi token + ajan koduyla çalıştırın:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\install.ps1 -ServerUrl "http://10.16.88.18:8000" `
              -AgentCode "robot-06" `
              -Token     "SUNUCUDA_OLUSAN_TOKEN" `
              -Name      "Robot 06"
```

Script otomatik olarak:

- `C:\SaggioRobotAgent\` klasörünü ve `logs\` alt klasörünü oluşturur
- `.venv` Python sanal ortamı kurar, `requests` paketini yükler
- `agent_runtime.py` ve `agent_launcher.py`'ı kopyalar
- `config.json`'u parametrelere göre yazar
- `nssm.exe` yoksa `https://nssm.cc` üzerinden indirir
- **NSSM** ile `SaggioRobotAgent` adlı Windows servisini kaydeder ve başlatır

> **Not:** Eski pywin32 tabanlı `robot_agent_service.py` artık kullanılmıyor.
> NSSM ortamdan bağımsız ve çok daha kararlıdır.

## Doğrulama

```powershell
Get-Service SaggioRobotAgent
Get-Content C:\SaggioRobotAgent\logs\launcher.log -Tail 30
Get-Content C:\SaggioRobotAgent\logs\stdout.log   -Tail 30
```

Sunucu tarafındaki **Robot Operasyon** ekranında ajanın `Online` olduğunu görmelisiniz.

## Güncelleme

Yeni paketi açtıktan sonra aynı `install.ps1` komutunu tekrar çalıştırmanız yeterlidir;
script eski servisi temizleyip yenisini kurar. `config.json` mevcutsa `config.json.bak`
olarak yedeklenir, parametrelerle yeni hâli yazılır.

## Kaldırma

```powershell
.\uninstall.ps1                    # sadece servisi kaldirir, veri kalir
.\uninstall.ps1 -PurgeData         # her seyi siler
```

## Sorun Giderme

| Belirti | Çözüm |
|--------|-------|
| `install.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force` çalıştırın. |
| `python bulunamadi` | Python 3.11'i kurun: <https://www.python.org/downloads/> |
| Servis Online olmuyor | `logs\launcher.log`, `logs\stdout.log`, `logs\stderr.log` dosyalarına bakın. |
| `Failed to establish a new connection` | Sunucu URL'si yanlış / firewall engelli. `Test-NetConnection 10.16.88.18 -Port 8000`. |
| `register failed: 401` | Token yanlış. Sunucuda yeni token oluşturup `config.json`'da güncelleyin. |
