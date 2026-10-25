from django.contrib import admin
from heart.models import Heart, HeartRevision


class HeartRevisionInline(admin.TabularInline):
    model = HeartRevision
    fields = ('number', 'content', 'color', 'editorFK', 'recordedAt', 'baseline')
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Heart)
class HeartAdmin(admin.ModelAdmin):
    list_display = ('id', 'paperFK', 'userFK', 'revisionCount')
    readonly_fields = ('paperFK', 'userFK', 'code', 'context', 'colorFK', 'location', 'revisionCount', 'createdAt', 'updatedAt')
    inlines = [HeartRevisionInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
