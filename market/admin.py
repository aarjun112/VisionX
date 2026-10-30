from django.contrib import admin
from .models import DailyBar


@admin.register(DailyBar)
class DailyBarAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'date', 'open', 'high', 'low', 'close', 'volume')
    list_filter = ('symbol',)
    search_fields = ('symbol',)
    ordering = ('symbol', '-date')