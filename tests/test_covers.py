"""Тесты авто-обложек (F18): чистые функции ComfyUI/Unsplash клиентов."""

from tg_repost.covers.comfyui import extract_first_image, inject_prompt_into_workflow
from tg_repost.covers.unsplash import UnsplashClient


def test_inject_prompt_into_workflow_replaces_text():
    workflow = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}}}
    result = inject_prompt_into_workflow(workflow, "6", "new prompt")
    assert result is not None
    assert result["6"]["inputs"]["text"] == "new prompt"
    # Исходный workflow не мутирован (глубокая копия).
    assert workflow["6"]["inputs"]["text"] == "old"


def test_inject_prompt_into_workflow_missing_node():
    assert inject_prompt_into_workflow({}, "6", "x") is None


def test_inject_prompt_into_workflow_missing_inputs_key():
    workflow = {"6": {"class_type": "CLIPTextEncode"}}
    result = inject_prompt_into_workflow(workflow, "6", "prompt")
    assert result["6"]["inputs"]["text"] == "prompt"


def test_extract_first_image_found():
    entry = {"outputs": {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}}}
    assert extract_first_image(entry) == {"filename": "a.png", "subfolder": "", "type": "output"}


def test_extract_first_image_none_when_no_outputs():
    assert extract_first_image({"outputs": {}}) is None
    assert extract_first_image({}) is None


def test_extract_first_image_skips_empty_image_lists():
    entry = {"outputs": {"1": {"images": []}, "2": {"images": [{"filename": "b.png"}]}}}
    assert extract_first_image(entry) == {"filename": "b.png"}


def test_unsplash_extract_image_url_prefers_regular():
    data = {"urls": {"regular": "https://x/regular.jpg", "full": "https://x/full.jpg"}}
    assert UnsplashClient.extract_image_url(data) == "https://x/regular.jpg"


def test_unsplash_extract_image_url_fallback_to_full():
    data = {"urls": {"full": "https://x/full.jpg"}}
    assert UnsplashClient.extract_image_url(data) == "https://x/full.jpg"


def test_unsplash_extract_image_url_missing():
    assert UnsplashClient.extract_image_url({}) is None


def test_unsplash_configured_false_without_key():
    # Тестовое окружение (conftest.py) не задаёт UNSPLASH_ACCESS_KEY.
    assert UnsplashClient().configured is False
