import json
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

import requests


def _default_config_path() -> str:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, "config.json")


DEFAULT_CONFIG_PATH = _default_config_path()


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    required = ["server_base_url", "agent_code", "token"]
    missing = [key for key in required if not str(data.get(key, "")).strip()]
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(missing)}")
    return data


def setup_logging(config: Dict[str, Any]) -> None:
    level_name = str(config.get("log_level", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)
    log_file = str(config.get("log_file", "C:/SaggioRobotAgent/agent.log"))
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


class AgentClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.base_url = str(config["server_base_url"]).rstrip("/")
        self.agent_code = str(config["agent_code"])
        self.token = str(config["token"])
        self.timeout = int(config.get("http_timeout_seconds", 20))

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "X-Agent-Code": self.agent_code,
            "X-Agent-Token": self.token,
        }

        urls = [f"{self.base_url}{path}"]
        if "localhost" in self.base_url.lower():
            urls.append(f"{self.base_url.replace('localhost', '127.0.0.1')}{path}")

        last_err: Optional[Exception] = None
        for url in urls:
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as ex:
                last_err = ex

        if last_err:
            raise last_err
        raise RuntimeError("HTTP request failed")

    def register(self) -> Dict[str, Any]:
        payload = {
            "agent_code": self.agent_code,
            "token": self.token,
            "name": self.config.get("name", self.agent_code),
            "machine_name": platform.node(),
            "host_name": socket.gethostname(),
            "os_user": os.environ.get("USERNAME", ""),
            "agent_version": self.config.get("agent_version", "1.0.0"),
            "capabilities": self.config.get("capabilities", {}),
        }
        return self._post("/api/robot-agent/register/", payload)

    def heartbeat(self) -> Dict[str, Any]:
        return self._post(
            "/api/robot-agent/heartbeat/",
            {
                "agent_code": self.agent_code,
                "token": self.token,
                "agent_version": self.config.get("agent_version", ""),
            },
        )

    def check_update(self) -> Dict[str, Any]:
        return self._post(
            "/api/robot-agent/check-update/",
            {
                "agent_code": self.agent_code,
                "token": self.token,
                "current_version": self.config.get("agent_version", ""),
            },
        )

    def log_event(self, level: str, message: str, *, job_id: Optional[int] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "agent_code": self.agent_code,
            "token": self.token,
            "level": level,
            "message": message,
            "extra": extra or {},
        }
        if job_id is not None:
            payload["job_id"] = int(job_id)
        return self._post("/api/robot-agent/log-event/", payload)

    def pull_job(self) -> Dict[str, Any]:
        return self._post("/api/robot-agent/pull-job/", {"agent_code": self.agent_code, "token": self.token})

    def update_job(self, job_id: int, status: str, message: str = "", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._post(
            "/api/robot-agent/job-update/",
            {
                "agent_code": self.agent_code,
                "token": self.token,
                "job_id": job_id,
                "status": status,
                "result_message": message,
                "result_payload": payload or {},
            },
        )


def execute_command(command: str, timeout_seconds: int) -> Dict[str, Any]:
    def _decode_output(raw: bytes) -> str:
        for enc in ("utf-8", "cp1254", "cp1252"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="replace")

    started = time.time()
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=False,
        timeout=timeout_seconds,
    )
    elapsed = round(time.time() - started, 2)
    stdout_text = _decode_output(result.stdout or b"")
    stderr_text = _decode_output(result.stderr or b"")
    return {
        "command": command,
        "return_code": result.returncode,
        "stdout": stdout_text[-8000:],
        "stderr": stderr_text[-8000:],
        "elapsed_seconds": elapsed,
    }


def _extract_command_path(command: str) -> str:
    cmd = str(command or "").strip()
    if not cmd:
        return ""
    if cmd[0] in ('"', "'"):
        q = cmd[0]
        end = cmd.find(q, 1)
        if end > 1:
            return cmd[1:end]
    return cmd.split()[0]


