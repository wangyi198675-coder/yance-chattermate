from types import SimpleNamespace

from app.services.translation import (
    DeepLTranslationOwner,
    ProviderTranslation,
    build_deepl_payload,
    contact_target_language,
    failed_projection,
    infer_source_language,
    normalize_source_language,
    normalize_target_language,
    persist_projection,
    set_contact_language,
    set_observed_language,
    source_sha256,
    stored_projection,
    success_projection,
    validate_integrity,
    validate_outbound_pairing,
)


def _customer(meta=None):
    return SimpleNamespace(meta_data=meta or {})


def _message(text="Nicht 12 € an @Lena senden 🙂\nOkay?", message_id=42):
    return SimpleNamespace(id=message_id, message=text, attributes={})


def test_target_and_source_language_normalization_are_provider_safe():
    assert normalize_target_language("de") == "DE"
    assert normalize_target_language("zh-CN") == "ZH-HANS"
    assert normalize_target_language("en_gb") == "EN-GB"
    assert normalize_source_language("en-US") == "EN"
    assert normalize_source_language("zh-Hant") == "ZH"
    assert normalize_target_language("xx") is None


def test_contact_preference_uses_existing_customer_metadata_only():
    customer = _customer({"timezone": "Europe/Berlin", "keep": "me"})
    meta = set_contact_language(customer, "de")
    assert meta["preferredLanguage"] == "de"
    assert contact_target_language(customer) == "de"
    assert customer.meta_data["keep"] == "me"
    set_contact_language(customer, "auto")
    set_observed_language(customer, "it")
    assert contact_target_language(customer) == "it"


def test_deterministic_source_inference_only_claims_strong_scripts():
    assert infer_source_language("你好，今天怎么样？") == "zh"
    assert infer_source_language("안녕하세요") == "ko"
    assert infer_source_language("Hallo Berlin") is None


def test_integrity_guard_rejects_protected_content_loss_without_repair():
    source = "Nicht 12 € an @Lena senden 🙂\nhttps://example.com/a"
    translated = "不要发送给 Lena\nhttps://example.com/a"
    failures = validate_integrity(source, translated, source_language="de", target_language="zh")
    assert "mention_changed" in failures
    assert "number_changed" in failures
    assert "currency_changed" in failures
    assert "emoji_changed" in failures


def test_integrity_guard_accepts_protected_content_and_negation():
    source = "Nicht 12 € an @Lena senden 🙂\nhttps://example.com/a"
    translated = "不要把 12 € 发给 @Lena 🙂\nhttps://example.com/a"
    assert validate_integrity(source, translated, source_language="de", target_language="zh") == []


def test_integrity_guard_does_not_treat_german_common_nouns_as_names():
    source = "Ich war heute länger im Atelier, aber jetzt bin ich endlich zuhause 🙂"
    translated = "今天我在工作室待得比较久，但现在终于到家了 🙂"
    assert validate_integrity(source, translated, source_language="de", target_language="zh") == []


def test_integrity_negation_detection_is_token_aware_and_chat_typography_safe():
    source = "I was going to answer earlier, but work stole the whole afternoon 🙂"
    translated = "我本来打算早点回复的，但工作占用了整个下午 🙂"
    assert validate_integrity(source, translated, source_language="en", target_language="zh") == []

    source = "我刚从工作室回来，今天有点忙，不过现在终于可以放松一下了 🙂"
    translated = "Ich bin gerade aus dem Studio zurückgekommen, hatte heute ziemlich viel zu tun, aber jetzt kann ich mich endlich mal entspannen 🙂"
    assert validate_integrity(source, translated, source_language="zh", target_language="de") == []

    source = "你一上来就叫我宝贝，会不会有点太快了 🙂"
    translated = "You called me “baby” right off the bat—isn’t that a bit too soon? 🙂"
    assert validate_integrity(source, translated, source_language="zh", target_language="en") == []


