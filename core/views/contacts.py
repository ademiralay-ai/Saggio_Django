"""Generic contact CRUD views (telegram bots/groups, mail, ftp).

Originally lived in ``core/views.py``.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.shortcuts import get_object_or_404, redirect, render

from ..firebase_service import ContactConfigService
from ..forms import (
	FTPAccountForm,
	MailAccountForm,
	TelegramBotForm,
	TelegramGroupForm,
)
from ..models import FTPAccount, MailAccount, TelegramBot, TelegramGroup
from ..services.notification_service import (
	_send_ftp_test,
	_send_mail_test,
	_send_telegram_group_test,
)


def _manage_contact_entity(request, *, model, form_class, page_title, page_subtitle, success_message, test_handler=None, firebase_sync_handler=None, firebase_entity_name=None, current_key=''):
	edit_id = request.GET.get('edit')
	edit_instance = model.objects.filter(pk=edit_id).first() if edit_id else None
	create_form = form_class(prefix='create')
	edit_form = form_class(instance=edit_instance, prefix='edit') if edit_instance else None
	error_message = ''

	if request.method == 'POST':
		action = request.POST.get('action', '')
		if action == 'create':
			create_form = form_class(request.POST, prefix='create')
			if create_form.is_valid():
				obj = create_form.save()
				if firebase_sync_handler is not None:
					firebase_sync_handler(obj)
				return redirect(f'{request.path}?ok=create')
			error_message = 'Kayit olusturulamadi. Alanlari kontrol edin.'
		elif action == 'update':
			object_id = request.POST.get('object_id', '')
			instance = get_object_or_404(model, pk=object_id)
			edit_form = form_class(request.POST, instance=instance, prefix='edit')
			if edit_form.is_valid():
				obj = edit_form.save()
				if firebase_sync_handler is not None:
					firebase_sync_handler(obj)
				return redirect(f'{request.path}?ok=update')
			error_message = 'Kayıt güncellenemedi. Alanları kontrol edin.'
		elif action == 'delete':
			object_id = request.POST.get('object_id', '')
			instance = get_object_or_404(model, pk=object_id)
			if firebase_entity_name:
				ContactConfigService.delete_entity(firebase_entity_name, instance.id)
			instance.delete()
			return redirect(f'{request.path}?ok=delete')
		elif action == 'test' and test_handler is not None:
			object_id = request.POST.get('object_id', '')
			instance = get_object_or_404(model, pk=object_id)
			ok, msg = test_handler(instance, request.POST)
			state = 'ok' if ok else 'err'
			query = urlencode({'test': state, 'msg': msg or ''})
			return redirect(f'{request.path}?{query}')

	ok_action = request.GET.get('ok', '')
	status_message = ''
	test_state = request.GET.get('test', '')
	test_msg = request.GET.get('msg', '')
	if ok_action == 'create':
		status_message = f'{success_message} olusturuldu.'
	elif ok_action == 'update':
		status_message = f'{success_message} güncellendi.'
	elif ok_action == 'delete':
		status_message = f'{success_message} silindi.'
	elif test_state == 'ok':
		status_message = test_msg or 'Test islemi basarili.'
	elif test_state == 'err':
		error_message = test_msg or 'Test islemi basarisiz.'

	return render(
		request,
		'core/contact_crud.html',
		{
			'current': current_key,
			'page_title': page_title,
			'page_subtitle': page_subtitle,
			'entity_name': success_message,
			'entity_type': model._meta.model_name,
			'items': model.objects.all(),
			'create_form': create_form,
			'edit_form': edit_form,
			'edit_instance': edit_instance,
			'status_message': status_message,
			'error_message': error_message,
		},
	)


def telegram_bots_manage(request):
	return _manage_contact_entity(
		request,
		model=TelegramBot,
		form_class=TelegramBotForm,
		page_title='Telegram Botlari',
		page_subtitle='Bot token, parse mode ve aktiflik durumunu yonetin',
		success_message='Telegram botu',
		current_key='telegram_bots_manage',
		firebase_sync_handler=ContactConfigService.sync_telegram_bot,
		firebase_entity_name='telegram_bots',
	)


def telegram_groups_manage(request):
	return _manage_contact_entity(
		request,
		model=TelegramGroup,
		form_class=TelegramGroupForm,
		page_title='Telegram Gruplari',
		page_subtitle='Sahip ekipler, chat id ve varsayilan bot baglantisini yonetin',
		success_message='Telegram grubu',
		current_key='telegram_groups_manage',
		test_handler=_send_telegram_group_test,
		firebase_sync_handler=ContactConfigService.sync_telegram_group,
		firebase_entity_name='telegram_groups',
	)


def mail_accounts_manage(request):
	return _manage_contact_entity(
		request,
		model=MailAccount,
		form_class=MailAccountForm,
		page_title='Mail Hesaplari',
		page_subtitle='SMTP hesaplari ve gonderim ayarlarini yonetin',
		success_message='Mail hesabi',
		current_key='mail_accounts_manage',
		test_handler=_send_mail_test,
		firebase_sync_handler=ContactConfigService.sync_mail_account,
		firebase_entity_name='mail_accounts',
	)


def ftp_accounts_manage(request):
	return _manage_contact_entity(
		request,
		model=FTPAccount,
		form_class=FTPAccountForm,
		page_title='FTP Hesaplari',
		page_subtitle='FTP/SFTP baglanti profillerini yonetin',
		success_message='FTP hesabi',
		current_key='ftp_accounts_manage',
		test_handler=_send_ftp_test,
		firebase_sync_handler=ContactConfigService.sync_ftp_account,
		firebase_entity_name='ftp_accounts',
	)





