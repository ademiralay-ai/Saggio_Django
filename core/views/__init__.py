"""Backwards-compatibility re-export package for ``core.views``.

The original ``core/views.py`` was split into:
  - ``core.views.pages``    : HTML page renderers (dashboard, sections, robot control center)
  - ``core.views.contacts`` : Telegram/Mail/FTP contact CRUD views

All JSON / scan / runtime endpoints live in ``core.api`` packages.
This ``__init__`` re-exports every public name so existing imports such as
``from core.views import dashboard`` continue to work.
"""
from __future__ import annotations

# --- HTML page views ---------------------------------------------------------
from .pages import (
	get_dashboard_stats,
	dashboard,
	help_center,
	help_media_upload,
	robots,
	processes,
	queues,
	scheduler,
	reports,
	settings_page,
	robot_control_center,
)

# --- Contact CRUD views ------------------------------------------------------
from .contacts import (
	_manage_contact_entity,
	telegram_bots_manage,
	telegram_groups_manage,
	mail_accounts_manage,
	ftp_accounts_manage,
)

# --- Telegram bot studio + webhook ------------------------------------------
from ..api.telegram_webhook_api import (
	telegram_bot_studio,
	telegram_bot_studio_menu_save,
	telegram_bot_studio_menus,
	telegram_bot_studio_menu_delete,
	telegram_bot_studio_simulate,
	telegram_bot_webhook,
	telegram_bot_studio_bot_save,
	telegram_bot_studio_set_webhook,
	telegram_bot_studio_webhook_info,
	telegram_bot_studio_delete_webhook,
)

# --- Robot agent runtime endpoints ------------------------------------------
from ..api.robot_agent_api import (
	agent_register,
	agent_heartbeat,
	agent_check_update,
	agent_log_event,
	agent_pull_job,
	agent_job_update,
	agent_process_definition,
	agent_run_process,
	agent_run_process_status,
)

# --- Robot admin / release / dispatch endpoints -----------------------------
from ..api.robot_admin_api import (
	robot_agent_status,
	robot_job_list,
	robot_agent_event_list,
	robot_release_list,
	robot_release_save,
	robot_release_download,
	robot_release_download_package,
	robot_release_deploy,
	robot_build_setup_exe,
	robot_build_install_package,
	robot_set_desired_version,
	robot_agent_upsert,
	robot_agent_delete,
	robot_cancel_job,
	robot_dispatch_job,
)

# --- SAP scan/apply/run + template endpoints --------------------------------
from ..api.sap_template_api import (
	sap_scan,
	sap_apply,
	sap_run,
	sap_template_list,
	sap_template_get,
	sap_template_save,
	sap_template_delete,
)

# --- SAP process admin + excel endpoints ------------------------------------
from ..api.sap_process_api import (
	sap_process_list,
	sap_process_builder,
	sap_process_backup,
	sap_process_delete,
	sap_process_step_save,
	sap_process_rename,
	sap_process_runtime_settings_save,
	sap_process_runtime_control,
	sap_process_runtime_status,
	sap_process_excel_browse,
	sap_process_excel_sheets,
	sap_process_excel_columns,
)

# --- SAP scan endpoints ------------------------------------------------------
from ..api.sap_scan_api import (
	_sap_process_scan_popups_impl,
	sap_process_scan_popups,
	sap_process_scan_buttons,
	sap_process_scan_selectables,
	sap_process_scan_inputs,
	sap_process_scan_windows_dialogs,
	sap_process_scan_screens,
	sap_process_scan_grids,
)

# --- SAP runtime preview (huge endpoint) ------------------------------------
from ..api.sap_runtime_api import sap_process_run_preview

# --- Scheduler endpoints -----------------------------------------------------
from ..api.scheduler_api import (
	scheduler_list,
	scheduler_save,
	scheduler_toggle,
	scheduler_delete,
	scheduler_run_now,
	scheduler_dispatch_due,
)
