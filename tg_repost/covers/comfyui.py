"""Клиент локального ComfyUI (F18) — уникальная AI-генерация обложки.

Использует стандартный API ComfyUI: `POST /prompt` (постановка в очередь),
`GET /history/{id}` (поллинг готовности), `GET /view` (скачивание картинки).

Workflow специфичен для установки пользователя (чекпойнт, сэмплер, разрешение)
— общего шаблона на все случаи не существует. Берётся из файла в формате API
(экспорт из ComfyUI: Settings → Enable Dev mode → Save (API Format)),
путь — `COMFYUI_WORKFLOW_PATH`. `COMFYUI_POSITIVE_NODE_ID` — id узла
CLIPTextEncode (ключ в JSON), куда подставляется текст промпта.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import httpx

from tg_repost.config import get_settings
from tg_repost.logging_conf import get_logger

logger = get_logger(__name__)


def inject_prompt_into_workflow(workflow: dict, node_id: str, prompt: str) -> dict | None:
    """Подставить текст промпта в узел `node_id` workflow (чистая функция).

    Возвращает изменённую копию workflow, либо None, если узла нет.
    """
    if node_id not in workflow:
        return None
    result = copy.deepcopy(workflow)
    node = result[node_id]
    node.setdefault("inputs", {})["text"] = prompt
    return result


def extract_first_image(history_entry: dict) -> dict | None:
    """Достать описание первого изображения из записи `/history/{id}` (чистая функция).

    Возвращает {"filename", "subfolder", "type"} либо None, если изображений нет.
    """
    outputs = history_entry.get("outputs") or {}
    for node_output in outputs.values():
        images = node_output.get("images") or []
        if images:
            return images[0]
    return None


class ComfyUIClient:
    """Асинхронный клиент генерации изображения через локальный ComfyUI."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.comfyui_base_url.rstrip("/")
        self._workflow_path = settings.comfyui_workflow_path
        self._node_id = settings.comfyui_positive_node_id
        self._poll_attempts = settings.comfyui_poll_attempts
        self._poll_interval = settings.comfyui_poll_interval_seconds

    @property
    def configured(self) -> bool:
        """Заданы ли путь к workflow и id узла промпта, существует ли файл."""
        return bool(
            self._workflow_path and self._node_id and Path(self._workflow_path).exists()
        )

    def _load_workflow(self) -> dict:
        return json.loads(Path(self._workflow_path).read_text(encoding="utf-8"))

    async def generate_image_bytes(self, prompt: str) -> bytes | None:
        """Сгенерировать изображение по промпту. None при ошибке/таймауте."""
        if not self.configured:
            logger.warning(
                "ComfyUI не настроен (COMFYUI_WORKFLOW_PATH/COMFYUI_POSITIVE_NODE_ID)"
            )
            return None

        try:
            base_workflow = self._load_workflow()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось загрузить workflow ComfyUI: %s", exc)
            return None

        workflow = inject_prompt_into_workflow(base_workflow, self._node_id, prompt)
        if workflow is None:
            logger.warning(
                "Узел '%s' не найден в workflow ComfyUI — проверь COMFYUI_POSITIVE_NODE_ID",
                self._node_id,
            )
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                submit = await client.post(
                    f"{self._base_url}/prompt", json={"prompt": workflow}
                )
                submit.raise_for_status()
                prompt_id = submit.json().get("prompt_id")
                if not prompt_id:
                    logger.warning("ComfyUI не вернул prompt_id")
                    return None

                image_info = await self._poll_history(client, prompt_id)
                if image_info is None:
                    logger.warning("ComfyUI: таймаут ожидания генерации (%s)", prompt_id)
                    return None

                view = await client.get(
                    f"{self._base_url}/view",
                    params={
                        "filename": image_info["filename"],
                        "subfolder": image_info.get("subfolder", ""),
                        "type": image_info.get("type", "output"),
                    },
                )
                view.raise_for_status()
                return view.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("ComfyUI ошибка: %s", exc)
            return None

    async def _poll_history(self, client: httpx.AsyncClient, prompt_id: str) -> dict | None:
        for _ in range(self._poll_attempts):
            await asyncio.sleep(self._poll_interval)
            response = await client.get(f"{self._base_url}/history/{prompt_id}")
            if response.status_code != 200:
                continue
            entry = response.json().get(prompt_id)
            if not entry:
                continue
            image_info = extract_first_image(entry)
            if image_info is not None:
                return image_info
        return None
