from django.contrib.auth import views as auth_views
from django.urls import path
from . import views, watchlist_views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('company/<path:symbol>/', views.company_detail, name='company'),

    path('watchlist/', watchlist_views.watchlist, name='watchlist'),
    path('watchlist/add/', watchlist_views.watchlist_add, name='watchlist_add'),
    path('watchlist/remove/', watchlist_views.watchlist_remove, name='watchlist_remove'),

    path('signup/', views.signup, name='signup'),
    path('login/', auth_views.LoginView.as_view(
        template_name='market/login.html',
        redirect_authenticated_user=True,
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]