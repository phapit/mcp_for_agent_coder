import base64
import logging
import os
import time

import anthropic
import openai

import observability

logger = logging.getLogger(__name__)

VISION_PROVIDER = os.getenv("VISION_PROVIDER", "openai")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_VISION_MODEL = os.getenv("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-5")

try:
    openai_vision_client = openai.OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception as e:
    logger.error(f"Failed to initialize OpenAI vision client: {e}", exc_info=True)
    openai_vision_client = None

try:
    anthropic_vision_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
except Exception as e:
    logger.error(f"Failed to initialize Anthropic vision client: {e}", exc_info=True)
    anthropic_vision_client = None

_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
}

CAPTION_PROMPT = (
    "Đây là một hình ảnh minh họa được trích từ file Excel đặc tả/yêu cầu thay đổi tính năng. "
    "Ngữ cảnh các dòng lân cận trong sheet:\n{context}\n\n"
    "Hãy mô tả bằng tiếng Việt, 1-3 câu, nội dung hình ảnh và thay đổi/tính năng mà nó đang minh họa."
)


class VisionProviderUnavailable(Exception):
    pass


def caption_image(image_bytes: bytes, ext: str, context_text: str) -> str:
    """Gọi vision LLM (OpenAI hoặc Anthropic, theo VISION_PROVIDER) để mô tả nội dung ảnh."""
    media_type = _MEDIA_TYPES.get(ext.lower(), "image/png")
    b64_data = base64.b64encode(image_bytes).decode("utf-8")
    prompt = CAPTION_PROMPT.format(context=context_text or "(không có)")

    started = time.perf_counter()
    if VISION_PROVIDER == "anthropic":
        if not anthropic_vision_client:
            raise VisionProviderUnavailable("ANTHROPIC_API_KEY is not configured.")
        message = anthropic_vision_client.messages.create(
            model=ANTHROPIC_VISION_MODEL,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64_data},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        observability.log_llm_usage(
            logger, "llm_completion", model=ANTHROPIC_VISION_MODEL, started=started,
            completion=message, purpose="vision_caption",
        )
        return message.content[0].text.strip()

    if not openai_vision_client:
        raise VisionProviderUnavailable("OPENAI_API_KEY is not configured.")
    completion = openai_vision_client.chat.completions.create(
        model=OPENAI_VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64_data}"}},
                ],
            }
        ],
        max_tokens=300,
    )
    observability.log_llm_usage(
        logger, "llm_completion", model=OPENAI_VISION_MODEL, started=started,
        completion=completion, purpose="vision_caption",
    )
    return completion.choices[0].message.content.strip()
