from django import forms

from .models import FTPAccount, MailAccount, TelegramBot, TelegramGroup


class TelegramBotForm(forms.ModelForm):
    bot_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        help_text='Bos birakirsan mevcut token korunur.',
    )

    class Meta:
        model = TelegramBot
        fields = [
            'name',
            'bot_username',
            'bot_token',
            'default_parse_mode',
            'description',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['bot_token'].required = False

    def clean_bot_token(self):
        value = (self.cleaned_data.get('bot_token') or '').strip()
        if value:
            return value
        if self.instance and self.instance.pk:
            return self.instance.bot_token
        raise forms.ValidationError('Bot token zorunludur.')


class TelegramGroupForm(forms.ModelForm):
    class Meta:
        model = TelegramGroup
        fields = [
            'name',
            'chat_id',
            'default_bot',
            'owners',
            'description',
            'is_active',
        ]


class MailAccountForm(forms.ModelForm):
    smtp_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        help_text='Bos birakirsan mevcut sifre korunur.',
    )

    class Meta:
        model = MailAccount
        fields = [
            'name',
            'email',
            'from_name',
            'smtp_host',
            'smtp_port',
            'smtp_username',
            'smtp_password',
            'use_tls',
            'use_ssl',
            'is_active',
            'description',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['smtp_password'].required = False

    def clean_smtp_password(self):
        value = (self.cleaned_data.get('smtp_password') or '').strip()
        if value:
            return value
        if self.instance and self.instance.pk:
            return self.instance.smtp_password
        raise forms.ValidationError('SMTP sifresi zorunludur.')


class FTPAccountForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        help_text='Bos birakirsan mevcut sifre korunur.',
    )

    class Meta:
        model = FTPAccount
        fields = [
            'name',
            'protocol',
            'host',
            'port',
            'username',
            'password',
            'remote_base_path',
            'is_active',
            'description',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['password'].required = False

    def clean_password(self):
        value = (self.cleaned_data.get('password') or '').strip()
        if value:
            return value
        if self.instance and self.instance.pk:
            return self.instance.password
        raise forms.ValidationError('FTP sifresi zorunludur.')
