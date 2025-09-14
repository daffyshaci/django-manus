from django.shortcuts import render

def chat(request):
    return render(request, 'chat.html')

def chat_detail(request, conversation_id):
    return render(request, 'chat_detail.html', {'conversation_id': conversation_id})