def test_live_deepl_protected_content_change_is_rejected_fail_closed():
    source = "Nicht 12 € an @Lena senden 🙂\nhttps://example.com/a"
    translated = "请勿向 @Lena 发送 12 欧元 🙂 https://example.com/a"
    failures = validate_integrity(source, translated, source_language="de", target_language="zh")
    assert set(failures) == {"currency_changed", "line_structure_changed"}


def test_window227_exact_window219_review_failure_is_rejected():
    # Window219's independently observed defect: dropping Lena and replacing
    # the named person with only a pronoun must never pass.
    source = "Heute habe ich Lena im Cafe gesehen."
    deleted = "今天我在咖啡馆见到了她。"
    modified = "今天我在咖啡馆见到了莉莎。"
    transliterated = "今天我在咖啡馆见到了莉娜。"
    assert "proper_name_changed" in validate_integrity(
        source, deleted, source_language="de", target_language="zh"
    )
    assert "proper_name_changed" in validate_integrity(
        source, modified, source_language="de", target_language="zh"
    )
    assert validate_integrity(
        source, transliterated, source_language="de", target_language="zh"
    ) == []


def test_window227_german_person_name_deleted_is_rejected():
    source = "Ich habe gestern mit Anna gesprochen 🙂"
    translated = "我昨天聊过了 🙂"
    assert "proper_name_changed" in validate_integrity(
        source, translated, source_language="de", target_language="zh"
    )


def test_window227_german_person_name_materially_changed_is_rejected():
    source = "Ich habe gestern mit Anna gesprochen 🙂"
    for translation, target in (
        ("我昨天和玛丽聊过了 🙂", "zh"),
        ("I spoke with Maria yesterday 🙂", "en"),
        ("I spoke with JoAnna yesterday 🙂", "en"),
        ("我昨天和安妮聊过了 🙂", "zh"),
        ("我昨天和汉娜聊过了 🙂", "zh"),
    ):
        assert "proper_name_changed" in validate_integrity(
            source, translation, source_language="de", target_language=target
        )


def test_window227_german_name_preserved_and_zh_transliterated_are_valid():
    source = "Ich habe gestern mit Anna gesprochen 🙂"
    for translation in ("我昨天和 Anna 聊过了 🙂", "我昨天和安娜聊过了 🙂"):
        assert validate_integrity(
            source, translation, source_language="de", target_language="zh"
        ) == []
    assert validate_integrity(
        "Ich habe mit Lena telefoniert 🙂",
        "我和莉娜通了电话 🙂",
        source_language="de",
        target_language="zh",
    ) == []


def test_window227_name_in_relationship_and_subject_roles_is_protected():
    assert "proper_name_changed" in validate_integrity(
        "Meine Freundin Lena kommt später 🙂",
        "我的朋友稍后会来 🙂",
        source_language="de", target_language="zh",
    )
    assert "proper_name_changed" in validate_integrity(
        "Anna schreibt heute 🙂",
        "她今天写信 🙂",
        source_language="de", target_language="zh",
    )


def test_window227_german_capitalized_common_nouns_still_pass_live_replay():
    source = "Ich war heute länger im Atelier, aber jetzt bin ich endlich zuhause 🙂"
    translated = "今天我在工作室待得比较久，但现在终于到家了 🙂"
    assert validate_integrity(source, translated, source_language="de", target_language="zh") == []


def test_window227_german_person_name_not_satisfied_by_url_or_mention():
    source = "Ich habe mit Anna gesprochen: @Lena 12 € 2026-10-09 18:30 https://example.com/Anna 🙂\\nBis bald"
    valid = "我和安娜聊过：@Lena 12 € 2026-10-09 18:30 https://example.com/Anna 🙂\\n再见"
    lost = "我聊过：@Lena 12 € 2026-10-09 18:30 https://example.com/Anna 🙂\\n再见"
    assert validate_integrity(source, valid, source_language="de", target_language="zh") == []
    assert validate_integrity(source, lost, source_language="de", target_language="zh") == [
        "proper_name_changed"
    ]


