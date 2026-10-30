from django.db import models

# watchlist model lives in its own file; importing it here registers it with Django
from .watchlist_models import WatchlistItem  # noqa: F401


class DailyBar(models.Model):
    """One trading day for a company, or for the NEPSE index."""
    symbol = models.CharField(max_length=40)
    date = models.DateField()
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    volume = models.FloatField(default=0)

    class Meta:
        ordering = ['symbol', 'date']
        constraints = [
            models.UniqueConstraint(fields=['symbol', 'date'], name='unique_symbol_date'),
        ]
        indexes = [
            models.Index(fields=['symbol', 'date']),
        ]

    def __str__(self):
        return f"{self.symbol} {self.date} {self.close}"