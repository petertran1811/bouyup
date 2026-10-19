"""The language the seller picked in the UI (VI/EN/ZH switch, ``X-BU-Lang`` header).

Vietnamese is the source language. Only text written for the seller at request time (Agent 2's chat
replies, the offer explanation) follows the choice; stored records, events and staff text stay in
Vietnamese."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

LANGS = ("vi", "en", "zh")
_lang: ContextVar[str] = ContextVar("bu_lang", default="vi")


def normalize(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v.startswith("zh"):
        return "zh"
    if v.startswith("en"):
        return "en"
    return "vi"


def set_lang(value: str | None) -> None:
    _lang.set(normalize(value))


def lang() -> str:
    return _lang.get()


def pick(vi: str, en: str, zh: str) -> str:
    """The sentence in the current language."""
    return {"en": en, "zh": zh}.get(_lang.get(), vi)


# Said to the model (Agent 2 and the explanation rewrite) so it answers in the seller's language.
MODEL_LANGUAGE = {
    "vi": "",
    "en": ("\nLANGUAGE: the seller uses the app in English. Reply ONLY in clear, natural English (address the seller as "
           "'you', speak as 'I'). Write amounts with full digits and comma thousands separators (100,000 CNY), never "
           "'k' or words for numbers."),
    "zh": ("\n语言：卖家使用简体中文界面。只用简体中文回答，称呼卖家为“您”，自称“我”。金额一律写完整阿拉伯数字并用逗号分隔千位"
           "（例如 100,000 元），不要写“万”“千”等汉字数量单位。"),
}


@contextmanager
def forced(value: str) -> Iterator[None]:
    """Write in one language whatever the request asked for (text that is stored, e.g. the offer explanation)."""
    token = _lang.set(normalize(value))
    try:
        yield
    finally:
        _lang.reset(token)
