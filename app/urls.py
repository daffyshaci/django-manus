from django.urls import path
from . import views

urlpatterns = [
    path('chat/', views.chat, name='chat'),
    path('chat/<str:conversation_id>/', views.chat_detail, name='chat_detail'),
]
