from django.conf import settings
from django.db import models


class WatchlistItem(models.Model):
    """One company in one user's watchlist. Other users never see it."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='watchlist_items',
    )
    symbol = models.CharField(max_length=40)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'symbol'], name='unique_user_symbol'),
        ]

    def __str__(self):
        return f"{self.user} - {self.symbol}"