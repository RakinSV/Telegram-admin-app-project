"""Тесты авто-обложек (F18): чистые функции ComfyUI/Unsplash/openai клиентов
плюс дефолты промптов — картинка должна быть БЕЗ текста и надписей, а сцена
ассоциативной, а не буквальной иллюстрацией заголовка."""

import pytest

from tg_repost.config import get_settings
from tg_repost.covers.comfyui import extract_first_image, inject_prompt_into_workflow
from tg_repost.covers.openai_compatible import _decode_image
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


def test_decode_image_valid_base64():
    import base64

    payload = base64.b64encode(b"fake-image-bytes").decode()
    assert _decode_image(payload) == b"fake-image-bytes"


def test_decode_image_none_when_missing():
    assert _decode_image(None) is None
    assert _decode_image("") is None


def test_decode_image_none_when_not_valid_base64():
    assert _decode_image("not-valid-base64!!!") is None


# --- негативный промпт ComfyUI ---


def test_inject_negative_prompt_into_second_node():
    """Позитивный и негативный промпты подставляются в РАЗНЫЕ узлы, не
    затирая друг друга — обе правки должны сосуществовать в одном workflow."""
    workflow = {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
    }
    with_positive = inject_prompt_into_workflow(workflow, "6", "a cat")
    result = inject_prompt_into_workflow(with_positive, "7", "text, watermark")
    assert result is not None
    assert result["6"]["inputs"]["text"] == "a cat"
    assert result["7"]["inputs"]["text"] == "text, watermark"


def test_default_comfyui_negative_prompt_bans_text_in_image():
    # Без явного запрета модели дорисовывают надписи на «новостных» картинках.
    negative = get_settings().comfyui_negative_prompt.lower()
    for banned in ("text", "watermark", "logo", "caption"):
        assert banned in negative


# --- дефолты промптов обложек: без текста в кадре, ассоциативная сцена ---


def test_openai_cover_prompt_forbids_text_and_asks_for_association():
    template = get_settings().cover_image_prompt_template
    assert "{post_text}" in template
    lowered = template.lower()
    assert "no text" in lowered
    # Запрет повторён и в начале, и в конце намеренно: одного упоминания в
    # середине промпта моделям генерации изображений стабильно не хватает.
    assert lowered.count("no ") >= 2
    assert "associat" in lowered  # associated / association — просим ассоциацию
    assert "literal" in lowered   # ...и явно запрещаем буквальную иллюстрацию


def test_openai_cover_prompt_avoids_the_generated_look():
    """Картинка не должна выглядеть сгенерированной. Слова вроде «cinematic»,
    «8k», «masterpiece» тянут ровно в тот глянцевый рендер, который
    опознаётся мгновенно, — их в промпте быть не должно."""
    template = get_settings().cover_image_prompt_template
    lowered = template.lower()
    for banned in ("cinematic", "8k", "masterpiece", "highly detailed", "trending on"):
        assert banned not in lowered, f"промпт тянет в AI-глянец: {banned}"


def test_openai_cover_prompt_asks_for_documentary_imperfection():
    """Обратное требование: репортажный кадр, зерно, естественный свет —
    именно этого генераторы сами не делают."""
    lowered = get_settings().cover_image_prompt_template.lower()
    for wanted in ("documentary", "grain", "available light", "35mm"):
        assert wanted in lowered


def test_openai_cover_prompt_avoids_faces():
    """Лица и руки — самый заметный провал генераторов: кадр без людей
    почти никогда не выдаёт происхождение."""
    lowered = get_settings().cover_image_prompt_template.lower()
    assert "no recognisable people" in lowered
    assert "face not visible" in lowered


def test_openai_cover_prompt_avoids_symmetry_and_centering():
    lowered = get_settings().cover_image_prompt_template.lower()
    assert "off-centre" in lowered
    assert "avoid perfect symmetry" in lowered


def test_comfyui_negative_covers_both_text_and_generated_look():
    """Негатив закрывает две группы: текст в кадре и признаки генерации."""
    negative = get_settings().comfyui_negative_prompt.lower()
    for banned in ("text", "watermark", "logo"):
        assert banned in negative
    for banned in ("3d render", "oversaturated", "neon", "deformed hands", "perfect symmetry"):
        assert banned in negative


def test_cover_search_prompt_forbids_text_bearing_scenes():
    template = get_settings().cover_search_prompt_template
    assert "{post_text}" in template
    lowered = template.lower()
    # Запрещаем как раз те слова, по которым и Unsplash, и ComfyUI отдают
    # картинку с надписью в кадре.
    for banned in ("banner", "poster", "infographic"):
        assert banned in lowered


@pytest.mark.parametrize("size", ["1792x1024", "1024x1024"])
def test_cover_image_size_is_a_valid_choice(size):
    from tg_repost.webui.settings_store import SETTINGS_GROUPS

    field = next(
        f
        for g in SETTINGS_GROUPS
        for f in g.fields
        if f.name == "cover_openai_image_size"
    )
    assert field.choices is not None
    assert size in field.choices


def test_cover_image_size_default_is_wide():
    # Квадрат обрезается по краям в ленте Telegram, из кадра уезжает как раз
    # композиционно важное — дефолт должен быть широким.
    width, height = get_settings().cover_openai_image_size.split("x")
    assert int(width) > int(height)
