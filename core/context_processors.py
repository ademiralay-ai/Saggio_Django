from .models import RobotAgent


def footer_robots(request):
    """Her template'e footer ticker için robot listesi ekler."""
    agents = list(
        RobotAgent.objects.filter(is_enabled=True)
        .order_by('code')
        .values('code', 'name', 'status')
    )
    return {'footer_robots': agents}