def test_window227_real_negation_loss_still_rejects():
    assert "negation_lost" in validate_integrity(
        "Bitte nicht senden 🙂", "请发送 🙂",
        source_language="de", target_language="zh",
    )
    assert "negation_lost" in validate_integrity(
        "Do not send it 🙂", "发送吧 🙂",
        source_language="en", target_language="zh",
    )
    assert "negation_lost" in validate_integrity(
        "我没有告诉她 🙂", "Ich habe es ihr gesagt 🙂",
        source_language="zh", target_language="de",
    )


def test_projection_is_exact_message_identity_and_source_revision_bound():
    message = _message()
    result = ProviderTranslation(
        text="不要把 12 € 发给 @Lena 🙂\nOkay?",
        detected_source_language="DE",
        model_type="quality_optimized",
    )
    projection = success_projection(message, result, target_language="ZH-HANS")
    persist_projection(message, projection)
    assert "__enc__" in message.attributes["yance_translation"]
    assert stored_projection(message)["status"] == "success"
    assert stored_projection(message)["messageId"] == 42

    message.message = "Changed source"
    stale = stored_projection(message)
    assert stale["status"] == "stale"
    assert stale["errorCode"] == "SOURCE_CHANGED"
    assert "text" not in stale


def test_failed_projection_never_contains_translated_text():
    message = _message()
    projection = failed_projection(
        message,
        error_code="TRANSLATION_OUTPUT_INVALID",
        failures=["negation_lost"],
        source_language="de",
        target_language="zh",
    )
    assert projection["status"] == "failed"
    assert projection["sourceSha256"] == source_sha256(message.message)
    assert "text" not in projection


def test_owner_is_fail_closed_when_not_configured():
    owner = DeepLTranslationOwner(api_key="")
    assert owner.configured is False


def test_deepl_payload_applies_chat_style_controls_only_where_supported():
    german = build_deepl_payload(
        "Hi",
        target_language="de",
        source_language="en",
        context="private chat",
        style_id="style-1",
        style_language="de",
    )
    assert german["custom_instructions"]
    assert german["style_id"] == "style-1"
    assert german["formality"] == "prefer_less"
    assert german["preserve_formatting"] is True

    romanian = build_deepl_payload(
        "Hi",
        target_language="ro",
        source_language="en",
        context="private chat",
        style_id="style-1",
        style_language="de",
    )
    assert "custom_instructions" not in romanian
    assert "style_id" not in romanian
    assert romanian["context"] == "private chat"

    en_gb = build_deepl_payload(
        "Hi",
        target_language="en-gb",
        source_language="de",
        style_id="gb-style",
        style_language="en-GB",
    )
    en_us = build_deepl_payload(
        "Hi",
        target_language="en-us",
        source_language="de",
        style_id="gb-style",
        style_language="en-GB",
    )
    assert en_gb["style_id"] == "gb-style"
    assert "style_id" not in en_us


def test_outbound_pairing_revalidates_source_hash_sent_text_and_integrity():
    source = "今天晚一点聊 🙂"
    translated = "Wir schreiben später 🙂"
    pairing = {
        "sourceText": source,
        "translatedText": translated,
        "sourceSha256": source_sha256(source),
        "sourceLanguage": "zh",
        "targetLanguage": "de",
        "integrity": "passed",
        "providerModel": "quality_optimized",
    }
    normalized, failures = validate_outbound_pairing(translated, pairing)
    assert failures == []
    assert normalized["direction"] == "outbound"
    assert normalized["humanLikeness"] == "preserved"

    stale, failures = validate_outbound_pairing(translated + "!", pairing)
    assert stale is None
    assert "translation_stale" in failures


