from django.contrib import admin
from .models import Conversation, Message, FileArtifact

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at')
    search_fields = ('user__username',)

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'role', 'content', 'created_at')
    search_fields = ('content',)
    list_filter = ('role', 'created_at')

@admin.register(FileArtifact)
class FileArtifactAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'path', 'filename','created_at')
    search_fields = ('path',)
    list_filter = ('created_at',)
