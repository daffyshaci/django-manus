from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from celery import shared_task  # type: ignore

from app.agent.manus import Manus
from app.logger import logger


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def run_manus_agent(self, prompt: str, conversation_id: Optional[str] = None, agent_kwargs: Optional[Dict[str, Any]] = None) -> str:
    """
    Jalankan Manus agent sebagai Celery task.

    Args:
        prompt: Teks input untuk agent.
        conversation_id: ID percakapan (opsional). Jika diberikan, agent akan otomatis
            melakukan persistensi ke Django ORM menggunakan hook yang sudah disiapkan.
        agent_kwargs: Argumen tambahan untuk pembuatan Manus (opsional), misalnya konfigurasi alat.

    Returns:
        Hasil string keluaran dari agent (jika ada). Perlu diingat, di settings Celery Anda
        CELERY_TASK_IGNORE_RESULT disetel True, sehingga nilai balik ini biasanya diabaikan
        oleh backend result Celery.
    """
    if not prompt or not str(prompt).strip():
        logger.warning("Empty prompt provided to run_manus_agent.")
        # Jika conversation_id diberikan, kita tetap lanjut karena history akan dimuat dari DB
        if not conversation_id:
            return ""

    # Susun kwargs untuk Manus.create()
    kwargs: Dict[str, Any] = dict(agent_kwargs or {})
    if conversation_id and "conversation_id" not in kwargs:
        kwargs["conversation_id"] = str(conversation_id)

    async def _run() -> str:
        agent = await Manus.create(**kwargs)
        try:
            logger.warning("Processing your request via Manus agent (Celery task)...")
            # Jika conversation_id tersedia, history (termasuk pesan user terbaru) sudah dimuat,
            # jadi jangan duplikasi dengan mengirim prompt lagi.
            if conversation_id:
                result = await agent.run(None)
            else:
                result = await agent.run(prompt)
            logger.info("Request processing completed.")
            return "done"
        finally:
            # Pastikan resource agent dibersihkan
            await agent.cleanup()


    # Jalankan konteks async di dalam task Celery sync
    return asyncio.run(_run())