# Window248: durable reproductions of the Window245 READ-ONLY red-team.
# The assertions intentionally distinguish proper-name fail closed from
# unrelated guards (e.g. negation/length); a different error is not a PASS.
import pytest
from app.services.translation import _german_person_names


@pytest.mark.parametrize(("source", "translated", "expected_names", "expected_failure"), [
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了她。", {"Lena"}, "proper_name_changed"),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了莉娜。", {"Lena"}, None),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了莉莎。", {"Lena"}, "proper_name_changed"),
    ("Ich habe mit Kunden gesprochen.", "我和客户谈过。", set(), None),
    ("Ich habe mit Freunden gesprochen.", "我和朋友聊过。", set(), None),
    ("Heute habe ich Gäste im Cafe gesehen.", "今天我在咖啡馆见到了客人。", set(), None),
    ("Ich habe mit Anna gesprochen.", "我按那个按钮说话。", {"Anna"}, "proper_name_changed"),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了李娜。", {"Lena"}, "proper_name_changed"),
    ("Gestern traf ich Lena im Cafe.", "昨天我在咖啡馆见到了她。", {"Lena"}, "proper_name_changed"),
    ("Ich werde Lena morgen treffen.", "我明天会见她。", {"Lena"}, "proper_name_changed"),
    ("Meine Schwester Anna kommt später.", "我姐姐晚点来。", {"Anna"}, "proper_name_changed"),
    ("Anna schreibt heute.", "她今天写信。", {"Anna"}, "proper_name_changed"),
    ("Bitte nicht senden.", "请发送。", set(), "negation_lost"),
    ("Ich war heute länger im Atelier, aber jetzt bin ich endlich zuhause 🙂",
     "今天我在工作室待得比较久，但现在终于到家了 🙂", set(), None),
    ("Ich habe mit Anna gesprochen: https://example.com/Anna",
     "我聊过：https://example.com/Anna", {"Anna"}, "proper_name_changed"),
    ("Ich habe mit Anna gesprochen: @Anna", "我聊过：@Anna", {"Anna"}, "proper_name_changed"),
])
def test_window248_window245_all_16_redteam_cases(
    source, translated, expected_names, expected_failure
):
    assert _german_person_names(source) == expected_names
    failures = validate_integrity(source, translated, source_language="de", target_language="zh")
    if expected_failure is None:
        assert failures == []
    else:
        assert expected_failure in failures


@pytest.mark.parametrize(("source", "target", "named"), [
    ("Ich habe gestern mit Nachbarn gesprochen.", "我昨天和邻居聊过了。", False),
    ("Ich habe mit Kolleginnen telefoniert.", "我和同事打了电话。", False),
    ("Gestern sah ich Gäste im Cafe.", "昨天我在咖啡馆见到了客人。", False),
    ("Heute habe ich Besucher im Atelier gesehen.", "今天我在工作室见到了访客。", False),
    ("Gestern sah ich Anna im Cafe.", "昨天我在咖啡馆见到了她。", True),
    ("Gestern traf ich Lena im Cafe.", "昨天我在咖啡馆见到了她。", True),
    ("Ich werde Anna morgen treffen.", "我明天会见她。", True),
    ("Meine Mutter Lena kommt später.", "我妈妈稍后就到。", True),
    ("Mein Bruder Ben hat geschrieben.", "我的兄弟发来消息。", True),
])
def test_window248_nearby_german_person_and_noun_grammar(source, target, named):
    names = _german_person_names(source)
    assert bool(names) == named
    failures = validate_integrity(source, target, source_language="de", target_language="zh")
    assert ("proper_name_changed" in failures) == named


