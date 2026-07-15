from parser.announcement_parser import classify_content, is_valid_suit_name, parse_announcement


def test_rerun_title_period_and_suits():
    draft = parse_announcement(
        "\u3010\u5fa9\u523b\u3011\u5947\u8ff9\u6f14\u5531\u6703 \u9650\u6642\u5fa9\u958b\n"
        "\u6d3b\u52d5\u6642\u9593\uff1a2026\u5e747\u670813\u65e505:00 \u2013 2026\u5e747\u670819\u65e523:59\n"
        "\u53ef\u7372\u5f97\u3010\u9ad4\u529b\u3001\u91d1\u5e63\u3001\u947d\u77f3\u3011\u3001\u3010\u5143\u6c23\u61c9\u63f4\u3011\u3001\u3010\u7d55\u5c0d\u6416\u6efe\u3011\u5957\u88dd"
    )

    assert draft.event_name_candidate == "\u5947\u8ff9\u6f14\u5531\u6703"
    assert draft.period_type_candidate == "rerun"
    assert draft.start_at_candidate == "2026-07-13T05:00:00+08:00"
    assert [suit.name for suit in draft.suits] == ["\u5143\u6c23\u61c9\u63f4", "\u7d55\u5c0d\u6416\u6efe"]


def test_debut_and_slash_period():
    draft = parse_announcement(
        "\u3010\u5168\u65b0\u3011\u661f\u5149\u7bc0\n2026/07/13 05:00 - 2026/07/19 23:59"
    )

    assert draft.period_type_candidate == "debut"
    assert draft.start_at_candidate == "2026-07-13T05:00:00+08:00"
    assert draft.end_at_candidate == "2026-07-19T23:59:00+08:00"


def test_missing_period_creates_notes_without_guessing_categories():
    draft = parse_announcement("\u3010\u9810\u544a\u3011\u6e2c\u8a66\u6d3b\u52d5")

    assert draft.start_at_candidate is None
    assert draft.end_at_candidate is None
    assert draft.player_category_candidate is None
    assert draft.acquisition_method_candidate is None
    assert draft.parser_notes is not None


def test_wallpaper_is_not_classified_as_an_event():
    draft = parse_announcement("六月桌布套組釋出\n請至官方社群下載桌布")

    assert draft.content_type_candidate == "wallpaper"


def test_single_title_emoji_classifies_an_otherwise_unclassified_announcement():
    assert classify_content("\U0001f381 \u6bcf\u65e5\u79ae\u7269", "\u9818\u53d6\u672c\u9031\u793c\u7269", False) == "welfare"


def test_multiple_title_emojis_use_the_established_emoji_priority():
    assert classify_content("\U0001f381 \U0001f5bc \u66f4\u65b0\u901a\u77e5", "\u8cc7\u8a0a\u6574\u7406", False) == "wallpaper"


def test_no_emoji_keeps_existing_other_classification():
    assert classify_content("\u65e5\u5e38\u5206\u4eab", "\u4eca\u5929\u5929\u6c23\u6674\u6717", False) == "other"


def test_keyword_classification_wins_when_title_emoji_agrees_or_conflicts():
    assert classify_content("\U0001f5bc \u684c\u5e03\u66f4\u65b0", "\u684c\u5e03\u5957\u7d44\u91cb\u51fa", False) == "wallpaper"
    assert classify_content("\U0001f527 \u6d3b\u52d5\u9810\u544a", "\u6d3b\u52d5\u6642\u9593\uff1a2026/07/13", False) == "event"


def test_suit_parser_rejects_resources_ui_labels_and_clothing_parts():
    invalid = ["5", "一鍵製衣", "下裝·紅莓漫歌", "體力", "星光幣", "套裝部件"]

    assert all(not is_valid_suit_name(name) for name in invalid)
    assert is_valid_suit_name("元氣應援")


