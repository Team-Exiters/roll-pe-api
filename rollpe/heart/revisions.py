from rest_framework.views import APIView

from heart.apis import can_read
from heart.models import Heart
from user.serializers import UserViewSerializer
from utils.response import Response
from utils.share.functions import is_valid_uuid


class HeartRevisionsAPI(APIView):
    def get(self, request):
        if not request.user.is_authenticated:
            return Response(status=401)
        code = request.query_params.get('hcode')
        if not is_valid_uuid(code):
            return Response(status=404)
        heart = Heart.objects.select_related('paperFK').filter(code=code).first()
        if heart is None:
            return Response(status=404)
        if not can_read(heart.paperFK, request.user):
            return Response(status=403)
        if request.user.pk not in (heart.userFK_id, heart.paperFK.hostFK_id):
            return Response(status=403)
        # Existing imports or legacy writes may have no version zero yet.
        revisions = [{
            'number': version.number, 'content': version.content, 'color': version.color,
            'recordedAt': version.recordedAt.isoformat(), 'baseline': version.baseline,
            'editor': UserViewSerializer(version.editorFK).data if version.editorFK_id else None,
        } for version in heart.revisions.select_related('editorFK').all()]
        if not revisions:
            revisions = [{'number': 0, 'content': heart.context, 'color': heart.colorFK.name,
                          'recordedAt': heart.updatedAt.isoformat(), 'baseline': True,
                          'editor': UserViewSerializer(heart.userFK).data}]
        return Response(status=200, data={'heartCode': str(heart.code), 'revisions': revisions})
