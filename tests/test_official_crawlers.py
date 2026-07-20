"""Offline parsing and source-format tests for active official announcements."""

from __future__ import annotations

from datetime import datetime

from announcement.models import Announcement, CN_OFFICIAL, TW_OFFICIAL
from bot.main import announcement_embed_batches
from crawler import cn_official_crawler, tw_official_crawler
from crawler.website_crawler import WebsiteAnnouncement, WebsiteCrawlResult


CN_LIST = """
<ul id="newsList" class="news-list"><li><p class="info"><span>2026-07-20</span></p>
<a class="title" href="/webplat/info/news/202607/988690.shtml">【公告】最新消息</a></li></ul>
"""
CN_DETAIL = """
<div class="content"><div class="hd"><p class="info"><span>运营团队</span><span>2026-07-20 11:20:12</span></p></div>
<div class="context"><p>正文</p><img src="//images.example/one.png"><img src="https://images.example/two.png"></div></div>
"""


def test_cn_list_and_detail_parsers_preserve_official_fields_and_image_order() -> None:
    item = cn_official_crawler.parse_list(CN_LIST, "https://qjnn.qq.com/list_1.shtml")[0]
    html, text, images, published_at = cn_official_crawler.parse_detail(CN_DETAIL, item.url)

    assert item.external_id == "988690"
    assert item.category == "公告"
    assert text == "正文"
    assert "context" in html
    assert images == ["https://images.example/one.png", "https://images.example/two.png"]
    assert published_at == datetime(2026, 7, 20, 11, 20, 12, tzinfo=cn_official_crawler.CHINA_TIMEZONE)


def test_cn_detail_text_preserves_inline_dates_and_punctuation_without_losing_paragraphs() -> None:
    document = """
    <div class="content"><div class="context">
      <p><span>7</span><span>月<span>22</span>日更新后</span><span>，领取套装【<strong>慕冬天使</strong>】。</span></p>
      <p>第一行<br><font>第二行</font></p>
      <p>下一段</p>
    </div></div>
    """

    _html, text, _images, _published_at = cn_official_crawler.parse_detail(
        document, "https://qjnn.qq.com/notice/1.shtml"
    )

    assert "7月22日更新后，领取套装【慕冬天使】。" in text
    assert "7\n月\n22" not in text
    assert "【\n慕冬天使\n】" not in text
    assert text == "7月22日更新后，领取套装【慕冬天使】。\n第一行\n第二行\n下一段"


def test_cn_detail_excludes_explicit_official_account_qr_footer_but_preserves_ordered_body_images() -> None:
    document = """
    <div class="content"><div class="context">
      <p><img src="/images/event-one.png"></p>
      <p><img src="/images/event-two.png"></p>
      <p><img src="/images/event-one.png"></p>
      <p>关注《奇迹暖暖》微信公众号（nikkiup2u3），微信扫描下方二维码：</p>
      <p><img id="图片 17" alt="游戏圈子_奇迹暖暖_220x220" src="/assets/image001.gif"></p>
    </div></div>
    """

    _html, _text, images, _published_at = cn_official_crawler.parse_detail(
        document, "https://qjnn.qq.com/notice/1.shtml"
    )

    assert images == [
        "https://qjnn.qq.com/images/event-one.png",
        "https://qjnn.qq.com/images/event-two.png",
    ]

    announcement = Announcement(
        source=CN_OFFICIAL,
        external_id="1",
        url="https://qjnn.qq.com/notice/1.shtml",
        title="公告",
        category=None,
        published_at=None,
        content_html=None,
        content_text="正文",
        images=tuple(images),
    )
    payload = announcement.payload()
    embeds = [embed for batch in announcement_embed_batches(payload) for embed in batch]
    assert payload["image_urls"] == images
    assert all("image001.gif" not in str(embed.image.url) for embed in embeds)


def test_cn_detail_does_not_drop_a_last_body_image_without_qr_markers() -> None:
    document = """
    <div class="content"><div class="context">
      <p><img src="/images/first.png"></p>
      <p>活动说明</p>
      <p><img src="/images/final-activity.png"></p>
    </div></div>
    """

    _html, _text, images, _published_at = cn_official_crawler.parse_detail(
        document, "https://qjnn.qq.com/notice/1.shtml"
    )

    assert images == [
        "https://qjnn.qq.com/images/first.png",
        "https://qjnn.qq.com/images/final-activity.png",
    ]


def test_tw_adapter_maps_existing_nextjs_parser_to_common_announcement(monkeypatch) -> None:
    source = WebsiteAnnouncement(
        source_post_id="17322", url="https://nu3.fearlessgames.net/news/17322", title="台服公告",
        section=1, section_name="活動", publish_time="2026-07-14T04:00:00+00:00",
        content_text="正文", content_html="<p>正文</p>", image_urls=["https://images.example/tw.png"],
    )
    monkeypatch.setattr(
        tw_official_crawler,
        "crawl_recent_announcements",
        lambda _limit: WebsiteCrawlResult([source], [], 1),
    )

    announcement = tw_official_crawler.fetch_recent_announcements(1)[0]

    assert announcement.source == TW_OFFICIAL
    assert announcement.external_id == "17322"
    assert announcement.title == "台服公告"
    assert announcement.category == "活動"
    assert announcement.content_html == "<p>正文</p>"
    assert announcement.content_text == "正文"
    assert announcement.images == ("https://images.example/tw.png",)


def test_official_sources_share_the_same_announcement_contract() -> None:
    cn = cn_official_crawler.parse_list(CN_LIST, "https://qjnn.qq.com/list_1.shtml")[0]
    assert cn.external_id
    assert cn.url
    assert TW_OFFICIAL != CN_OFFICIAL