def test_suit_parser_only_keeps_explicit_acquisition_candidates():
    draft = parse_announcement(
        "活動時間：2026/07/13 05:00 - 2026/07/19 23:59\n"
        "【5】、【一鍵製衣】、【下裝·紅莓漫歌】、【體力】、【星光幣】、【套裝部件】\n"
        "可獲得【元氣應援】套裝"
    )

    assert [suit.name for suit in draft.suits] == ["元氣應援"]


def test_suit_event_without_high_confidence_suits_is_flagged_for_follow_up():
    draft = parse_announcement(
        "限時活動\n活動時間：2026/07/13 05:00 - 2026/07/19 23:59\n"
        "可獲得【下裝·紅莓漫歌】套裝"
    )

    assert draft.content_type_candidate == "suit_event"
    assert draft.suits == []


def test_suit_parser_accepts_explicit_official_suit_formats_at_high_confidence():
    draft = parse_announcement(
        "\u5957\u88dd\u3010\u6d77\u6c99\u66a2\u60f3\u3011\n"
        "\u6545\u4e8b\u5957\u88dd\u3010\u5e78\u798f\u9810\u5146\u3011\n"
        "\u5168\u65b0\u5957\u88dd\u3010\u661f\u591c\u5e7b\u5922\u3011\n"
        "\u7cbe\u7dfb\u5957\u88dd\u3010\u7434\u97f3\u5348\u5f8c\u3011\n"
        "\u5fa9\u523b\u5957\u88dd\u3010\u7562\u6708\u70cf\u3011\n"
        "\u6210\u5c31\u5957\u88dd\u3010\u7d05\u8393\u6f2b\u6b4c\u3011\n"
        "\u6536\u96c6\u5957\u88dd\u3010\u51b0\u8207\u528d\u4e4b\u8a93\u3011\n"
        "\u7cbe\u7dfb\u7bc0\u65e5\u5957\u88dd\u3010\u528d\u98f2\u6625\u79cb\u3011\n"
        "\u3010\u96f6\u798f\u9810\u5146\u3011\u5957\u88dd\n"
        "\u5957\u88dd\u70ba\u3010\u6668\u66e6\u82b1\u5f71\u3011"
    )

    assert [suit.name for suit in draft.suits] == [
        "\u6d77\u6c99\u66a2\u60f3",
        "\u5e78\u798f\u9810\u5146",
        "\u661f\u591c\u5e7b\u5922",
        "\u7434\u97f3\u5348\u5f8c",
        "\u7562\u6708\u70cf",
        "\u7d05\u8393\u6f2b\u6b4c",
        "\u51b0\u8207\u528d\u4e4b\u8a93",
        "\u528d\u98f2\u6625\u79cb",
        "\u96f6\u798f\u9810\u5146",
        "\u6668\u66e6\u82b1\u5f71",
    ]
    assert all(suit.confidence == 1.0 for suit in draft.suits)


def test_suit_parser_rejects_resources_without_an_explicit_suit_context():
    draft = parse_announcement(
        "\u53ef\u7372\u5f97\u3010\u661f\u66dc\u77f3\u3011\u3002\u9084\u53ef\u7372\u5f97\u7cbe\u7dfb\u5957\u88dd\u3010\u5143\u6c23\u61c9\u63f4\u3011\u3002\n"
        "\u7372\u5f97\u3010\u5fc3\u57df\u8993\u5f71\u5238\u3011\n"
        "\u7372\u5f97\u3010\u87a2\u5149\u68d2\u3011\n"
        "\u7372\u5f97\u3010\u51b0\u4e4b\u9b44*350\u3011\n"
        "\u7372\u5f97\u3010\u7cbe\u5bc6\u9f52\u8f2a\u3011"
    )

    assert [suit.name for suit in draft.suits] == ["\u5143\u6c23\u61c9\u63f4"]
    assert draft.suits[0].confidence == 1.0
    assert not is_valid_suit_name("\u661f\u66dc\u77f3")
    assert not is_valid_suit_name("\u51b0\u4e4b\u9b44*350")


