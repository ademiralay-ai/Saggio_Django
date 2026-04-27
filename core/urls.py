from django.urls import path

from .views import (
    dashboard, ftp_accounts_manage, mail_accounts_manage, processes, queues, reports, robots,
    sap_scan, sap_apply, sap_run,
    sap_template_list, sap_template_get, sap_template_save, sap_template_delete,
    sap_process_list, sap_process_builder, sap_process_delete,
    sap_process_step_save, sap_process_rename, sap_process_runtime_settings_save, sap_process_run_preview,
    scheduler, settings_page, telegram_bots_manage, telegram_groups_manage,
)

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('robots/', robots, name='robots'),
    path('processes/', processes, name='processes'),
    path('queues/', queues, name='queues'),
    path('scheduler/', scheduler, name='scheduler'),
    path('reports/', reports, name='reports'),
    path('settings/', settings_page, name='settings'),
    path('contacts/telegram-bots/', telegram_bots_manage, name='telegram_bots_manage'),
    path('contacts/telegram-groups/', telegram_groups_manage, name='telegram_groups_manage'),
    path('contacts/mail-accounts/', mail_accounts_manage, name='mail_accounts_manage'),
    path('contacts/ftp-accounts/', ftp_accounts_manage, name='ftp_accounts_manage'),
    path('sap-scan/', sap_scan, name='sap_scan'),
    path('sap-apply/', sap_apply, name='sap_apply'),
    path('sap-run/', sap_run, name='sap_run'),
    path('sap-template/list/', sap_template_list, name='sap_template_list'),
    path('sap-template/get/', sap_template_get, name='sap_template_get'),
    path('sap-template/save/', sap_template_save, name='sap_template_save'),
    path('sap-template/delete/', sap_template_delete, name='sap_template_delete'),
    path('sap-process/', sap_process_list, name='sap_process_list'),
    path('sap-process/<int:process_id>/', sap_process_builder, name='sap_process_builder'),
    path('sap-process/<int:process_id>/delete/', sap_process_delete, name='sap_process_delete'),
    path('sap-process/<int:process_id>/steps/save/', sap_process_step_save, name='sap_process_step_save'),
    path('sap-process/<int:process_id>/rename/', sap_process_rename, name='sap_process_rename'),
    path('sap-process/<int:process_id>/runtime-settings/', sap_process_runtime_settings_save, name='sap_process_runtime_settings_save'),
    path('sap-process/<int:process_id>/run/', sap_process_run_preview, name='sap_process_run_preview'),
]
