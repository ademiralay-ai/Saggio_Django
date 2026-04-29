import json
import sys

from windows_dialog_utils import perform_dialog_action


def main():
    try:
        raw = sys.argv[1] if len(sys.argv) > 1 else '{}'
        payload = json.loads(raw)
        payload.pop('on_progress', None)
        payload.pop('progress_interval_ms', None)
        ok, msg = perform_dialog_action(**payload)
        print(json.dumps({'ok': bool(ok), 'msg': str(msg or '')}, ensure_ascii=False))
        return 0
    except Exception as ex:
        print(json.dumps({'ok': False, 'msg': f'worker_exception: {ex}'}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
