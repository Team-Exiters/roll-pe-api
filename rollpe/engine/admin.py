from django.contrib import admin

from engine.models import Inquiry


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ('id', 'category', 'email', 'status', 'createdAt')
    list_filter = ('category', 'status')
    search_fields = ('email', 'content')
    fields = ('userFK', 'email', 'category', 'content', 'status', 'staffNote', 'createdAt', 'updatedAt')
    readonly_fields = ('userFK', 'email', 'category', 'content', 'createdAt', 'updatedAt')

    def has_add_permission(self, request):
        return False
