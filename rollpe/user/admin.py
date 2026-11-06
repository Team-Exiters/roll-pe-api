from django.contrib import admin

from user.models import ContentReport


def user_label(user):
    if user is None:
        return '삭제된 사용자'
    return f'{user.name} ({user.identifyCode or user.pk})'


@admin.register(ContentReport)
class ContentReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'targetType', 'reason', 'status', 'reporter', 'reported_user', 'createdAt')
    list_filter = ('status', 'targetType', 'reason')
    search_fields = ('=targetCode', 'description', 'snapshot__title')
    fields = ('targetType', 'targetCode', 'paperFK', 'heartFK', 'reporter', 'reported_user',
              'reason', 'description', 'snapshot', 'status', 'staffNote', 'createdAt', 'updatedAt')
    readonly_fields = ('reporter', 'reported_user', 'paperFK', 'heartFK', 'targetType', 'targetCode',
                       'reason', 'description', 'snapshot', 'createdAt', 'updatedAt')
    list_select_related = ('reporterFK', 'reportedUserFK')

    @admin.display(description='신고자')
    def reporter(self, obj):
        return user_label(obj.reporterFK)

    @admin.display(description='콘텐츠 작성자')
    def reported_user(self, obj):
        return user_label(obj.reportedUserFK)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
