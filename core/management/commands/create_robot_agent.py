import secrets

from django.core.management.base import BaseCommand, CommandError

from core.models import RobotAgent


class Command(BaseCommand):
    help = "Robot ajanı oluşturur veya tokenını yeniler."

    def add_arguments(self, parser):
        parser.add_argument("--code", required=True, help="Ajan kodu (örn robot-01)")
        parser.add_argument("--name", required=True, help="Ajan adı")
        parser.add_argument("--token", required=False, help="Ajan token (verilmezse otomatik üretilir)")
        parser.add_argument("--disabled", action="store_true", help="Ajanı pasif oluştur")

    def handle(self, *args, **options):
        code = str(options["code"] or "").strip()
        name = str(options["name"] or "").strip()
        token = str(options.get("token") or "").strip() or secrets.token_urlsafe(32)

        if not code:
            raise CommandError("--code zorunlu")
        if not name:
            raise CommandError("--name zorunlu")

        agent, created = RobotAgent.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "is_enabled": not bool(options.get("disabled")),
                "status": "offline",
                "token_hash": "",
            },
        )
        agent.name = name
        agent.is_enabled = not bool(options.get("disabled"))
        agent.set_token(token)
        agent.save()

        state = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Agent {state}: {agent.code}"))
        self.stdout.write(self.style.WARNING(f"TOKEN: {token}"))
