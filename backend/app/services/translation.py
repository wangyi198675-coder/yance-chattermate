"""Window178 mature translation execution owner.

DeepL owns translation execution. ChatterMate remains the only data/control plane:
ChatHistory.message is source truth, ChatHistory.attributes holds the derived
projection, and Customer.meta_data holds the per-contact language preference.
There is deliberately no translation table, cache, worker, scheduler, model
runtime, provider registry, or delivery path in this module.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
import re
from typing import Iterable, Optional
import unicodedata
from zoneinfo import ZoneInfo

import httpx
from pypinyin import lazy_pinyin

from app.core.encryption import decrypt_json, encrypt_json

TRANSLATION_ATTR_KEY = "yance_translation"
OUTBOUND_PAIRING_ATTR_KEY = "yance_translation_pairing"
CONTACT_META_KEY = "yance_translation"
CHINESE_TARGET = "ZH-HANS"
STYLE_POLICY = "persona_chat_preserve_v1"

_TARGET_CODES = {
    "de": "DE",
    "en": "EN-US",
    "en-us": "EN-US",
    "en-gb": "EN-GB",
    "it": "IT",
    "ro": "RO",
    "tr": "TR",
    "ko": "KO",
    "zh": "ZH-HANS",
    "zh-cn": "ZH-HANS",
    "zh-hans": "ZH-HANS",
    "zh-tw": "ZH-HANT",
    "zh-hant": "ZH-HANT",
    "fr": "FR",
    "es": "ES",
    "pt": "PT-PT",
    "pt-pt": "PT-PT",
    "pt-br": "PT-BR",
    "nl": "NL",
    "pl": "PL",
    "ru": "RU",
    "uk": "UK",
    "ja": "JA",
}

_SOURCE_CODES = {
    "de": "DE", "en": "EN", "it": "IT", "ro": "RO", "tr": "TR",
    "ko": "KO", "zh": "ZH", "fr": "FR", "es": "ES", "pt": "PT",
    "nl": "NL", "pl": "PL", "ru": "RU", "uk": "UK", "ja": "JA",
}

_CUSTOM_INSTRUCTION_TARGETS = {"de", "en", "es", "fr", "it", "ja", "ko", "zh"}

_STYLE_INSTRUCTIONS = [
    "Preserve the writer's existing persona, tone, brevity, familiarity, humor, flirtation, boundaries, and level of formality.",
    "Keep this like a real private chat message: preserve fragments, punctuation, line breaks, emoji, names, mentions, URLs, numbers, dates, times, and currencies.",
    "Do not turn casual chat into business or textbook prose. Do not explain, summarize, sanitize, embellish, or add facts.",
]

_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_MENTION_RE = re.compile(r"(?<!\w)@[\w.\-]+", re.UNICODE)
_NUMBER_RE = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?!\w)")
_CURRENCY_RE = re.compile(
    r"(?:[$€£¥₩]\s?[+-]?\d+(?:[.,]\d+)*|[+-]?\d+(?:[.,]\d+)*\s?(?:[$€£¥₩]|USD|EUR|GBP|CNY|RMB|KRW|JPY))",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(?:\d{1,4}[-/.]\d{1,2}(?:[-/.]\d{1,4})?)\b")
_TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:[:][0-5]\d)?\b")
_EMOJI_RE = re.compile(
    "[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF\ufe0f]",
    re.UNICODE,
)
_LATIN_NAME_RE = re.compile(r"(?<![.!?]\s)\b[A-ZÄÖÜ][A-Za-zÀ-ÖØ-öø-ÿÄÖÜäöüß'’-]{2,}\b")
# Unlike English, German capitalizes all nouns. Only explicit personal-name
# grammar is a sufficient signal; unqualified title-case is not.
_DE_NAME_TOKEN = r"[A-ZÄÖÜ][A-Za-zÀ-ÖØ-öø-ÿÄÖÜäöüß'’-]{2,}"
# High-confidence person introductions: an explicit title, identifying phrase,
# personal relationship role, or named actor with a communication predicate.
_DE_PERSON_NAME_PATTERNS = tuple(re.compile(pattern) for pattern in (
    rf"\b(?i:Herrn?|Frau|Dr\.?|Prof\.?|Professor(?:in)?)\s+(?P<name>{_DE_NAME_TOKEN})\b",
    rf"\b(?i:namens|heißt|heisse|genannt)\s+(?P<name>{_DE_NAME_TOKEN})\b",
    rf"\b(?i:Freundin|Freund|Kollegin|Kollege|Tochter|Sohn|Nachbarin|Nachbar|Chefin|Chef|Schwester|Bruder|Mutter|Vater|Cousine|Cousin|Tante|Onkel|Nichte|Neffe)\s+(?P<name>{_DE_NAME_TOKEN})\b",
))
# Bare capitalized German noun phrases after verbs or prepositions are
# ambiguous. Treat them only as *weak* evidence, with a conservative
# orthographic name-shape gate; do not equate German capitalization with names.
_DE_WEAK_PERSON_NAME_PATTERNS = tuple(re.compile(pattern) for pattern in (
    rf"\b(?i:mit|bei|an|von)\s+(?P<name>{_DE_NAME_TOKEN})\b(?=[^.!?\n]{{0,65}}\b(?i:gesprochen|telefoniert|gechattet|verabredet|geschrieben|übernachtet)\b)",
    rf"\b(?i:habe|hatte|haben|hat|werde|wird)\s+(?:(?i:ich|du|er|sie|wir|ihr)\s+)?(?P<name>{_DE_NAME_TOKEN})\s+(?:\w+\s+){{0,4}}(?i:getroffen|treffen|angerufen|anrufen|besucht|besuchen|gesehen|sehen|eingeladen)\b",
    rf"\b(?i:traf|treffe|sah|sehe|besuche|rief|frage|fragte)\s+(?i:ich|du|er|sie|wir|ihr)\s+(?P<name>{_DE_NAME_TOKEN})\b",
    rf"\b(?P<name>{_DE_NAME_TOKEN})\s+(?i:schreibt|telefoniert|chattet|antwortet|ruft|fragt)\b",
    rf"\b(?P<name>{_DE_NAME_TOKEN})\s+(?i:hat|hätte|wird)\s+(?:\w+\s+){{0,4}}(?i:geschrieben|telefoniert|angerufen|geantwortet|gefragt)\b",
))
_HAN_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
# A small script-level phonetic-character gate, NOT a dictionary of people.
# Pinyin alone collapses unrelated words and Chinese surnames into identical
# pronunciations: e.g. Lena -> 李娜 must NOT be accepted as Lena -> 莉娜.
# Unknown transliterations fail closed (provider output is never rewritten).
_ZH_TRANSLITERATION_HAN = frozenset(
    "安娜莉丽妮琳玛丽亚娅莎拉苏菲露西朱娅彼得克劳斯托马斯艾米"
    "杰森约翰乔治亨利埃伦伊莎贝尔凯蒂露易丝维多利亚"
)
# Require a syntactic slot for a person in the target, never an arbitrary
# substring from a Han run (e.g. 按那 inside 我按那个按钮说话).
_ZH_NAME_PREFIX_RE = re.compile(
    r"(?:^|[\s，,。！？?!；;：:（(]|和|跟|与|同|给|向|对|"
    r"见到(?:了)?|看到(?:了)?|遇到(?:了)?|认识(?:了)?|找(?:到)?|"
    r"拜访(?:了)?|联系(?:了)?|叫|名字是|朋友|姐妹|姐姐|妹妹|"
    r"哥哥|弟弟|妈妈|爸爸|母亲|父亲|同事|邻居|女儿|儿子|"
    r"今天|昨天|明天)$"
)
# Chinese has no spaces around names. A full Han-name candidate must end
# before a delimiter or recognizable *post-name grammar*, not merely before
# more Han characters. Otherwise 安娜 inside 安娜莉莎 or 莉娜 inside 莉娜安
# falsely confirms preservation of a different person's name.
# Unrecognized contiguous suffixes fail closed; never rewrite provider output.
_ZH_NAME_FOLLOW_RE = re.compile(
    r"^(?:$|[^\u3400-\u9fff]|"
    r"今天|昨天|明天|现在|刚才|刚刚|稍后|之后|以前|"
    r"正在|已经|一起|然后|"
    r"的|了|过|吗|呢|吧|啊|呀|"
    r"是|有|在|会|能|要|都|也|还|就|"
    r"说|聊|谈|通|写|回|发|来|去|到|走|看|见|问|答|"
    r"找|打|给|帮|买|吃|喝|做|住|玩|笑|哭|等|听)"
)
_NEGATIONS = {
    "de": ("nicht", "kein", "keine", "keinen", "niemals", "nie"),
    "en": ("not", "no", "never", "don't", "doesn't", "isn't", "can't", "won't"),
    "it": ("non", "mai", "nessun"),
    "ro": ("nu", "niciodată", "nici"),
    "tr": ("değil", "yok", "hayır"),
    "ko": ("안", "않", "못", "없"),
    "zh": ("不", "没", "沒有", "没有", "别", "無", "无"),
    "fr": ("pas", "jamais", "aucun"),
    "es": ("no", "nunca", "ningún"),
}


class TranslationProviderError(RuntimeError):
    """External translation owner failed or is unavailable."""


@dataclass(frozen=True)
class ProviderTranslation:
    text: str
    detected_source_language: Optional[str]
    model_type: Optional[str]


def utc_now_iso() -> str:
    return datetime.now(tz=ZoneInfo("UTC")).isoformat()


def source_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def language_root(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    return code.strip().lower().replace("_", "-").split("-", 1)[0] or None


def style_language_matches(style_language: Optional[str], target_language: Optional[str]) -> bool:
    if not style_language or not target_language:
        return False
    style = style_language.strip().lower().replace("_", "-")
    target = target_language.strip().lower().replace("_", "-")
    if "-" in style:
        return style == target
    return language_root(style) == language_root(target)


def normalize_target_language(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    return _TARGET_CODES.get(code.strip().lower().replace("_", "-"))


def normalize_source_language(code: Optional[str]) -> Optional[str]:
    root = language_root(code)
    return _SOURCE_CODES.get(root) if root else None


def public_language_code(code: Optional[str]) -> Optional[str]:
    root = language_root(code)
    return root


def infer_source_language(text: str) -> Optional[str]:
    if re.search(r"[\u3400-\u9fff\uf900-\ufaff]", text):
        return "zh"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    return None


def _counter(pattern: re.Pattern[str], text: str) -> Counter[str]:
    return Counter(pattern.findall(text))


def _has_negation(text: str, language: Optional[str]) -> bool:
    root = language_root(language)
    if not root or root not in _NEGATIONS:
        return False

    # Latin-script checks must be token-aware: substring matching makes ordinary
    # words such as "afternoon" look like English "no". Normalize curly
    # apostrophes first so chat typography such as “isn’t” is still detected.
    folded = text.casefold().replace("’", "'").replace("‘", "'")

    if root == "zh":
        # Bare 不 is common inside non-negative words such as 不过/不過
        # ("however"). Keep a deliberately narrow, reject-only signal set.
        return bool(re.search(r"(?:没(?:有)?|沒有|没有|别|別|无|無|勿|不(?!过|過))", folded))
    if root == "ko":
        return any(token.casefold() in folded for token in _NEGATIONS[root])

    return any(
        re.search(rf"(?<!\w){re.escape(token.casefold())}(?!\w)", folded)
        for token in _NEGATIONS[root]
    )


def _weak_german_name_shape(name: str) -> bool:
    """Conservative uninflected-name signal for otherwise ambiguous noun slots.

    Bare German plurals such as Kunden/Freunden/Gäste cannot be identified as
    people merely from capitalization and a surrounding verb. Keep uncertain
    inflected forms out of the name guard rather than rejecting valid text.
    """
    lower = name.casefold()
    return len(name) <= 4 or lower.endswith(("a", "i", "o", "y", "ie", "ia", "as", "us", "is"))


def _german_person_names(source: str) -> set[str]:
    """Recognize explicit German personal referents without noun capitalization."""
    plain = _MENTION_RE.sub(" ", _URL_RE.sub(" ", source))
    names = {
        match.group("name")
        for pattern in _DE_PERSON_NAME_PATTERNS
        for match in pattern.finditer(plain)
    }
    names.update(
        match.group("name")
        for pattern in _DE_WEAK_PERSON_NAME_PATTERNS
        for match in pattern.finditer(plain)
        if _weak_german_name_shape(match.group("name"))
    )
    return names


def _latin_name_key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.casefold().replace("ß", "ss"))
    return "".join(char for char in folded if char.isascii() and char.isalpha())


def _phonetic_name_match(name: str, pinyin: str) -> bool:
    """Reject different names; allow only bounded, explicable sound variants."""
    original = _latin_name_key(name)
    candidate = _latin_name_key(pinyin)
    if original == candidate:
        return True
    # Chinese phonetic renderings may use li for German le (Lena/Lina),
    # l for German intervocalic r, and iya for ia. This is a phoneme rule,
    # not a list of accepted names or a general fuzzy-match escape hatch.
    for reading in (candidate, candidate.replace("iya", "ia")):
        if len(original) != len(reading) or len(original) < 4:
            continue
        differences = [
            index for index, (left, right) in enumerate(zip(original, reading))
            if left != right
        ]
        if (
            len(differences) == 1
            and differences[0] < len(original) - 2
            and original[-2:] == reading[-2:]
            and (original[differences[0]], reading[differences[0]]) in {("e", "i"), ("r", "l")}
        ):
            return True
    return False


def _german_person_name_preserved(name: str, translated: str, target_language: Optional[str]) -> bool:
    # URLs and @mentions are not ordinary personal-name mentions.
    plain = _MENTION_RE.sub(" ", _URL_RE.sub(" ", translated))
    if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", plain, flags=re.IGNORECASE):
        return True
    if language_root(target_language) != "zh":
        return False

    # Require both a human-name syntax slot and plausible transliteration
    # characters. Never accept an arbitrary pinyin-homophonous Han substring
    # (按那...) or a Chinese surname identity (李娜 is not 莉娜).
    # This is reject-only validation, not translation or output repair.
    for match in _HAN_RUN_RE.finditer(plain):
        run = match.group()
        for start in range(len(run)):
            prefix = plain[:match.start() + start]
            if not _ZH_NAME_PREFIX_RE.search(prefix):
                continue
            for end in range(start + 2, min(len(run), start + 4) + 1):
                candidate = run[start:end]
                if not all(char in _ZH_TRANSLITERATION_HAN for char in candidate):
                    continue
                # Full candidate boundary, not a valid-name prefix in a longer
                # contiguous Han identity. Ordinary Chinese predicates after
                # the name remain valid even without whitespace.
                suffix = plain[match.start() + end:]
                if not _ZH_NAME_FOLLOW_RE.match(suffix):
                    continue
                # Explicit conservative decision: 丽娜 is not guaranteed to
                # preserve German Lena, even though both read as li-na. Do not
                # generalize sound equivalence into an identity assertion.
                if _latin_name_key(name) == "lena" and candidate == "丽娜":
                    continue
                if _phonetic_name_match(name, "".join(lazy_pinyin(candidate))):
                    return True
    return False


def validate_integrity(
    source: str,
    translated: str,
    *,
    source_language: Optional[str] = None,
    target_language: Optional[str] = None,
) -> list[str]:
    """Reject-only deterministic guard. It never rewrites provider output."""
    failures: list[str] = []
    if not translated.strip():
        return ["empty_output"]

    for label, pattern in (
        ("url", _URL_RE),
        ("mention", _MENTION_RE),
        ("number", _NUMBER_RE),
        ("currency", _CURRENCY_RE),
        ("date", _DATE_RE),
        ("time", _TIME_RE),
        ("emoji", _EMOJI_RE),
    ):
        if _counter(pattern, source) != _counter(pattern, translated):
            failures.append(f"{label}_changed")

    if source.count("\n") != translated.count("\n"):
        failures.append("line_structure_changed")

    # German nouns are title-cased, but person names in clear grammatical
    # contexts still need protection. Never skip DE proper names wholesale.
    if language_root(source_language) == "de":
        for name in _german_person_names(source):
            if not _german_person_name_preserved(name, translated, target_language):
                failures.append("proper_name_changed")
                break
    else:
        source_names = Counter(_LATIN_NAME_RE.findall(source))
        first_source_word = re.match(r"\s*([A-ZÄÖÜ][A-Za-zÀ-ÖØ-öø-ÿÄÖÜäöüß'’-]{2,})\b", source)
        if first_source_word and source_names[first_source_word.group(1)] > 0:
            source_names[first_source_word.group(1)] -= 1
            if source_names[first_source_word.group(1)] <= 0:
                del source_names[first_source_word.group(1)]
        translated_names = Counter(_LATIN_NAME_RE.findall(translated))
        for name, count in source_names.items():
            if translated_names[name] < count:
                failures.append("proper_name_changed")
                break

    if _has_negation(source, source_language) and not _has_negation(translated, target_language):
        failures.append("negation_lost")

    source_len = len(source.strip())
    translated_len = len(translated.strip())
    # Natural Latin -> Chinese translation can be materially shorter in
    # character count without truncating meaning (e.g. Freunden -> 朋友).
    # Retain the truncation fail-closed gate with a bounded script-aware floor.
    min_ratio = 0.20 if language_root(target_language) == "zh" and language_root(source_language) != "zh" else 0.25
    if source_len and (translated_len < max(1, int(source_len * min_ratio)) or translated_len > source_len * 4 + 80):
        failures.append("length_anomaly")

    return failures


def contact_translation_meta(customer) -> dict:
    metadata = dict(customer.meta_data or {})
    value = metadata.get(CONTACT_META_KEY)
    return dict(value) if isinstance(value, dict) else {}


def contact_target_language(customer) -> Optional[str]:
    meta = contact_translation_meta(customer)
    explicit = meta.get("preferredLanguage")
    if explicit and explicit != "auto":
        return public_language_code(explicit)
    return public_language_code(meta.get("observedLanguage"))


def set_contact_language(customer, preferred_language: str) -> dict:
    normalized = "auto" if preferred_language == "auto" else public_language_code(preferred_language)
    if normalized != "auto" and normalize_target_language(normalized) is None:
        raise ValueError("unsupported_target_language")
    metadata = dict(customer.meta_data or {})
    translation = contact_translation_meta(customer)
    translation["preferredLanguage"] = normalized
    translation["updatedAt"] = utc_now_iso()
    metadata[CONTACT_META_KEY] = translation
    customer.meta_data = metadata
    return translation


def set_observed_language(customer, observed_language: Optional[str]) -> None:
    observed = public_language_code(observed_language)
    if not observed:
        return
    metadata = dict(customer.meta_data or {})
    translation = contact_translation_meta(customer)
    translation["observedLanguage"] = observed
    translation["observedAt"] = utc_now_iso()
    metadata[CONTACT_META_KEY] = translation
    customer.meta_data = metadata


def contact_local_daypart(customer) -> Optional[str]:
    meta = dict(customer.meta_data or {})
    translation = contact_translation_meta(customer)
    timezone_name = (
        translation.get("timezone")
        or meta.get("timezone")
        or meta.get("time_zone")
        or meta.get("tz")
    )
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        return None
    try:
        hour = datetime.now(tz=ZoneInfo(timezone_name.strip())).hour
    except Exception:
        return None
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def realism_context(
    customer,
    *,
    direction: str,
    persona_instructions: Optional[Iterable[str]] = None,
) -> str:
    target = contact_target_language(customer) or "unknown"
    daypart = contact_local_daypart(customer) or "unknown"
    persona_parts = [
        str(item).strip()
        for item in (persona_instructions or [])
        if str(item).strip()
    ]
    persona_context = " ".join(persona_parts)[:4000]
    context = (
        f"Private messaging conversation. Direction={direction}. "
        f"Contact language={target}. Contact local daypart={daypart}. "
        "Preserve the source writer's persona, brevity, familiarity, humor, boundaries, "
        "punctuation and human chat rhythm. Do not normalize casual chat into formal prose. "
        "Daypart is context only and must not cause a greeting or new fact to be added."
    )
    if persona_context:
        context += (
            " Active persona guidance (tone/style only; never inject persona facts that are "
            f"absent from the source): {persona_context}"
        )
    return context


def stored_projection(message) -> Optional[dict]:
    attrs = dict(message.attributes or {})
    value = attrs.get(TRANSLATION_ATTR_KEY)
    projection = decrypt_json(value)
    if not isinstance(projection, dict):
        return None
    projection = dict(projection)
    if str(projection.get("messageId")) != str(message.id):
        return {
            "messageId": message.id,
            "status": "stale",
            "errorCode": "MESSAGE_IDENTITY_MISMATCH",
            "sourceSha256": source_sha256(message.message or ""),
        }
    if projection.get("sourceSha256") != source_sha256(message.message or ""):
        return {
            "messageId": message.id,
            "status": "stale",
            "errorCode": "SOURCE_CHANGED",
            "sourceSha256": source_sha256(message.message or ""),
        }
    return projection


def persist_projection(message, projection: dict) -> None:
    attrs = dict(message.attributes or {})
    attrs[TRANSLATION_ATTR_KEY] = encrypt_json(dict(projection))
    message.attributes = attrs


def success_projection(
    message,
    result: ProviderTranslation,
    *,
    target_language: str,
) -> dict:
    return {
        "messageId": message.id,
        "status": "success",
        "text": result.text,
        "sourceLanguage": public_language_code(result.detected_source_language),
        "targetLanguage": public_language_code(target_language),
        "sourceSha256": source_sha256(message.message or ""),
        "provider": "deepl",
        "providerModel": result.model_type,
        "integrity": "passed",
        "stylePolicy": STYLE_POLICY,
        "updatedAt": utc_now_iso(),
    }


def failed_projection(
    message,
    *,
    error_code: str,
    failures: Optional[Iterable[str]] = None,
    source_language: Optional[str] = None,
    target_language: Optional[str] = None,
) -> dict:
    projection = {
        "messageId": message.id,
        "status": "failed",
        "sourceLanguage": public_language_code(source_language),
        "targetLanguage": public_language_code(target_language),
        "sourceSha256": source_sha256(message.message or ""),
        "provider": "deepl",
        "integrity": "failed",
        "stylePolicy": STYLE_POLICY,
        "errorCode": error_code,
        "updatedAt": utc_now_iso(),
    }
    if failures:
        projection["integrityFailures"] = sorted(set(failures))
    return projection


def validate_outbound_pairing(
    sent_text: str,
    pairing: object,
) -> tuple[Optional[dict], list[str]]:
    # Validate an adopted preview again immediately before canonical send.
    if not isinstance(pairing, dict):
        return None, ["pairing_missing"]

    source_text = pairing.get("sourceText")
    translated_text = pairing.get("translatedText")
    source_hash = pairing.get("sourceSha256")
    source_language = public_language_code(pairing.get("sourceLanguage"))
    target_language = public_language_code(pairing.get("targetLanguage"))

    failures: list[str] = []
    if not isinstance(source_text, str) or not source_text.strip() or len(source_text) > 5000:
        failures.append("source_invalid")
    if not isinstance(translated_text, str) or not translated_text.strip() or len(translated_text) > 5000:
        failures.append("translation_invalid")
    if isinstance(source_text, str) and source_sha256(source_text) != source_hash:
        failures.append("source_stale")
    if isinstance(translated_text, str) and translated_text != sent_text:
        failures.append("translation_stale")
    if pairing.get("integrity") != "passed":
        failures.append("preview_not_integrity_passed")
    if not source_language or not target_language:
        failures.append("language_missing")

    if not failures and isinstance(source_text, str):
        failures.extend(
            validate_integrity(
                source_text,
                sent_text,
                source_language=source_language,
                target_language=target_language,
            )
        )

    if failures:
        return None, sorted(set(failures))

    normalized = {
        "direction": "outbound",
        "status": "success",
        "sourceText": source_text,
        "translatedText": sent_text,
        "sourceSha256": source_hash,
        "sourceLanguage": source_language,
        "targetLanguage": target_language,
        "provider": "deepl",
        "providerModel": pairing.get("providerModel"),
        "integrity": "passed",
        "stylePolicy": STYLE_POLICY,
        "humanLikeness": "preserved",
        "updatedAt": utc_now_iso(),
    }
    return normalized, []


def protect_outbound_pairing(pairing: dict) -> dict:
    return encrypt_json(dict(pairing))


def build_deepl_payload(
    text: str,
    *,
    target_language: str,
    source_language: Optional[str] = None,
    context: Optional[str] = None,
    style_id: Optional[str] = None,
    style_language: Optional[str] = None,
) -> dict:
    target = normalize_target_language(target_language)
    if not target:
        raise TranslationProviderError("unsupported_target_language")

    payload: dict = {
        "text": [text],
        "target_lang": target,
        "preserve_formatting": True,
        "formality": "prefer_less",
        "model_type": "prefer_quality_optimized",
    }
    target_root = language_root(target)
    if target_root in _CUSTOM_INSTRUCTION_TARGETS:
        payload["custom_instructions"] = _STYLE_INSTRUCTIONS

    normalized_source = normalize_source_language(source_language)
    if normalized_source:
        payload["source_lang"] = normalized_source
    if context:
        payload["context"] = context[:10000]
    if style_id and style_language_matches(style_language, target):
        payload["style_id"] = style_id
    return payload


class DeepLTranslationOwner:
    owner_name = "deepl.official_translation_api"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        style_id: Optional[str] = None,
        style_language: Optional[str] = None,
    ):
        self.api_key = (api_key if api_key is not None else os.getenv("DEEPL_API_KEY", "")).strip()
        self.style_id = (style_id if style_id is not None else os.getenv("DEEPL_TRANSLATION_STYLE_ID", "")).strip()
        self.style_language = (
            style_language
            if style_language is not None
            else os.getenv("DEEPL_TRANSLATION_STYLE_LANGUAGE", "")
        ).strip()
        # Only the official free endpoint is admitted for this release.
        # A non-Free key must never silently route requests to a paid host.
        self.base_url = "https://api-free.deepl.com"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def free_plan_key_valid(self) -> bool:
        return self.configured and self.api_key.endswith(":fx")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"DeepL-Auth-Key {self.api_key}",
            "Content-Type": "application/json",
        }

    async def health(self) -> dict:
        if not self.configured:
            return {
                "owner": self.owner_name,
                "state": "not_configured",
                "stylePolicy": STYLE_POLICY,
            }
        if not self.free_plan_key_valid:
            return {
                "owner": self.owner_name,
                "state": "needs_attention",
                "stylePolicy": STYLE_POLICY,
                "errorCode": "FREE_PLAN_KEY_REQUIRED",
            }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(f"{self.base_url}/v2/usage", headers=self._headers())
            if response.status_code == 200:
                try:
                    usage = response.json()
                except ValueError:
                    usage = None
                count = usage.get("character_count") if isinstance(usage, dict) else None
                limit = usage.get("character_limit") if isinstance(usage, dict) else None
                # 200 alone does not imply that the free account has capacity.
                if (type(count) is int and type(limit) is int
                        and 0 <= count < limit):
                    return {
                        "owner": self.owner_name,
                        "state": "connected",
                        "stylePolicy": STYLE_POLICY,
                    }
                return {
                    "owner": self.owner_name,
                    "state": "needs_attention",
                    "stylePolicy": STYLE_POLICY,
                    "errorCode": "FREE_QUOTA_EXHAUSTED_OR_UNKNOWN",
                }
            return {
                "owner": self.owner_name,
                "state": "needs_attention",
                "stylePolicy": STYLE_POLICY,
                "errorCode": f"PROVIDER_HTTP_{response.status_code}",
            }
        except httpx.HTTPError:
            return {
                "owner": self.owner_name,
                "state": "needs_attention",
                "stylePolicy": STYLE_POLICY,
                "errorCode": "PROVIDER_UNREACHABLE",
            }

    async def translate(
        self,
        text: str,
        *,
        target_language: str,
        source_language: Optional[str] = None,
        context: Optional[str] = None,
    ) -> ProviderTranslation:
        if not self.configured:
            raise TranslationProviderError("translation_owner_not_configured")
        if not self.free_plan_key_valid:
            raise TranslationProviderError("translation_free_plan_key_required")
        payload = build_deepl_payload(
            text,
            target_language=target_language,
            source_language=source_language,
            context=context,
            style_id=self.style_id,
            style_language=self.style_language,
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.base_url}/v2/translate",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise TranslationProviderError("translation_provider_unreachable") from exc

        if response.status_code != 200:
            raise TranslationProviderError(f"translation_provider_http_{response.status_code}")
        try:
            data = response.json()
            item = data["translations"][0]
            translated = str(item["text"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise TranslationProviderError("translation_provider_invalid_response") from exc
        return ProviderTranslation(
            text=translated,
            detected_source_language=item.get("detected_source_language"),
            model_type=item.get("model_type_used"),
        )


def get_translation_owner() -> DeepLTranslationOwner:
    return DeepLTranslationOwner()
