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
