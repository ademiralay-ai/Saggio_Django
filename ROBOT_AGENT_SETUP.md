# Robot Agent Kurulum Rehberi

Bu yapı ile merkezi Django sunucusu robot bilgisayarlara iş dağıtır.

## 1) Sunucu tarafı

### Migration

```powershell
c:/Util/SaggioDjango/.venv/Scripts/python.exe manage.py migrate
```

### Robot ajanı oluşturma

Her robot için ayrı ajan oluştur:

```powershell
c:/Util/SaggioDjango/.venv/Scripts/python.exe manage.py create_robot_agent --code robot-01 --name "Robot 01"
c:/Util/SaggioDjango/.venv/Scripts/python.exe manage.py create_robot_agent --code robot-02 --name "Robot 02"
c:/Util/SaggioDjango/.venv/Scripts/python.exe manage.py create_robot_agent --code robot-03 --name "Robot 03"
c:/Util/SaggioDjango/.venv/Scripts/python.exe manage.py create_robot_agent --code robot-04 --name "Robot 04"
c:/Util/SaggioDjango/.venv/Scripts/python.exe manage.py create_robot_agent --code robot-05 --name "Robot 05"
```

Komut çıktısındaki TOKEN değerini ilgili robota koy.

### Uygulamadan robota iş gönderme

SAP süreç işi gönderme:

```powershell
Invoke-RestMethod -Method Post -Uri "https://SUNUCU_ADRESIN/api/robot-agent/dispatch-job/" -ContentType "application/json" -Body (@{
  command_type = "run_sap_process"
  sap_process_id = 12
  target_agent_code = "robot-01"
  priority = 200
  payload = @{
    command = "C:/SaggioRobotRunner/run_process_12.bat"
  }
  requested_by = "admin"
} | ConvertTo-Json -Depth 8)
```

Genel komut işi gönderme:

```powershell
Invoke-RestMethod -Method Post -Uri "https://SUNUCU_ADRESIN/api/robot-agent/dispatch-job/" -ContentType "application/json" -Body (@{
  command_type = "run_command"
  target_agent_code = "robot-02"
  priority = 100
  payload = @{
    command = "C:/Scripts/nightly_job.bat"
  }
  requested_by = "scheduler"
} | ConvertTo-Json -Depth 8)
```

Ajan durumlarını görme:

```powershell
Invoke-RestMethod -Method Get -Uri "https://SUNUCU_ADRESIN/api/robot-agent/status/"
```

## 2) Robot bilgisayar tarafı

Her robotta aşağıdaki klasörü oluştur:

- C:/SaggioRobotAgent

Bu klasöre kopyala:

- robot_agent/agent_runtime.py
- robot_agent/robot_agent_service.py
- robot_agent/config.example.json (adını config.json yap)

`config.json` içini robota göre güncelle:

- server_base_url: sunucu adresi
- agent_code: robot-01 gibi
- token: create_robot_agent çıktısındaki TOKEN
- process_command_template: SAP sürecini lokalde başlatacak komut şablonu

## 3) Robotta Python bağımlılıkları

```powershell
py -3.11 -m venv C:/SaggioRobotAgent/.venv
C:/SaggioRobotAgent/.venv/Scripts/pip.exe install requests pywin32
```

## 4) Windows servis olarak çalıştırma

Servisi kur:

```powershell
$env:SAGGIO_AGENT_CONFIG = "C:/SaggioRobotAgent/config.json"
C:/SaggioRobotAgent/.venv/Scripts/python.exe C:/SaggioRobotAgent/robot_agent_service.py install
C:/SaggioRobotAgent/.venv/Scripts/python.exe C:/SaggioRobotAgent/robot_agent_service.py start
```

Servis durumu:

```powershell
Get-Service SaggioRobotAgent
```

Log:

- C:/SaggioRobotAgent/agent.log

## 5) EXE üretmek istersen (opsiyonel)

```powershell
C:/SaggioRobotAgent/.venv/Scripts/pip.exe install pyinstaller
C:/SaggioRobotAgent/.venv/Scripts/pyinstaller.exe --onefile C:/SaggioRobotAgent/robot_agent_service.py
```

Üretilen exe ile aynı service komutlarını çalıştırabilirsin.

## 6) Önerilen işletim akışı

1. Sunucuda 5 ajanı oluştur, tokenları kaydet.
2. Robotlara config.json ile dağıt.
3. Her robotta servisi kur ve başlat.
4. `/api/robot-agent/status/` ile hepsinin online olduğunu doğrula.
5. Uygulamadan `dispatch-job` ile işi robota gönder.
6. Job sonucu `RobotJob` kaydında succeeded/failed olarak izlenir.

## 7) Yeni panel yetenekleri

Robot Operasyon ekranından şunları yapabilirsin:

- Ajan oluşturma/güncelleme (code/name/token/enabled)
- Job arama ve filtreleme (durum + robot + metin)
- Ajan EXE release kaydı (version, url, sha, not)
- Desired version atama (tek ajana veya tüm ajanlara)
- Ajan event log izleme

Ajan tarafı periyodik olarak `check-update` çağırır; desired sürüm farklıysa panelde `outdated` görünür.
