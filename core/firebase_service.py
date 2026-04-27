"""
Firebase Realtime Database Service for RPA Dashboard
Provides methods to interact with Firebase collections
"""
import base64
from pathlib import Path
from firebase_admin import db
from datetime import datetime
import json
import time
from django.conf import settings


class RobotService:
    """Manage robot data in Firebase"""
    
    @staticmethod
    def get_all_robots():
        """Fetch all robots from Firebase"""
        try:
            ref = db.reference('robots')
            robots = ref.get()
            return robots.val() if robots else {}
        except Exception as e:
            print(f"Error fetching robots: {e}")
            return {}
    
    @staticmethod
    def get_robot(robot_id):
        """Fetch specific robot by ID"""
        try:
            ref = db.reference(f'robots/{robot_id}')
            robot = ref.get()
            return robot.val() if robot else None
        except Exception as e:
            print(f"Error fetching robot {robot_id}: {e}")
            return None
    
    @staticmethod
    def create_robot(robot_id, data):
        """Create new robot"""
        try:
            ref = db.reference(f'robots/{robot_id}')
            data['created_at'] = datetime.now().isoformat()
            data['updated_at'] = datetime.now().isoformat()
            ref.set(data)
            return True
        except Exception as e:
            print(f"Error creating robot: {e}")
            return False
    
    @staticmethod
    def update_robot(robot_id, data):
        """Update robot data"""
        try:
            ref = db.reference(f'robots/{robot_id}')
            data['updated_at'] = datetime.now().isoformat()
            ref.update(data)
            return True
        except Exception as e:
            print(f"Error updating robot: {e}")
            return False


class ProcessService:
    """Manage process data in Firebase"""
    
    @staticmethod
    def get_all_processes():
        """Fetch all processes"""
        try:
            ref = db.reference('processes')
            processes = ref.get()
            return processes.val() if processes else {}
        except Exception as e:
            print(f"Error fetching processes: {e}")
            return {}
    
    @staticmethod
    def get_process(process_id):
        """Fetch specific process"""
        try:
            ref = db.reference(f'processes/{process_id}')
            process = ref.get()
            return process.val() if process else None
        except Exception as e:
            print(f"Error fetching process {process_id}: {e}")
            return None
    
    @staticmethod
    def create_process(process_id, data):
        """Create new process"""
        try:
            ref = db.reference(f'processes/{process_id}')
            data['created_at'] = datetime.now().isoformat()
            data['updated_at'] = datetime.now().isoformat()
            data['status'] = 'pending'
            ref.set(data)
            return True
        except Exception as e:
            print(f"Error creating process: {e}")
            return False


class QueueService:
    """Manage queue data in Firebase"""
    
    @staticmethod
    def get_all_queues():
        """Fetch all queues"""
        try:
            ref = db.reference('queues')
            queues = ref.get()
            return queues.val() if queues else {}
        except Exception as e:
            print(f"Error fetching queues: {e}")
            return {}
    
    @staticmethod
    def add_to_queue(queue_name, item):
        """Add item to queue"""
        try:
            ref = db.reference(f'queues/{queue_name}')
            new_item = {
                'id': datetime.now().timestamp(),
                'data': item,
                'created_at': datetime.now().isoformat()
            }
            ref.push(new_item)
            return True
        except Exception as e:
            print(f"Error adding to queue: {e}")
            return False


class ReportService:
    """Manage report data in Firebase"""
    
    @staticmethod
    def get_all_reports():
        """Fetch all reports"""
        try:
            ref = db.reference('reports')
            reports = ref.get()
            return reports.val() if reports else {}
        except Exception as e:
            print(f"Error fetching reports: {e}")
            return {}
    
    @staticmethod
    def create_report(report_id, data):
        """Create new report"""
        try:
            ref = db.reference(f'reports/{report_id}')
            data['created_at'] = datetime.now().isoformat()
            ref.set(data)
            return True
        except Exception as e:
            print(f"Error creating report: {e}")
            return False


