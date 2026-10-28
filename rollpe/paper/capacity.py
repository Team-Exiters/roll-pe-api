from heart.models import Heart
from utils.response import Response


def capacity_error(paper, user):
    """Mutating callers must hold the paper lock until participation is saved."""
    maximum = paper.sizeFK.query.get('max', 12)
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        maximum = 12
    # The host counts once. Legacy authors still occupy a place even without
    # membership; pending invitations and a receiver-only account do not.
    participants = {paper.hostFK_id}
    participants.update(paper.invitingUser.values_list('pk', flat=True))
    participants.update(Heart.objects.filter(paperFK=paper).values_list('userFK_id', flat=True))
    if user.pk not in participants and len(participants) >= maximum:
        return Response(status=409, data={'reason': 'full'},
                        msg='참여 정원이 가득 찼습니다. 자리가 생긴 후 다시 시도해주세요.')
    return None
