from django.contrib import admin
from .models import Conversation, Message, FileArtifact


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "llm_model", "daytona_volume_id", "daytona_volume_name", "created_at")
    search_fields = ("id", "user__username", "title", "llm_model", "daytona_volume_id", "daytona_volume_name")
    list_filter = ("agent_type", )
    date_hierarchy = "created_at"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("conversation__id", "content")


@admin.register(FileArtifact)
class FileArtifactAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "filename", "size_bytes", "created_at")
    search_fields = ("conversation__id", "filename", "path")