def test_suit_parser_keeps_multi_suit_acquisition_list_in_the_same_sentence():
    draft = parse_announcement(
        "\u9084\u53ef\u8d0f\u5f97\u3010\u5143\u6c23\u61c9\u63f4\u3011\u3001\u3010\u7d55\u5c0d\u6416\u6efe\u3011\u7cbe\u7dfb\u6f14\u5531\u6703\u4e3b\u984c\u5957\u88dd\u3002"
    )

    assert [suit.name for suit in draft.suits] == ["\u5143\u6c23\u61c9\u63f4", "\u7d55\u5c0d\u6416\u6efe"]
    assert all(suit.confidence == 0.9 for suit in draft.suits)


def test_suit_parser_keeps_an_explicit_rerun_suit_list_at_high_confidence():
    draft = parse_announcement(
        "\u5fa9\u523b\u5957\u88dd\u3010\u7562\u6708\u70cf\u3011\u3001\u3010\u89d2\u6728\u86df\u3011\u3001\u3010\u623f\u65e5\u5154\u3011"
    )

    assert [suit.name for suit in draft.suits] == ["\u7562\u6708\u70cf", "\u89d2\u6728\u86df", "\u623f\u65e5\u5154"]
    assert all(suit.confidence == 1.0 for suit in draft.suits)


def test_suit_parser_rejects_bracketed_reward_enumerations_with_suit_parts():
    draft = parse_announcement(
        "\u7372\u5f97\u3010\u947d\u77f3\u3001\u9ad4\u529b\u3001\u91d1\u5e63\u3001\u9650\u5b9a\u5957\u88dd\u90e8\u4ef6\u3001\u8d85\u7a00\u6709\u9650\u5b9a\u90e8\u4ef6\u3011\u3002\n"
        "\u7372\u5f97\u3010\u947d\u77f3\u3001\u91d1\u5e63\u3011\u3002\n"
        "\u7372\u5f97\u3010\u9650\u5b9a\u5957\u88dd\u90e8\u4ef6\u3011\u3002\n"
        "\u53ef\u7372\u5f97\u5957\u88dd\u3010\u6696\u5fc3\u871c\u610f\u3011\u3002"
    )

    assert [suit.name for suit in draft.suits] == ["\u6696\u5fc3\u871c\u610f"]
    assert not is_valid_suit_name(
        "\u947d\u77f3\u3001\u9ad4\u529b\u3001\u91d1\u5e63\u3001\u9650\u5b9a\u5957\u88dd\u90e8\u4ef6\u3001\u8d85\u7a00\u6709\u9650\u5b9a\u90e8\u4ef6"
    )
    assert not is_valid_suit_name("\u947d\u77f3\u3001\u91d1\u5e63")
    assert not is_valid_suit_name("\u9650\u5b9a\u5957\u88dd\u90e8\u4ef6")


def test_suit_parser_keeps_high_confidence_suit_lists_while_rejecting_reward_lists():
    draft = parse_announcement(
        "\u5fa9\u523b\u5957\u88dd\u3010\u7562\u6708\u70cf\u3011\u3001\u3010\u89d2\u6728\u86df\u3011\u3002\n"
        "\u5957\u88dd\u3010\u6696\u5fc3\u871c\u610f\u3011\u3002\n"
        "\u6210\u5c31\u5957\u88dd\u3010\u6d77\u6c99\u66a2\u60f3\u3011\u3002"
    )

    assert [suit.name for suit in draft.suits] == ["\u7562\u6708\u70cf", "\u89d2\u6728\u86df", "\u6696\u5fc3\u871c\u610f", "\u6d77\u6c99\u66a2\u60f3"]
    assert all(suit.confidence == 1.0 for suit in draft.suits)


def test_source_neutral_content_type_hint_has_priority_over_text_classification():
    draft = parse_announcement(
        "【活動】測試公告\n活動時間：2026年7月16日05:00 - 2026年7月25日23:59",
        content_type_hint="system",
    )

    assert draft.content_type_candidate == "system"
