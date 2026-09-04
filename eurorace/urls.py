"""
URL configuration for eurorace project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from allauth.account.views import ConfirmEmailView, PasswordResetView
from dj_rest_auth.registration.views import VerifyEmailView, ResendEmailVerificationView, RegisterView
from dj_rest_auth.serializers import PasswordResetConfirmSerializer
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, reverse
from django.urls.conf import include, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as static_serve

from eurorace.views import LocationReportViewSet, TaskViewSet, TeamViewSet, live_dashboard, live_dashboard_data

api_router = DefaultRouter()

api_router.register("location-reports", LocationReportViewSet, basename="location-reports")
api_router.register("tasks", TaskViewSet, basename="tasks")
api_router.register("teams", TeamViewSet, basename="teams")

urlpatterns = [
    path("", live_dashboard, name="live-dashboard-root"),
    path("live/", live_dashboard, name="live-dashboard"),
    path("live/data/", live_dashboard_data, name="live-dashboard-data"),
    path("admin/", admin.site.urls),
    path("api/auth/", include("dj_rest_auth.urls")),
    path("api/auth/registration/", include("dj_rest_auth.registration.urls")),

    path("api/auth/registration/", RegisterView.as_view(), name='rest_register'),
    path("api/auth/registration/", RegisterView.as_view(), name='rest_register'),
    re_path(r"api/auth/registration/verify-email/?$", VerifyEmailView.as_view(), name="rest_verify_email"),
    re_path(r"api/auth/registration/resend-email/?$", ResendEmailVerificationView.as_view(), name="rest_resend_email"),

    re_path(
        r"account-confirm-email/(?P<key>[-:\w]+)/$", lambda *args, **kwargs: redirect(reverse("swagger-ui")),
        name="account_confirm_email",
    ),
    re_path(
        r"password_reset_confirm/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)$", lambda *args, **kwargs: redirect(reverse("swagger-ui")),
        name="password_reset_confirm",
    ),

    # YOUR PATTERNS
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # Optional UI:
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/", include(api_router.urls))
]

# Media always; static also in production (admin CSS/JS behind /euroapp via Daphne).
# django.conf.urls.static.static() is a no-op when DEBUG=False.
urlpatterns += [
    re_path(
        r"^media/(?P<path>.*)$",
        static_serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
    re_path(
        r"^static/(?P<path>.*)$",
        static_serve,
        {"document_root": settings.STATIC_ROOT},
    ),
]
if settings.DEBUG:
    # Keep helper for local DX; patterns above already cover the same paths.
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
