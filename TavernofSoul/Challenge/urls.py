from django.urls import path

from . import views

app_name = 'Challenge'

urlpatterns = [
    path('', views.index, name='index'),
]