class ScheduleService:
    """Manage scheduled tasks in Firebase"""
    
    @staticmethod
    def get_all_schedules():
        """Fetch all schedules"""
        try:
            ref = db.reference('schedules')
            schedules = ref.get()
            return schedules.val() if schedules else {}
        except Exception as e:
            print(f"Error fetching schedules: {e}")
            return {}
    
    @staticmethod
    def create_schedule(schedule_id, data):
        """Create new schedule"""
        try:
            ref = db.reference(f'schedules/{schedule_id}')
            data['created_at'] = datetime.now().isoformat()
            data['enabled'] = True
            ref.set(data)
            return True
        except Exception as e:
            print(f"Error creating schedule: {e}")
            return False


class SAPTemplateService:
    """Manage SAP screen templates in Firebase"""

    BASE_PATH = 'sap_templates'
    LOCAL_FILE = Path(settings.BASE_DIR) / 'data' / 'sap_templates_local.json'

    @staticmethod
    def _key_from_name(name):
        raw = str(name or '').strip()
        if not raw:
            return ''
        token = base64.urlsafe_b64encode(raw.encode('utf-8')).decode('ascii').rstrip('=')
        return f"n_{token}"

    # Firebase key'lerde . / # [ ] $ karakterleri yasak; satır ID'lerini encode et.
    _KEY_ENCODE = [
        ('__', '__esc__'),   # escape token'ı önce encode et
        ('.', '__D__'),
        ('/', '__S__'),
        ('#', '__H__'),
        ('[', '__L__'),
        (']', '__R__'),
        ('$', '__Q__'),
    ]
    _KEY_DECODE = [(v, k) for k, v in reversed(_KEY_ENCODE)]

    @staticmethod
    def _sanitize_key(key: str) -> str:
        for src, dst in SAPTemplateService._KEY_ENCODE:
            key = key.replace(src, dst)
        return key or '__empty__'

    @staticmethod
    def _desanitize_key(key: str) -> str:
        if key == '__empty__':
            return ''
        for src, dst in SAPTemplateService._KEY_DECODE:
            key = key.replace(src, dst)
        return key

    @staticmethod
    def _encode_rows(rows: dict) -> dict:
        if not isinstance(rows, dict):
            return rows
        return {SAPTemplateService._sanitize_key(k): v for k, v in rows.items()}

    @staticmethod
    def _decode_rows(rows: dict) -> dict:
        if not isinstance(rows, dict):
            return rows
        return {SAPTemplateService._desanitize_key(k): v for k, v in rows.items()}

    @staticmethod
    def _normalize_payload(payload):
        if payload is None:
            return {}
        if hasattr(payload, 'val'):
            try:
                payload = payload.val()
            except Exception:
                return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_local():
        try:
            path = SAPTemplateService.LOCAL_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                return {}
            with open(path, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _save_local(data):
        try:
            path = SAPTemplateService.LOCAL_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    @staticmethod
    def list_template_names():
        names = []
        try:
            ref = db.reference(SAPTemplateService.BASE_PATH)
            data = SAPTemplateService._normalize_payload(ref.get())
            for key, value in data.items():
                if isinstance(value, dict):
                    nm = str(value.get('name', '') or '').strip()
                    if nm:
                        names.append(nm)
                        continue
                # Legacy fallback: old records stored directly under plain name
                names.append(str(key))
        except Exception as e:
            print(f"Error listing SAP templates: {e}")

        # Firebase ok olsa da yerel fallback kayıtlarını da görünür tut.
        local_data = SAPTemplateService._load_local()
        names.extend(local_data.keys())
        return sorted(set(names), key=lambda x: str(x).casefold())

    @staticmethod
    def get_template(name):
        try:
            if not name:
                return None
            key = SAPTemplateService._key_from_name(name)
            data = None

            if key:
                ref = db.reference(f'{SAPTemplateService.BASE_PATH}/{key}')
                data = ref.get()
                if hasattr(data, 'val'):
                    data = data.val()

            # Legacy fallback
            if not isinstance(data, dict):
                ref_legacy = db.reference(f'{SAPTemplateService.BASE_PATH}/{name}')
                data = ref_legacy.get()
                if hasattr(data, 'val'):
                    data = data.val()

            if isinstance(data, dict):
                # rows key'leri decode et (Firebase'de encode edilmiş olabilir).
                stored_state = data.get('state')
                if isinstance(stored_state, dict) and 'rows' in stored_state:
                    stored_state = {
                        **stored_state,
                        'rows': SAPTemplateService._decode_rows(stored_state['rows']),
                    }
                    data = {**data, 'state': stored_state}
                return data

            # Firebase tarafında bulunamazsa yerelde tutulan fallback'e bak.
            local = SAPTemplateService._load_local().get(str(name), None)
            return local if isinstance(local, dict) else None
        except Exception as e:
            print(f"Error reading SAP template {name}: {e}")
            local = SAPTemplateService._load_local().get(str(name), None)
            return local if isinstance(local, dict) else None

    @staticmethod
    def save_template(name, state):
        name = str(name or '').strip()
        if not name:
            return {'ok': False, 'storage': 'none', 'error': 'Şablon adı boş.'}
        key = SAPTemplateService._key_from_name(name)
        if not key:
            return {'ok': False, 'storage': 'none', 'error': 'Şablon anahtarı oluşturulamadı.'}

        payload = {
            'name': name,
            'state': {
                **{k: v for k, v in (state or {}).items() if k != 'rows'},
                'rows': SAPTemplateService._encode_rows((state or {}).get('rows', {})),
            },
            'updated_at': datetime.now().isoformat(),
        }

        last_error = None
        for attempt in range(2):
            try:
                ref = db.reference(f'{SAPTemplateService.BASE_PATH}/{key}')
                # set() with overwrite keeps latest snapshot of template
                ref.set(payload)
                return {'ok': True, 'storage': 'firebase'}
            except Exception as e:
                last_error = e
                print(f"Error saving SAP template {name} (attempt {attempt + 1}/2): {e}")
                if attempt == 0:
                    time.sleep(0.2)

        local = SAPTemplateService._load_local()
        local[name] = {
            'name': name,
            'state': state or {},
            'updated_at': datetime.now().isoformat(),
            'storage': 'local_fallback',
        }
        local_ok = SAPTemplateService._save_local(local)
        if local_ok:
            return {'ok': True, 'storage': 'local_fallback', 'reason': str(last_error or '')}
        return {'ok': False, 'storage': 'none', 'error': 'Firebase ve yerel kaydetme başarısız.'}

    @staticmethod
    def delete_template(name):
        name = str(name or '').strip()
        if not name:
            return {'ok': False, 'storage': 'none', 'error': 'Şablon adı boş.'}

        key = SAPTemplateService._key_from_name(name)
        firebase_ok = False
        firebase_err = None

        # Firebase'den yeni format anahtarıyla silmeyi dene.
        try:
            if key:
                db.reference(f'{SAPTemplateService.BASE_PATH}/{key}').delete()
            # Legacy isim tabanlı kayıt ihtimaline karşı ikinci silme.
            db.reference(f'{SAPTemplateService.BASE_PATH}/{name}').delete()
            firebase_ok = True
        except Exception as e:
            firebase_err = str(e)

        # Yereldeki fallback kaydını da sil.
        local = SAPTemplateService._load_local()
        local_deleted = False
        if name in local:
            del local[name]
            local_deleted = SAPTemplateService._save_local(local)

        if firebase_ok:
            return {'ok': True, 'storage': 'firebase'}
        if local_deleted:
            return {'ok': True, 'storage': 'local_fallback', 'reason': firebase_err}
        return {'ok': False, 'storage': 'none', 'error': firebase_err or 'Şablon silinemedi.'}


class ContactConfigService:
    """Sync telegram/mail config models to Firebase RTDB"""

    @staticmethod
    def _key(prefix, entity_id):
        return f'{prefix}_{entity_id}'

    @staticmethod
    def sync_telegram_bot(bot):
        try:
            key = ContactConfigService._key('bot', bot.id)
            ref = db.reference(f'contact_configs/telegram_bots/{key}')
            ref.set(
                {
                    'id': bot.id,
                    'name': bot.name,
                    'bot_username': bot.bot_username,
                    'bot_token_enc': bot.bot_token,
                    'default_parse_mode': bot.default_parse_mode,
                    'description': bot.description,
                    'is_active': bool(bot.is_active),
                    'updated_at': datetime.now().isoformat(),
                }
            )
            return True, 'firebase_ok'
        except Exception as e:
            return False, f'firebase_sync_error: {e}'

    @staticmethod
    def sync_telegram_group(group):
        try:
            key = ContactConfigService._key('grp', group.id)
            ref = db.reference(f'contact_configs/telegram_groups/{key}')
            ref.set(
                {
                    'id': group.id,
                    'name': group.name,
                    'chat_id': group.chat_id,
                    'owners': group.owners,
                    'description': group.description,
                    'default_bot_id': group.default_bot_id,
                    'default_bot_name': group.default_bot.name if group.default_bot else '',
                    'is_active': bool(group.is_active),
                    'updated_at': datetime.now().isoformat(),
                }
            )
            return True, 'firebase_ok'
        except Exception as e:
            return False, f'firebase_sync_error: {e}'

    @staticmethod
    def sync_mail_account(account):
        try:
            key = ContactConfigService._key('mail', account.id)
            ref = db.reference(f'contact_configs/mail_accounts/{key}')
            ref.set(
                {
                    'id': account.id,
                    'name': account.name,
                    'email': account.email,
                    'from_name': account.from_name,
                    'smtp_host': account.smtp_host,
                    'smtp_port': account.smtp_port,
                    'smtp_username': account.smtp_username,
                    'smtp_password_enc': account.smtp_password,
                    'use_tls': bool(account.use_tls),
                    'use_ssl': bool(account.use_ssl),
                    'description': account.description,
                    'is_active': bool(account.is_active),
                    'updated_at': datetime.now().isoformat(),
                }
            )
            return True, 'firebase_ok'
        except Exception as e:
            return False, f'firebase_sync_error: {e}'

    @staticmethod
    def sync_ftp_account(account):
        try:
            key = ContactConfigService._key('ftp', account.id)
            ref = db.reference(f'contact_configs/ftp_accounts/{key}')
            ref.set(
                {
                    'id': account.id,
                    'name': account.name,
                    'protocol': account.protocol,
                    'host': account.host,
                    'port': account.port,
                    'username': account.username,
                    'password_enc': account.password,
                    'remote_base_path': account.remote_base_path,
                    'description': account.description,
                    'is_active': bool(account.is_active),
                    'updated_at': datetime.now().isoformat(),
                }
            )
            return True, 'firebase_ok'
        except Exception as e:
            return False, f'firebase_sync_error: {e}'

    @staticmethod
    def delete_entity(entity_type, entity_id):
        try:
            prefix_map = {
                'telegram_bots': 'bot',
                'telegram_groups': 'grp',
                'mail_accounts': 'mail',
                'ftp_accounts': 'ftp',
            }
            key = ContactConfigService._key(prefix_map.get(entity_type, 'obj'), entity_id)
            ref = db.reference(f'contact_configs/{entity_type}/{key}')
            ref.delete()
            return True, 'firebase_delete_ok'
        except Exception as e:
            return False, f'firebase_delete_error: {e}'