@pytest.mark.parametrize(("translated", "preserved"), [
    ("我昨天和安娜聊过了。", True),
    ("我今天见到了莉娜。", False),  # checked against Anna below
    ("我按那个按钮说话。", False),
    ("我今天按那个按钮说话。", False),
    ("安娜今天写信了。", True),
    ("我今天看到了安娜。", True),
    ("我今天看到了李娜。", False),
    ("我今天看到了按那。", False),
    ("我今天看到了安妮。", False),
])
def test_window248_anna_han_context_not_arbitrary_pinyin(translated, preserved):
    failures = validate_integrity(
        "Ich habe mit Anna gesprochen.",
        translated, source_language="de", target_language="zh",
    )
    assert ("proper_name_changed" not in failures) == preserved


@pytest.mark.parametrize(("translated", "preserved"), [
    ("我和莉娜通了电话。", True),
    ("我今天见到了莉娜。", True),
    ("我今天见到了李娜。", False),
    ("我今天见到了黎娜。", False),
    ("我今天见到了莉莎。", False),
    ("我昨天按那个按钮后见到了她。", False),
    ("我和她聊天时提到了按那。", False),
    ("我今天见到了她，网址是 https://example.org/Lena", False),
    ("我和 @Lena 交流后才见到她。", False),
])
def test_window248_lena_transliteration_identity_not_homophone(translated, preserved):
    source = "Ich habe mit Lena telefoniert."
    # URL/@mention adversaries are separately protected as literal transport.
    failures = validate_integrity(source, translated, source_language="de", target_language="zh")
    assert ("proper_name_changed" not in failures) == preserved


def test_window248_short_chinese_noun_translation_keeps_truncation_gate():
    assert validate_integrity(
        "Ich habe mit Freunden gesprochen.", "我和朋友聊过。",
        source_language="de", target_language="zh",
    ) == []
    assert "length_anomaly" in validate_integrity(
        "Ich habe mit Freunden gesprochen und danach gestern sehr lange zusammen im Cafe gegessen.",
        "好。", source_language="de", target_language="zh",
    )



# Window265: permanent regressions for W252 Han-run false acceptance.
# No whitespace is expected between a Chinese person's name and predicate;
# that does not permit an unbounded prefix of a different, longer name.
@pytest.mark.parametrize(("source", "target", "preserved"), [
    ("Ich habe mit Anna gesprochen.", "我和安娜聊过了。", True),
    ("Ich habe mit Anna gesprochen.", "安娜今天写信了。", True),
    ("Ich habe mit Anna gesprochen.", "我见到了安娜。", True),
    ("Ich habe mit Anna gesprochen.", "我和安娜莉莎聊过了。", False),
    ("Ich habe mit Anna gesprochen.", "我和安娜丽莎聊过了。", False),
    ("Ich habe mit Anna gesprochen.", "我和安娜莉聊过了。", False),
    ("Ich habe mit Anna gesprochen.", "我和安娜安聊过了。", False),
    ("Ich habe mit Anna gesprochen.", "我和安娜妮聊过了。", False),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了莉娜。", True),
    ("Ich habe mit Lena telefoniert.", "我和莉娜通了电话。", True),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了莉娜安。", False),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了莉娜丽。", False),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了莉娜玛丽。", False),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了丽娜。", False),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了李娜。", False),
    ("Heute habe ich Lena im Cafe gesehen.", "今天我在咖啡馆见到了莉莎。", False),
])
def test_window265_complete_han_name_boundary(source, target, preserved):
    failures = validate_integrity(source, target, source_language="de", target_language="zh")
    assert ("proper_name_changed" not in failures) == preserved


@pytest.mark.parametrize(("source", "target"), [
    ("Ich habe mit Kunden gesprochen.", "我和客户谈过。"),
    ("Ich habe mit Freunden gesprochen.", "我和朋友聊过。"),
    ("Heute habe ich Gäste im Cafe gesehen.", "今天我在咖啡馆见到了客人。"),
])
def test_window265_common_nouns_remain_outside_person_name_guard(source, target):
    assert _german_person_names(source) == set()
    assert validate_integrity(
        source, target, source_language="de", target_language="zh",
    ) == []