def resolve_job_command(config: Dict[str, Any], job: Dict[str, Any]) -> str:
    command_type = str(job.get("command_type", ""))
    payload = job.get("payload") or {}

    if command_type == "run_command":
        cmd = str(payload.get("command") or "").strip()
        if not cmd:
            raise ValueError("run_command job payload must include 'command'.")
        return cmd

    if command_type == "run_sap_process":
        explicit_cmd = str(payload.get("command") or "").strip()
        if explicit_cmd:
            return explicit_cmd

        sap_process_id = job.get("sap_process_id")
        template = str(config.get("process_command_template", "")).strip()
        if not template:
            raise ValueError("process_command_template is required for run_sap_process jobs.")
        return template.format(sap_process_id=sap_process_id)

    raise ValueError(f"Unsupported command_type: {command_type}")


def run_loop(stop_event: threading.Event, config_path: str = DEFAULT_CONFIG_PATH) -> None:
    config = load_config(config_path)
    setup_logging(config)

    client = AgentClient(config)
    poll_sleep = int(config.get("poll_interval_seconds", 5))
    idle_sleep = int(config.get("idle_interval_seconds", 3))
    command_timeout = int(config.get("command_timeout_seconds", 7200))
    update_check_interval = int(config.get("update_check_interval_seconds", 300))
    last_update_check = 0.0

    logging.info("Agent starting, registering to server.")
    while not stop_event.is_set():
        try:
            reg = client.register()
            if not reg.get("ok"):
                raise RuntimeError(f"register failed: {reg}")
            try:
                client.log_event("info", "Agent startup completed")
            except Exception:
                pass
            break
        except Exception as ex:
            logging.exception("Register failed, retrying: %s", ex)
            stop_event.wait(10)

    while not stop_event.is_set():
        try:
            client.heartbeat()

            now_ts = time.time()
            if now_ts - last_update_check >= update_check_interval:
                last_update_check = now_ts
                try:
                    upd = client.check_update()
                    if upd.get("update_available"):
                        desired = str(upd.get("desired_version") or "")
                        current = str(upd.get("current_version") or "")
                        msg = f"Update available: current={current} desired={desired}"
                        logging.warning(msg)
                        client.log_event("warning", msg, extra={"update": upd})
                except Exception as update_ex:
                    logging.warning("Update check failed: %s", update_ex)

            pull = client.pull_job()
            job = pull.get("job") if isinstance(pull, dict) else None
            if not job:
                stop_event.wait(idle_sleep)
                continue

            job_id = int(job["job_id"])
            client.update_job(job_id, "running", "Job started")
            try:
                client.log_event("info", f"Job {job_id} started", job_id=job_id)
            except Exception:
                pass

            command = resolve_job_command(config, job)
            logging.info("Running job %s | %s", job_id, command)

            # For process jobs, fail fast with a clear message when the batch/exe path is missing.
            cmd_path = _extract_command_path(command)
            is_abs = bool(re.match(r"^[A-Za-z]:[\\/]", cmd_path))
            if cmd_path and is_abs and not os.path.exists(cmd_path.replace('/', os.sep)):
                run_data = {
                    "command": command,
                    "return_code": 127,
                    "stdout": "",
                    "stderr": f"Command file not found: {cmd_path}",
                    "elapsed_seconds": 0.0,
                }
                client.update_job(job_id, "failed", "Command file not found", run_data)
                try:
                    client.log_event("error", f"Job {job_id} failed: command file missing", job_id=job_id, extra=run_data)
                except Exception:
                    pass
                stop_event.wait(poll_sleep)
                continue

            run_data = execute_command(command, command_timeout)

            if int(run_data.get("return_code", 1)) == 0:
                client.update_job(job_id, "succeeded", "Command completed", run_data)
                logging.info("Job %s succeeded", job_id)
                try:
                    client.log_event("info", f"Job {job_id} succeeded", job_id=job_id, extra=run_data)
                except Exception:
                    pass
            else:
                client.update_job(job_id, "failed", "Command failed", run_data)
                logging.warning("Job %s failed rc=%s", job_id, run_data.get("return_code"))
                try:
                    client.log_event("error", f"Job {job_id} failed", job_id=job_id, extra=run_data)
                except Exception:
                    pass

            stop_event.wait(poll_sleep)
        except Exception as ex:
            logging.exception("Loop error: %s", ex)
            try:
                client.log_event("error", f"Loop error: {ex}")
            except Exception:
                pass
            stop_event.wait(10)


def main() -> None:
    event = threading.Event()
    run_loop(event)


if __name__ == "__main__":
    main()
