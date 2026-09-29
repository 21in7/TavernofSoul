from django.urls import path
from django.views.generic.base import TemplateView
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('ads.txt', views.Ads),
    path('private.txt', TemplateView.as_view(template_name='private.txt', content_type='text/plain'))
]
