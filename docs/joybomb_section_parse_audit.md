# JoyBomb Section Parse Quality Audit

> Audit date: 2026-07-17  
> Scope: a read-only, temporary SQLite copy was used to reparse 50 JoyBomb raw posts in `draft-only` mode. The production database, Parser, Splitter, Story Dictionary, Queue, and Discord were not changed.

## Method

- Sample: 50 `joybomb_archive` raw posts, stratified by available published year with fixed seed `20260717`.
- Execution: `parse_pending_raw_posts(..., source="joybomb_archive", draft_only=True)` ran only on a system temporary database copy.
- Identity checked: `(raw_post_id, section_hash, splitter_version, parser_version)`.
- Assessment labels are conservative manual audit labels based on the source text in this sample; they are not a claim about a future parser revision.

## Sample Summary

- Raw posts: **50**
- Sections / parse drafts: **102 / 102**
- Multi-section raw posts: **18**
- Parse failures: **0**
- Story-event direct text matches: **3** (2 raw posts)
- Sample year distribution: 2016: 4, 2017: 16, 2018: 14, 2019: 12, 2020: 17, 2021: 21, 2022: 18

### Human Triage Totals

- Event name: Incorrect 21, Not assessed: preamble 15, Correct/usable 53, Not applicable 13
- Content type judgement: Reasonable 87, Deviates 1, Incorrect: activity misclassified by maintenance wording 14
- Parser output content types: event 37, notice 13, other 10, suit_event 15, system 24, welfare 3
- Suit: Correct names 13, No named suit 84, Missed 4, False positive 1; candidates total 28
- Story event: exact hits 3, confirmed misses 0, false positives 0, no direct text match 99
- Draft status: Auto 0, Needs Review 0, Failed 0, Pending 102 (intentional draft-only result)
- Recommended draft action: Keep: human review needed 58, Skip: system/community/maintenance 26, Skip: preamble 18

## Raw Post Index

| Raw post | Notice ID | Date | Source title | Sections |
|---:|---|---|---|---:|
| 107 | 1:8576 | 2016-08-17 | 新聞公告 | 1 |
| 108 | 11:8562 | 2016-08-13 | 新聞公告 | 1 |
| 119 | 2:10213 | 2017-07-18 | 新聞公告 | 1 |
| 124 | 1:10345 | 2017-08-04 | 新聞公告 | 1 |
| 125 | 11:8573 | 2016-08-16 | 新聞公告 | 1 |
| 130 | 11:8581 | 2016-08-17 | 新聞公告 | 1 |
| 136 | 1:10467 | 2017-08-24 | 新聞公告 | 1 |
| 159 | 11:10693 | 2017-10-03 | 新聞公告 | 1 |
| 162 | 3:10751 | 2017-10-18 | 新聞公告 | 1 |
| 182 | 1:11082 | 2017-12-21 | 活動 【活動】聖誕活動［第四彈］飄雪聖誕 奇遇之旅 2017/12/21 | 5 |
| 185 | 1:11038 | 2017-12-14 | 新聞公告 | 5 |
| 195 | 1:11106 | 2017-12-28 | 新聞公告 | 1 |
| 199 | 1:11138 | 2018-01-08 | 新聞公告 | 6 |
| 209 | 11:11221 | 2018-01-26 | 新聞公告 | 1 |
| 224 | 2:11297 | 2018-02-07 | 新聞公告 | 1 |
| 232 | 1:11199 | 2018-02-28 | 新聞公告 | 2 |
| 237 | 1:11362 | 2018-03-09 | 新聞公告 | 1 |
| 247 | 1:11375 | 2018-03-14 | 新聞公告 | 1 |
| 251 | 11:11382 | 2018-03-15 | 新聞公告 | 1 |
| 263 | 1:11532 | 2018-05-11 | 新聞公告 | 1 |
| 285 | 11:12522 | 2019-06-12 | 【系統】6/13 臨時停機維護公告 | 1 |
| 292 | 11:12547 | 2019-06-26 | 【系統】遊光長廊停權名單_0626 | 1 |
| 305 | 1:12726 | 2019-09-10 | 占卜禮盒活動說明 | 2 |
| 319 | 11:12636 | 2019-08-04 | 【系統】0804 Facebook登入切換異常 | 1 |
| 334 | 1:12762 | 2019-11-08 | 復刻‧海櫻 螢光之靈 | 5 |
| 337 | 11:12805 | 2019-10-25 | 聯邦商貿禮盒品項異常 | 1 |
| 344 | 11:12741 | 2019-09-24 | 【系統】遊光長廊停權名單_0924 | 1 |
| 367 | 1:13393 | 2020-08-01 | MyCard 暑期聯促活動 | 1 |
| 377 | 11:13262 | 2020-04-28 | 遊光長廊停權名單_0428 | 1 |
| 381 | 1:13464 | 2020-08-10 | 四週年慶．苜蓿奇遇 幸運之旅 | 5 |
| 383 | 2:13569 | 2020-09-14 | 維茵田園 豐收獻禮　《奇迹暖暖》全新套裝推出 「慢飛天使」設計款上衣 同步登場 | 1 |
| 422 | 1:13628 | 2020-11-10 | 復刻 白永羲 螢光之靈 | 3 |
| 451 | 1:13383 | 2020-06-30 | 登入送 時光旋律 | 5 |
| 470 | 11:13761 | 2020-11-26 | 遊光長廊停權名單_1126 | 1 |
| 482 | 11:14045 | 2021-02-09 | 鑽石紅包領取異常補償公告 | 1 |
| 507 | 11:14215 | 2021-04-10 | 時光回溯星輝流沙購買介面異常_已修復 | 1 |
| 513 | 1:14254 | 2021-04-25 | 神眷之地 沙海尋秘 | 4 |
| 516 | 1:14158 | 2021-04-16 | 點滴心頭的雨季戀曲 | 5 |
| 520 | 11:14343 | 2021-06-03 | 6/3 開機公告 | 1 |
| 521 | 1:14367 | 2021-06-09 | 歡慶端午送好禮 | 2 |
| 525 | 1:14360 | 2021-06-10 | 限時簽到送【墨筆檀香】 | 4 |
| 599 | 1:14803 | 2021-12-02 | 復刻 拂蘇 螢光之靈 | 3 |
| 606 | 1:15247 | 2022-05-12 | 星光幣雙倍活動 | 2 |
| 609 | 11:15263 | 2022-05-10 | 5/12部分系統維護公告 | 1 |
| 615 | 1:15350 | 2022-06-15 | 奇迹大陸 知識問答 | 8 |
| 618 | 11:15310 | 2022-05-19 | 5/18 FB登入異常補償公告 | 1 |
| 619 | 1:15293 | 2022-06-03 | 暖暖慶端午獎勵活動 | 2 |
| 621 | 1:15250 | 2022-05-15 | 主題商店 限時開啟 | 1 |
| 622 | 1:15245 | 2022-05-07 | 五月芬芳登入送 | 1 |
| 643 | 1:15465 | 2022-07-29 | 六週年紀念貼圖 集章活動 | 2 |

## Per-Section Results

The summary is the first source-text sentence. Hashes are the current full section fingerprints.

### Raw 107 / Notice 1:8576

- Date: 2016-08-17T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=8576](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=8576)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 31bac09bc8ff8d3f732f8efa4e1ee45cc8031261784251e71eb789557dfe3023 | whole_notice | 新聞公告 親愛的暖粉, 慶祝台港澳版本上線，大喵準備了眾多活動增加暖粉在奇迹大陸冒險的樂趣~ ♡ 一、暑期好禮三重送 ※第一重－2016/08/17 上線後-2016/08/23 23:59:59 每天可領取金幣*1萬+ ※第二重－2016/08/23 00? | 新聞公告 | suit_event | 童趣美夢, 璀璨星河, 紅裳錦繡, 花田香氣, 慕冬天使 | ? | pending | Event: Incorrect; Type: Reasonable; Suit: Correct names; Story: No direct match; Draft: Keep: human review needed |

### Raw 108 / Notice 11:8562

- Date: 2016-08-13T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=8562](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=8562)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 6f96cf594780efe86c867a88086efb62ed4325501e9781740e437ae78afc1bf7 | whole_notice | 新聞公告 ♡遊戲安裝問題 （・⊝・∞） Q 遊戲應如何下載安裝以及進行更新？ A Android用戶在Google Play商店（iOS用戶在App Atore） 搜索「奇迹暖暖」按照商店指引下載安裝即可。 下載任意門如下： Android： http://? | 新聞公告 | system | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 119 / Notice 2:10213

- Date: 2017-07-18T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=2&K=10213](https://nu3.joybomb.com.tw/notice/noticecontent?N=2&K=10213)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 892f12a784b48e9b765c1a599b2e01fc2fb752c9699193080f7ea9bb640cad2b | whole_notice | 新聞公告 時尚換裝夢幻手遊《奇迹暖暖》今(18日)迎來暑期盛大改版，推出搭配師聯盟全新玩法「搭配戰」，將能展現聯盟團結一致的精神；而隨著第13章節同步登場，《奇迹暖暖》劇情正式進入高峰，將陪伴搭配師們度過美好的盛夏時光！ 搭配師聯盟全新玩法！齊心協力參加「凝? | 新聞公告 | suit_event | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: Missed; Story: No direct match; Draft: Keep: human review needed |

### Raw 124 / Notice 1:10345

- Date: 2017-08-04T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10345](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10345)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | eb9c5c17dde8f6bc71270d10d7ffdc3401e603dba53f91af98213e3d37d6e293 | whole_notice | 新聞公告 親愛的搭配師，你好！ 奇迹暖暖週年盛典即將開跑 我們邀請各地暖粉們呼朋引伴 一同前往為奇迹暖暖慶生，進行盛大搭配賽！ 快進入下面的表單中填寫資料，幸運的搭配師將可以獲得參賽資格喔！ 搭配師們必須根據初賽主題「少女的週年慶」做搭配 1.前往奇迹暖暖遊? | 新聞公告 | notice | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 125 / Notice 11:8573

- Date: 2016-08-16T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=8573](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=8573)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 7feec4736e301aa34d05b0288ac218fd21e0d36bdb69b0f39b14901b7414133d | whole_notice | 新聞公告 《奇迹暖暖》Web儲值開放！ iOS / Android版： http://nmn.tw/215 即日起大家可以透過Web儲值，使用辣椒卡或是小額付費來儲值啦！ 鑽石品項 新台幣 100鑽石 NT$50 430鑽石 (內含30鑽石) NT$200 ? | 新聞公告 | event | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 130 / Notice 11:8581

- Date: 2016-08-17T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=8581](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=8581)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | f2a2e283734be8f2cf3d22a9424fd7e7929ba282505e64bc525b2d517470150d | whole_notice | 新聞公告 親愛的暖粉, 假若在奇迹大陸的時候，遇到以下這情況， 1. 好友名單 出現空白ID，假若點擊贈送愛心會出現［網路環境不穩定　請更換穩定的網路後重試！］此訊息。 2. 評選賽、關卡排名 出現空白ID 3. 好友寄送的愛心郵件 出現空白ID 很抱歉..? | 新聞公告 | notice | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 136 / Notice 1:10467

- Date: 2017-08-24T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10467](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10467)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | fce0794d26eeda92c520f86ef7aea15197f1697c17841bd610e38e4c394ffcb4 | whole_notice | 新聞公告 親愛的搭配師，你好！ 奇迹暖暖週年盛典台中場次即將來臨，我們邀請搭配師們呼朋引伴，一同前往為暖暖慶生，進行盛大搭配賽。 未在決賽名單中的搭配師，仍可至現場觀賽。 現場將有甜美拍照區、打卡禮及搶答活動與 遊戲體驗區中所舉辦的：「週年慶搭配評選賽」 唷? | 新聞公告 | event | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 159 / Notice 11:10693

- Date: 2017-10-03T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=10693](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=10693)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | ba97514b876aa609128da28e8e710c4d421edc631d26eccc77c56882f5faa0d6 | whole_notice | 新聞公告 親愛的搭配師，你好！ 今日例行維護更新項目如下： 【新增】遊戲內新增520鑽+狂歡券一張商品項目。 「狂歡券」可選擇謎之屋之中「縹緲軒 晝夜迴廊 雲禪天塔 流光庭園」 任意一閣開啟24小時半價狂歡，打折時間可以累計哦~ 【新增】主線關卡第十五章‧上? | 新聞公告 | system | 氤氳仙子, 新增 | ? | pending | Event: Incorrect; Type: Reasonable; Suit: False positive; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 162 / Notice 3:10751

- Date: 2017-10-18T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=3&K=10751](https://nu3.joybomb.com.tw/notice/noticecontent?N=3&K=10751)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | b8d540395a5ed64207905d96ac0fd89a8cd352fd754b27d24f13e45e78ebc1eb | whole_notice | 新聞公告 親愛的玩家您好，《Netmarble Joybomb 會員系統服務合約》於2017/10/18進行修正。為保障會員權益，請詳細閱讀更新後之服務條款所有內容。 會員服務合約 https://member.joybomb.com.tw/others/a? | 新聞公告 | notice | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 182 / Notice 1:11082

- Date: 2017-12-21T00:00:00
- Title: 活動 【活動】聖誕活動［第四彈］飄雪聖誕 奇遇之旅 2017/12/21
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11082](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11082)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 42eb6f1f172acb5153b68a42f5bf8c6c88ff29ffc14ea4e5e7fdfe1b616ec45d | whole_notice | 活動 【活動】聖誕活動［第四彈］飄雪聖誕 奇遇之旅 2017/12/21 在甜蜜的聖誕王國裡，就連星星都是撒了金色糖粉的巧克力味…糖霜仙子金色的長髮會是什麼味道的呢？ | 活動 【活動】聖誕活動［第四彈］飄雪聖誕 奇遇之旅 2017/12/21 | other | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | 55efeda7a1fd0c5bcea553594162aec66729255797222fbf0bb3718ab9d428d9 | explicit_activity | 飄雪聖誕　奇遇之旅 活動時間：2017/12/22 05:00 - 2017/12/26 23:59 活動內容： 各章節關卡通關成功後都會掉落道具「雪鈴鐺」 (聯盟關卡除外)。 使用「雪鈴鐺」幫小精靈打包霜糖禮盒與松果禮盒， 達到一定次數即可領取【雪夜迴旋曲? | 飄雪聖誕　奇遇之旅 | suit_event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 3 | 活動二 | bf762e5cbb8fe29ae33c786727c4338e7b893e937c42a7b1b453182fd7853f65 | explicit_activity | 來自世界各地的聖誕禮物 活動時間：2017/12/24 12:00 - 2017/12/26 23:59 活動內容：活動期間內，登錄遊戲會收到來自世界各地的聖誕禮物 每個遊戲帳號僅限領取一次。共有８封郵件哦！ 2017/12/24 12:00 - 2017/? | 來自世界各地的聖誕禮物 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 4 | 活動三 | 6beb0b01815d802adb279f29aa77333e13d3b154b8c977b569ffc0de82b6d866 | explicit_activity | 聖誕超值購 活動時間：2017/12/22 05:00 - 2017/12/26 23:59 活動內容：活動期間內，購買聖誕超值購，即可獲得【楓暖情】部件+100鑽石+1萬金幣。 每人僅限購一次。 | 聖誕超值購 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 5 | 活動四 | dfc1f9cf925b8c1ee4d153159901680864a1fec1c4c01d8748d1c4d69bb506bc | explicit_activity | 聖誕禮包 活動時間：2017/12/22 05:00 - 2017/12/26 23:59 活動內容：活動期間內，花費台幣30元可在聯邦商貿分別購買聖誕限定禮包！ 雪人的聖誕祝福［5個部件+60鑽+60Vip點數］ 薑餅人的糖果屋［5個部件+60鑽+60Vi? | 聖誕禮包 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 185 / Notice 1:11038

- Date: 2017-12-14T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11038](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11038)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 8d50ebe8b79d90dfa264ec2cb7023d4279b3edfc1e784a87ea23b6e39e0a7837 | whole_notice | 新聞公告 點燃仙女棒，就能把星星抓在手中。短暫的光芒消逝之後，你還會記得從前快樂的心情嗎？ | 新聞公告 | notice | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | fc93fe801914fb8b0d5b253bcc06716e756bb941d6a08d0960fbfa8a9b0edb5c | explicit_activity | 珍稀螢光之靈‧回憶花火 活動時間：2017/12/15 05:00 - 2017/12/19 23:59 活動內容： 活動期間內，在浮夢島進行探索將有機會獲得稀有螢光之靈【回憶花火 】， 獲得【回憶花火】即可開啟海櫻回憶夢境的【時光花火】。 | 珍稀螢光之靈‧回憶花火 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 3 | 活動二 | 8d4fd69b2b020a1d56dd86b0d842d6fcb3793f2e14888ec24eb9ed7ea5806c22 | explicit_activity | 累計消耗鑽石送珍稀螢光石 活動時間：2017/12/15 05:00 - 2017/12/19 23:59 活動期間花費鑽石達到指定額度，即可獲得相對應回饋好禮。 | 累計消耗鑽石送珍稀螢光石 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 4 | 活動三 | 568204247890401b56ded400967cbc7ad326bc3de78ee15e31ce83e023c91585 | explicit_activity | 海櫻的承諾 活動時間：2017/12/15 05:00 - 2017/12/17 23:59 活動內容：進行搭配競技場結算時，星光幣將會有雙倍獎勵！ 比拚勝利將獲得10個星光幣，比拚失敗將會獲得6個星光幣 | 海櫻的承諾 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 5 | 活動四 | f594210177f905c5247f4ed87cbcc2aab21abb619a80af88463cbe89651ca07f | explicit_activity | 海櫻的勉勵 活動時間：2017/12/15 05:00 - 2017/12/17 23:59 活動內容：活動期間內，公主級指定關卡雙倍掉率 ［金幣加倍］第五、六、十一章 ［金幣與服裝掉落率加倍］第八、十二章 如有任何問題再請至 客服中心 與我們反應，謝謝。 | 海櫻的勉勵 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 195 / Notice 1:11106

- Date: 2017-12-28T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11106](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11106)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 2c302a82e2a65009e5ccdb4144d23331910a2cb326b8675053f2bd48af4047e1 | whole_notice | 新聞公告 親愛的搭配師你好！ 《奇迹暖暖》很重視玩家的感受，也尊重每一位玩家提出的建議。 我們了解到，多數玩家感覺目前的活動過於緊湊，希望可以放慢腳步。 來自大家的意見我們都收到了，也決定將元旦系列活動內容進行調整。 異動項目： 飛躍午夜 午動心跳此活動將暫? | 新聞公告 | event | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 199 / Notice 1:11138

- Date: 2018-01-08T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11138](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11138)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 81bdf0fd05432c7aac423d6a53db8e54610abb24642dff7477abd4be4b63808e | whole_notice | 新聞公告 冰雪女王的甦醒是永冬之夜的開端，此夜之後，大陸北端陷入漫長的黑夜，等候春天回歸。 當二月來臨，冰雪融化，信鴿森林就不再是冰雪女王的領地；春之少女帶來了萬物的復甦。 | 新聞公告 | notice | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | 98253fd7a3966600e102b4b868383080e21113e2021bdbd9eac231e84de8c6da | explicit_activity | 女王的邀請－冰雪舞會 活動期間：2018/01/09 05:00 - 2018/01/15 23:59 活動方式：於活動關卡「冰雪舞會」中闖關即可獲得「雪花」。使用雪花可以兌換「春之少女」套裝的初級部件；透過進化可以獲得完整「春之少女」套裝。 累計收集達到指? | 女王的邀請－冰雪舞會 | other | ? | ? | pending | Event: Correct/usable; Type: Deviates; Suit: Missed; Story: No direct match; Draft: Keep: human review needed |
| 3 | 活動二 | 90968f4577495b939b727ce5dcb553b8782ef7608401401bc6f0b4e06405470c | explicit_activity | 女神的誕生－累計儲值活動 活動時間：2018/01/09 05:00 - 2018/01/15 23:59 活動方式：活動期間內，累計儲值購買鑽石達到指定額度即可領取【花束情緣】與【海沫生珠】套裝。 | 女神的誕生－累計儲值活動 | suit_event | 海沫生珠 | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: Correct names; Story: No direct match; Draft: Keep: human review needed |
| 4 | 活動三 | 8cfd8b517477b10a99f3dfe11823522927f056ef018817c2d910cf0f854748eb | explicit_activity | 冰之女王的回歸－聯邦商貿限定販售 活動時間：2018/01/09 05:00 - 2018/01/15 23:59 活動期間內，聯邦商貿販售活動限定的冬之初雪禮盒、冬之光輝禮盒 | 冰之女王的回歸－聯邦商貿限定販售 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 5 | 活動四 | 75d859a7653dadd8fddf3773b21cad50e93c592d503fdde701f09d8f49b8eb43 | explicit_activity | 春之少女的歌聲－Web網頁限定販售 活動時間： 2018/01/09 11:00 - 2018/01/15 23:59 活動期間內，Web網頁販售活動限定的春之呢喃禮盒、春之祈願禮盒 購買方式： NT.150付費方式－請參考以下 NT.500付費方式－ 現有? | 春之少女的歌聲－Web網頁限定販售 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 6 | 活動五 | 51304bffd1fa0b92f9f3d42a05865aa489bb88da4fc01a21b54a3436ebfef480 | explicit_activity | 春之少女的私語－公主級關卡加倍 活動時間：2018/01/12 05:00 - 2018/01/14 23:59 活動期間內，公主級指定關卡雙倍掉率 金幣加倍：第十章、第十一章、第十四章 金幣、掉落率加倍：第二章、第十二章 詳細的活動介紹請參考遊戲內的活動B? | 春之少女的私語－公主級關卡加倍 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 209 / Notice 11:11221

- Date: 2018-01-26T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=11221](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=11221)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 2797705ab67fee38f42024dc9f70d644c426cbfed8d53f9ef4beb42a1e0751db | whole_notice | 新聞公告 親愛的玩家，您好： 我們預計於2018年1月31日(三)早上09:30~13:30進行網路調整， 屆時網石棒辣椒官網、會員網站及各遊戲Web儲值功能將無法使用。 受影響之網站及功能： ＃網石棒辣椒官方網站 ＃會員網站（影響功能：各遊戲網頁儲值頁面、? | 新聞公告 | notice | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 224 / Notice 2:11297

- Date: 2018-02-07T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=2&K=11297](https://nu3.joybomb.com.tw/notice/noticecontent?N=2&K=11297)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 90042d632d4e26ffcb3f7df31e306eb3bff50c5a827eb8166169bdf30e9990d4 | whole_notice | 新聞公告 最夢幻的穿搭養成手遊《奇迹暖暖》今(7日)宣布，全新主線關卡第17章和系統「時光流轉之庭」嶄新登場。而為迎接即將到來的農曆新年，《奇迹暖暖》也推出2018新年套裝和紅包活動，為搭配師帶來充滿喜氣的春節祝賀！ 主線關卡第17章正式登場 2位新角色亮相? | 新聞公告 | suit_event | ? | 時光流轉 | pending | Event: Incorrect; Type: Reasonable; Suit: Missed; Story: Exact hit; Draft: Keep: human review needed |

### Raw 232 / Notice 1:11199

- Date: 2018-02-28T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11199](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11199)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 8973bafcff746c4dded95e6b1a9c14bf5b63f3ace7a8f2ce6cb107dcd53d746d | whole_notice | 新聞公告 親愛的暖粉， 暖暖與全家 Fami Port 有新活動囉！ 活動時間：2018/02/28 00:00 - 2018/03/13 23:59 活動方式：【限定使用全家Fami Port】於活動期間單筆購買（含）NT.200(鑽石430)以上， 即可? | 新聞公告 | event | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 儲值 | 675b3c8b72022aae572bf912d99a7bb591eccca04dffdb5c3ce716f87a7a8d45 | explicit_category | 3、本公司保留修改獎品與獎項配發的最後決定權。 4、活動期間，系統若發生問題或不可抗力之因素導致活動無法進行，本公司將保留變更、終止本活動時間、內容之權利。 5、一切以伺服器紀錄為準。 6、活動獎勵［大喵的私房錢－金幣*3萬］每個遊戲帳號限領一次。 | 3、本公司保留修改獎品與獎項配發的最後決定權。 | event | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 237 / Notice 1:11362

- Date: 2018-03-09T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11362](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11362)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 14b442cb28eb841f92c8eb19e96b1a95604cd2a7cd65f76856b6b6cc6f6241a6 | whole_notice | 新聞公告 親愛的搭配師，你好！ 《奇迹暖暖》03/14將進行例行性關機維護 維護關機時間：03/14 10:00~15:00 還請各位搭配師們提早下線，以免資料異常。 如維護時間有異動，還請搭配師們以官網最新公告為主。 如有不便，還請多包涵。 《奇迹暖暖營運? | 新聞公告 | system | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 247 / Notice 1:11375

- Date: 2018-03-14T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11375](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11375)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | d4d9cd75944160fe6963f7a59e7b934b99ac84ffcc4370df844a2c2f1ce5b416 | whole_notice | 新聞公告 親愛的搭配師，你好！ 03/14的停機維護已結束。 停機維護補償：314體力。會陸續於17:00後配發。 以下是這次維護更新的內容 ------ 【劇情章節】第18章 【限時優惠禮盒】 僅限遊戲內購買。禮盒內含精美套裝、鑽石、Vip經驗、星光幣、體? | 新聞公告 | system | 狩獵魔女, 金珠玉葉, 曉光的祈願, 遊園驚夢, 宇宙之汐, 來自雲端的國的綾羅, 青春風暴, 傳說中的鐵薔薇組織, 長街包子娘 | ? | pending | Event: Incorrect; Type: Reasonable; Suit: Correct names; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 251 / Notice 11:11382

- Date: 2018-03-15T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=11382](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=11382)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | fe68f2796cfd0ca1ec012f4639acc9ac53611c9bda823cfa648cd62bced64c30 | whole_notice | 新聞公告 親愛的搭配師你好， 已修正［ 體力不足無法抽取醉狂人之歌問題］， 謝謝搭配師的耐心等候，給搭配師帶來不便請見諒。 如果有其他問題再請至客服中心與我們反應，謝謝。 補償：60體力+50鑽石，陸續於12點後配發 若有其他問題再請至 客服中心 與我們反應? | 新聞公告 | notice | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 263 / Notice 1:11532

- Date: 2018-05-11T00:00:00
- Title: 新聞公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11532](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=11532)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 7ad978695f8f5a899a5d1a6955bdf31fb5bda3e450dee56f190e1b34f61f1cc8 | whole_notice | 新聞公告 親愛的搭配師，你好！ 05/11的停機維護已結束。 感謝暖粉的耐心等待，假若有任何問題歡迎至客服中心或粉絲團與我們反應。 本次維護補償為100體。 配送時間為2018/05/11 18:00:00 -2018/05/12 17:59:59 每個遊戲? | 新聞公告 | system | ? | ? | pending | Event: Incorrect; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 285 / Notice 11:12522

- Date: 2019-06-12T00:00:00
- Title: 【系統】6/13 臨時停機維護公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12522](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12522)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 606051b1e8cf7893f2032bc883cd717bc4125a249aa81f6bc5d62809a765b622 | whole_notice | 【系統】6/13 臨時停機維護公告 【系統】6/13 臨時停機維護公告 2019.06.12 16:00 親愛的搭配師你好， 因進行硬體設備更換作業， 奇迹暖暖將於6/13(四) 15:00－17:00進行停機維護作業。 還請各位搭配師們提早下線，以免資料異? | 6/13 臨時停機維護公告 | system | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 292 / Notice 11:12547

- Date: 2019-06-26T00:00:00
- Title: 【系統】遊光長廊停權名單_0626
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12547](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12547)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 660e3313ead9b22ba4da00cf43350491481f2dc5bc7bf0d86b84654768124550 | whole_notice | 【系統】遊光長廊停權名單_0626 【系統】遊光長廊停權名單_0626 2019.06.26 12:13 親愛的搭配師你好： 近期發現一些不雅或較為裸露的照片散布於【遊光長廊】中。 由於【遊光長廊】是遊戲內的公開系統，藉此系統搭配師們可以共享穿搭技巧，互相欣? | 遊光長廊停權名單_0626 | notice | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 305 / Notice 1:12726

- Date: 2019-09-10T00:00:00
- Title: 占卜禮盒活動說明
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=12726](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=12726)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | d63551f17b21aec16d75712f5d12a50e5f7824541037721a3927930aa78e37b8 | whole_notice | 占卜禮盒活動說明 占卜禮盒活動說明 2019.09.10 15:30 | 占卜禮盒活動說明 | other | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | 28477403a9b3bd42eba52558e967f1b5dd072983a359db4e7e03dfa4d6fa8e4e | explicit_activity | 活動時間：9/10 停機維護後 活動內容：停機維護後，占卜禮盒中將加入北地王國套裝【夢想雲霄】， 購買有套裝部件圖示的禮盒 (如上圖所示) 可隨機獲得全套套裝， 累計購買3次必可獲得套裝【夢想雲霄】。 占卜禮盒每日上午5點自動刷新，也可以選擇花費鑽石獲取額外? | 活動時間：9/10 停機維護後 | system | 夢想雲霄 | ? | pending | Event: Incorrect; Type: Incorrect: activity misclassified by maintenance wording; Suit: Correct names; Story: No direct match; Draft: Keep: human rev? |

### Raw 319 / Notice 11:12636

- Date: 2019-08-04T00:00:00
- Title: 【系統】0804 Facebook登入切換異常
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12636](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12636)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 39d07344937333c4d880991d0454ed99490306edd9997defd09613d73dd41f93 | whole_notice | 【系統】0804 Facebook登入切換異常 【系統】0804 Facebook登入切換異常 2019.08.04 22:35 親愛的搭配師你好, 目前有發生Facebook帳號切換登入異常的狀況, 若登出Facebook做帳號切換將會無法順利進入遊戲。 ? | 0804 Facebook登入切換異常 | welfare | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 334 / Notice 1:12762

- Date: 2019-11-08T00:00:00
- Title: 復刻‧海櫻 螢光之靈
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=12762](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=12762)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 3caefce3619c837338cc120da297d08a8cf993c40e85cf805a96e67ed2571362 | whole_notice | 復刻‧海櫻 螢光之靈 復刻‧海櫻 螢光之靈 2019.11.08 18:06 | 復刻‧海櫻 螢光之靈 | event | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | 241b277798f2f3f5a8751876ff93916190b0130edd980e2fb07233805deaa55a | explicit_activity | 珍稀螢光之靈‧回憶花火 復刻 活動時間：11/11 05:00 - 11/13 23:59 活動期間內，在浮夢島進行探索將有機會獲得稀有螢光之靈［回憶花火］， 獲得［回憶花火］即可開啟海櫻回憶夢境［時光花火］。 ※每個遊戲帳號僅限獲得一次 | 珍稀螢光之靈‧回憶花火 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 3 | 活動二 | c456c730c2b99d653401be8a180c5d92cd90fed2d96c24cddc079a0b6d27c8b3 | explicit_activity | 大喵限時任務 活動時間：11/11 05:00 - 11/18 23:59 活動內容：活動時間內完成大喵指定任務【碧潭竹影】， 即可獲得獎勵[公主級刷新券x1+體力x30+水晶鞋x1]。 ※請於活動時間內至活動介面領取對應獎勵，逾期將不進行補發 | 大喵限時任務 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 4 | 活動三 | f9d657326707ced85dfe02800fa467af9fa59dcdcdf9bfd47b847a644c517738 | explicit_activity | 聯邦商貿限定販售［大喵的限時祝福］禮盒 活動時間：11/11 05:00 - 11/18 23:59 活動內容：聯邦商貿限定販售NT.33的［大喵的限時祝福］禮盒。 內含VIP經驗x66+鑽石x66+體力x100+星光幣x40+公主級刷新券x2，每個遊戲帳號? | 聯邦商貿限定販售［大喵的限時祝福］禮盒 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 5 | 活動四 | adae42a0ec244d8f4d9a7e8848e6d69cb100e255968718a4e841d9ca69dbf6ac | explicit_activity | 神秘商店開啟 活動時間：11/11 05:00 - 11/13 23:59 活動內容：活動期間內，搭配師可於神秘商店中購買尚未獲得之套裝禮包， 禮包內含未獲得之隨機套裝、鑽石、VIP經驗等，禮包內有機會出現多套套裝。 禮包每天淩晨5點後可免費刷新一次，若神祕? | 神秘商店開啟 | suit_event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 337 / Notice 11:12805

- Date: 2019-10-25T00:00:00
- Title: 聯邦商貿禮盒品項異常
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12805](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12805)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | e3d8f97c6e3ec3d02c5ea241d28138d232503ae654eea374a44fad11eac1ff6f | whole_notice | 聯邦商貿禮盒品項異常 聯邦商貿禮盒品項異常 2019.10.25 12:00 親愛的搭配師你好， 今日10/25 05:00-10:00 聯邦商貿出現「流星點綴」禮盒品項， 由於禮盒內容物『祈願流星』代幣目前尚未上架， 購買此商品的玩家，系統已將禮盒內容物進? | 聯邦商貿禮盒品項異常 | notice | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 344 / Notice 11:12741

- Date: 2019-09-24T00:00:00
- Title: 【系統】遊光長廊停權名單_0924
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12741](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=12741)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 856ec0ace9c2e6ebeb54a9ea219c36fae0e7495c78756257f447dec7316406d2 | whole_notice | 【系統】遊光長廊停權名單_0924 【系統】遊光長廊停權名單_0924 2019.09.24 10:27 親愛的搭配師你好： 近期發現一些不雅或較為裸露的照片散布於【遊光長廊】中。 由於【遊光長廊】是遊戲內的公開系統，藉此系統搭配師們可以共享穿搭技巧，互相欣? | 遊光長廊停權名單_0924 | notice | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 367 / Notice 1:13393

- Date: 2020-08-01T00:00:00
- Title: MyCard 暑期聯促活動
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=13393](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=13393)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | af1500a6a38f99a6243c33bae5c9a1c47bfe37d6f2daebe2d8920bd09ce85713 | whole_notice | MyCard 暑期聯促活動 MyCard 暑期聯促活動 2020.08.01 00:00 活動時間：08/01 00:00-08/31 23:59 活動方式：活動期間內至7-ELEVEN、全家、萊爾富及OK超商購買MyCard指定面額，並儲至《奇迹暖暖》，即? | MyCard 暑期聯促活動 | system | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 377 / Notice 11:13262

- Date: 2020-04-28T00:00:00
- Title: 遊光長廊停權名單_0428
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=13262](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=13262)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | d4eea5584df0133f5b7d9c4eb10f7484b4e36ebc9adf14074acda5488ff24e73 | whole_notice | 遊光長廊停權名單_0428 遊光長廊停權名單_0428 2020.04.28 17:06 親愛的搭配師你好： 近期發現一些不雅或較為裸露的照片散布於【遊光長廊】中。 由於【遊光長廊】是遊戲內的公開系統，藉此系統搭配師們可以共享穿搭技巧，互相欣賞彼此的時尚美感? | 遊光長廊停權名單_0428 | notice | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 381 / Notice 1:13464

- Date: 2020-08-10T00:00:00
- Title: 四週年慶．苜蓿奇遇 幸運之旅
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=13464](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=13464)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | ca7f79efcfb5a5864151e09d5fad34b5c69fb28296a721016412c8ad67b270b4 | whole_notice | 四週年慶．苜蓿奇遇 幸運之旅 四週年慶．苜蓿奇遇 幸運之旅 2020.08.10 19:00 | 四週年慶．苜蓿奇遇 幸運之旅 | other | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | 216a0765b1f8adc02dde4ae62a51234db6564c9869e592b78cd0ee63c2f65372 | explicit_activity | 苜蓿奇遇 活動時間：08/12 停機維護後 - 08/21 23:59 活動內容：過關所有主線章節關卡都可獲得「苜蓿草」，收集「苜蓿草」可以兌換精緻莉莉斯套裝【幸運之旅】。過關還有機會遇到黛奧比，送給她「苜蓿草」能獲得額外獎勵。 ※活動結束後「苜蓿草」將會清? | 苜蓿奇遇 | system | 幸運之旅 | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: Correct names; Story: No direct match; Draft: Keep: huma? |
| 3 | 活動二 | 971770db2c0336ff524f2f032e47c31abd41191b8d9d0be8dcab6bcb7c3a0808 | explicit_activity | 累計消耗體力送獎勵 活動時間：08/12 維護後 - 08/28 23:59 活動內容：活動期間內，累計消耗體力達到指定數量，即可領取體力、染料劑、許願券、鑽石和散件-吉祥花火+風起雲祥、小屋交通工具-吉祥舞獅、頭像框-福鼠呈祥。 ※每個遊戲帳號限領一次 ※? | 累計消耗體力送獎勵 | system | ? | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: No named suit; Story: No direct match; Draft: Keep: huma? |
| 4 | 活動三 | e6634c20f27464b2dfedc4367ef64c919ea34dede4d9bf250701b29aa8cf7134 | explicit_activity | 公主級不限次數重置 活動時間：08/12 維護後 - 08/28 23:59 活動期間內，可無限次花費鑽石重置公主級關卡次數。 | 公主級不限次數重置 | system | ? | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: No named suit; Story: No direct match; Draft: Keep: huma? |
| 5 | 活動四 | 3fd2ae05cd0699484a7ae6b2c040864858ebdbeb77799536063fa650b24cc9ae | explicit_activity | 公主級三倍 活動時間：08/12 維護後 - 08/15 23:59 活動內容：指定的公主級關卡－服裝掉落率、通關後獲得金幣三倍。 服裝掉落率三倍：第2章、第5章、第8章、第11章、第14章、第17章、第二卷第1章、第二卷第4章。 通關後獲得金幣三倍：第1章? | 公主級三倍 | system | ? | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: No named suit; Story: No direct match; Draft: Keep: huma? |

### Raw 383 / Notice 2:13569

- Date: 2020-09-14T00:00:00
- Title: 維茵田園 豐收獻禮　《奇迹暖暖》全新套裝推出 「慢飛天使」設計款上衣 同步登場
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=2&K=13569](https://nu3.joybomb.com.tw/notice/noticecontent?N=2&K=13569)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | f72cb611b1c3efbec27ea02744c6171f48ef5a24882a4382a1a7cc090f70d884 | whole_notice | 維茵田園 豐收獻禮　《奇迹暖暖》全新套裝推出 「慢飛天使」設計款上衣 同步登場 維茵田園 豐收獻禮　《奇迹暖暖》全新套裝推出 「慢飛天使」設計款上衣 同步登場 2020.09.14 16:36 主打換裝題材的時尚夢幻手遊《奇迹暖暖》今(14日)宣布，全新活動? | 維茵田園 豐收獻禮　《奇迹暖暖》全新套裝推出 「慢飛天使」設計款上衣 同步登場 | suit_event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: Missed; Story: No direct match; Draft: Keep: human review needed |

### Raw 422 / Notice 1:13628

- Date: 2020-11-10T00:00:00
- Title: 復刻 白永羲 螢光之靈
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=13628](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=13628)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | e38ab35cdeb5152de4dcfb3e37867b0ece3f0150289ca99e64b03763bb8579f8 | whole_notice | 復刻 白永羲 螢光之靈 復刻 白永羲 螢光之靈 2020.11.10 12:00 | 復刻 白永羲 螢光之靈 | event | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | fa07055df8fdda399796f92dddcc503a9d967375ca9f46183645eb67100effbb | explicit_activity | 復刻 珍稀螢光之靈 活動時間：11/12 05:00 - 11/14 23:59 活動內容：在浮夢島進行探索將有機會獲得稀有螢光之靈［碧霄吟］， 獲得［碧霄吟］即可開啟白永羲回憶夢境［千秋朝雲錄］。 ※每個遊戲帳號僅限獲得一次 | 復刻 珍稀螢光之靈 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 3 | 活動二 | a62754ba08f3bfcb139d7374f1356b4ac81932309344747dfe4c83c166b1f95f | explicit_activity | 神秘商店限時開啟 活動時間：11/12 05:00 - 11/14 23:59 活動內容：活動期間內，搭配師可於神秘商店中購買尚未獲得之套裝禮包， 禮包內含未獲得之隨機套裝、鑽石、VIP經驗等，禮包內有機會出現多套套裝。 禮包每天凌晨5點後可免費刷新一次，若? | 神秘商店限時開啟 | suit_event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 451 / Notice 1:13383

- Date: 2020-06-30T00:00:00
- Title: 登入送 時光旋律
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=13383](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=13383)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 877cca9e50644b1666a481849d8057498bf190886660f09846ec3a762bbae63b | whole_notice | 登入送 時光旋律 登入送 時光旋律 2020.06.30 19:00 | 登入送 時光旋律 | welfare | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | 8f110d22e0fe799ecc5b5d0eb9ad3cae9ba6cb1b5639e83a60d5b320f958eeb0 | explicit_activity | 登入送 活動時間：07/01 維護後 - 07/07 23:59 活動內容：活動期間內登入遊戲即可透過信箱信件領取［時光旋律］+體力x60，每個遊戲帳號限領一次。 ※每個遊戲帳號限領1次 ※請於信件到期日前領取對應獎勵，逾期將不進行補發 | 登入送 | system | ? | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: No named suit; Story: No direct match; Draft: Keep: huma? |
| 3 | 活動二 | fe43e26014d9f1b75ce049a333d52d63447216214547f173c2caec906c6b05b5 | explicit_activity | 神秘商店限時開啟 活動時間：07/01 維護後 - 07/01 23:59 活動內容：活動期間內，搭配師可於神秘商店中購買尚未獲得之套裝禮包， 禮包內含未獲得之隨機套裝、鑽石、VIP經驗等，禮包內有機會出現多套套裝。 禮包每天凌晨5點後可免費刷新一次，若神祕? | 神秘商店限時開啟 | system | ? | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: No named suit; Story: No direct match; Draft: Keep: huma? |
| 4 | 活動三 | a622890f89f4961231c248ca8d8e41a8e49da4fd181ede989391c2305bf94a3e | explicit_activity | 聯邦商貿販售限時禮盒 活動時間：07/01 維護後 - 07/07 23:59 活動內容：聯邦商貿限定販售NT.33的［新章節應援禮盒］禮盒， 內含VIP經驗x66+體力x300+星光幣x30+公主級刷新券x6+幸運加成次數x6+金幣x60000，每個遊戲帳? | 聯邦商貿販售限時禮盒 | system | ? | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: No named suit; Story: No direct match; Draft: Keep: huma? |
| 5 | 活動四 | 03c0639e2aefd72a07ef2b81f1ed4a562962a209fe5b1840db58b6855e3212a5 | explicit_activity | 公主級雙倍 活動時間：07/03 05:00 - 07/05 23:59 活動內容：指定的公主級關卡－服裝掉落率、通關後獲得金幣加倍。 服裝掉落率加倍：第8章、第12章、第17章。 通關後獲得金幣加倍：第6章、第15章、第二卷第1章。 通關後獲得金幣、服裝掉? | 公主級雙倍 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 470 / Notice 11:13761

- Date: 2020-11-26T00:00:00
- Title: 遊光長廊停權名單_1126
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=13761](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=13761)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | f559e1cb3ba8906ee3bfe7231d3e0768b281c68fb0814a459abdc58795bb4e64 | whole_notice | 遊光長廊停權名單_1126 遊光長廊停權名單_1126 2020.11.26 10:48 親愛的搭配師你好： 近期發現一些不雅或較為裸露的照片散布於【遊光長廊】中。 由於【遊光長廊】是遊戲內的公開系統，藉此系統搭配師們可以共享穿搭技巧，互相欣賞彼此的時尚美感? | 遊光長廊停權名單_1126 | notice | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 482 / Notice 11:14045

- Date: 2021-02-09T00:00:00
- Title: 鑽石紅包領取異常補償公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=14045](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=14045)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 2e8e597386ab01d99267c8d38601d0904271764cfff76160c7f93bd14bf5fd9c | whole_notice | 鑽石紅包領取異常補償公告 鑽石紅包領取異常補償公告 2021.02.09 16:17 親愛的搭配師您好， 2/4停機維護後，有收到部分玩家回報發生鑽石紅包領取異常問題， 因此我們將請技術團隊撈取固定期間內有出現異常紀錄的玩家名單進行補發， 補償共分三階段，時? | 鑽石紅包領取異常補償公告 | system | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 507 / Notice 11:14215

- Date: 2021-04-10T00:00:00
- Title: 時光回溯星輝流沙購買介面異常_已修復
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=14215](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=14215)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 68ec63a05ad6de923d4633dec88679efc33e0a9b216623d5c46623c225c67730 | whole_notice | 時光回溯星輝流沙購買介面異常_已修復 時光回溯星輝流沙購買介面異常_已修復 2021.04.10 08:49 親愛的搭配師您好， 目前時光回溯星輝流沙購買介面異常的問題已於12點修復完畢， 給各位帶來不便還請見諒， 如有任何問題請至客服中心洽詢，謝謝。 《奇? | 時光回溯星輝流沙購買介面異常_已修復 | notice | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 513 / Notice 1:14254

- Date: 2021-04-25T00:00:00
- Title: 神眷之地 沙海尋秘
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14254](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14254)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | fd28bed8a9654d40bc160378b78ffe176f85038eb7d3aef377569b671be22a4e | whole_notice | 神眷之地 沙海尋秘 神眷之地 沙海尋秘 2021.04.25 12:00 | 神眷之地 沙海尋秘 | other | ? | 神眷之地 | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: Exact hit; Draft: Skip: preamble |
| 2 | 活動一 | 6d58bc3a451daf1d5b4eea2aa3d8d2bff3203efec6abc9c4fd95f555e30c3d94 | explicit_activity | 神眷之地 活動時間：04/29 05:00 - 05/08 23:59 活動內容：前往探尋「迷途之果」，將隨機附贈限定服飾部件、鑽石、金幣或體力獎勵。 收集一定數量的「迷途之果」，獲得秘境之路的指引，即可領取精緻頭像掛飾及隨機一套神眷之地·故事套裝。 故事套? | 神眷之地 | suit_event | 虔誠神女 | 神眷之地 | pending | Event: Correct/usable; Type: Reasonable; Suit: Correct names; Story: Exact hit; Draft: Keep: human review needed |
| 3 | 活動二 | 385d1c1984df6469f961711f7691319f9c6d199f94fc570f2673c1236fdf5a0d | explicit_activity | 累計購買鑽石達指定數量加贈套裝 活動時間：04/29 05:00 - 05/08 23:59 活動內容：活動期間內累計儲值鑽石達指定數量即可獲得精緻套裝。 累計儲值830鑽石可獲得【幽夜鐘鳴】套裝。 累計儲值2140鑽石可獲得【爆裂特工】套裝。 ※每個遊戲帳? | 累計購買鑽石達指定數量加贈套裝 | suit_event | 幽夜鐘鳴, 爆裂特工 | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: Correct names; Story: No direct match; Draft: Keep: human review needed |
| 4 | 活動三 | 2779897db18900553330b71b22a63e2cd4e494fae96cb474172d14e5c34cb73d | explicit_activity | 聯邦商貿販售限時禮盒 活動時間：04/28 維護後 - 05/04 23:59 活動內容：聯邦商貿限定販售NT.33的［新章節應援禮盒］禮盒， 內含VIP經驗x66+體力x300+星光幣x30+公主級刷新券x6+幸運加成道具x6+金幣x60,000，每個遊戲? | 聯邦商貿販售限時禮盒 | system | ? | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: No named suit; Story: No direct match; Draft: Keep: huma? |

### Raw 516 / Notice 1:14158

- Date: 2021-04-16T00:00:00
- Title: 點滴心頭的雨季戀曲
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14158](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14158)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 7dbf16838c3f0e4366f481b1e934888609af65b70ca9c29d0edb5e65a6932378 | whole_notice | 點滴心頭的雨季戀曲 點滴心頭的雨季戀曲 2021.04.16 12:00 | 點滴心頭的雨季戀曲 | other | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | 7f833c761b9315ee3d91b42849a27f43ab4f9a0fd0dee7ed30bd572ce8439071 | explicit_activity | 聯邦商貿販售限時禮盒 活動時間：04/17 05:00 - 04/27 23:59 活動內容：聯邦商貿限定販售NT.33的［雨季戀曲散件禮盒］禮盒， 內含鑽石x66+VIP經驗x66+散件x9，每個遊戲帳號限購1次。 聯邦商貿限定販售NT.33的［狂歡大喵禮? | 聯邦商貿販售限時禮盒 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 3 | 活動二 | d4c34a253fa2a1fca55210032602ab8660d13518d6a74ba74b897e2be1a8d0a3 | explicit_activity | 星光幣雙倍 活動時間：04/19 05:00 - 04/21 23:59 活動內容：活動期間內進行搭配競技場比拚不論輸贏，皆可獲得星光幣雙倍獎勵！ 比拚勝利將獲得10個星光幣，比拚失敗將會獲得6個星光幣。 | 星光幣雙倍 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 4 | 活動三 | f7fe35e18253ea0f02bad9035c12e80956d1c74ec73d044fd03a28b0a8d4c6c5 | explicit_activity | 大喵限時任務 活動時間：04/20 05:00 - 04/26 23:59 活動內容：參與限時任務活動，完成階段的部件製作任務，可獲得階段獎勵。 本次任務套裝為【狡黠天使】，集齊共可獲得［幻閣券x1+體力x30+稚嫩粉x1］。 ※請於活動時間內領取對應獎勵；? | 大喵限時任務 | suit_event | 狡黠天使 | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: Correct names; Story: No direct match; Draft: Keep: human review needed |
| 5 | 活動四 | 3f53f5bd9949725150fde4c80f0110110dca2bfd8b18099dfba7c79a0b2e5098 | explicit_activity | 聯邦商貿販售限時禮盒 活動時間：04/20 05:00 - 04/26 23:59 活動內容：聯邦商貿限定販售NT.33的［大喵的限時祝福］禮盒， 內含鑽石x66+VIP經驗x66+金幣x50,000+體力x50+星塵黑x5，每個遊戲帳號限購3次。 ※僅限使? | 聯邦商貿販售限時禮盒 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 520 / Notice 11:14343

- Date: 2021-06-03T00:00:00
- Title: 6/3 開機公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=14343](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=14343)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | e5640d7fca415f67a3d7c9834cda427cf899d32641b6793555ab7eb9b1091843 | whole_notice | 6/3 開機公告 6/3 開機公告 2021.06.03 14:02 6/3更新維護作業已結束， 感謝暖粉的耐心等待，假若有任何問題歡迎至客服中心與我們反應。 本次維護補償為體力x60 配送時間為6/3 17:00:00 - 23:59:59 ※每個遊戲帳號? | 6/3 開機公告 | system | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 521 / Notice 1:14367

- Date: 2021-06-09T00:00:00
- Title: 歡慶端午送好禮
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14367](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14367)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 27d5e766101ba500670fb72e867c6c013efd96c3a26c8676ef3304a393f8eab5 | whole_notice | 歡慶端午送好禮 歡慶端午送好禮 2021.06.09 19:00 | 歡慶端午送好禮 | other | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | b68d17bab65717e7caa781d08e679a688f8b2582bc007062d20d20df672e8da3 | explicit_activity | 粉絲團歡慶端午送好禮活動 活動時間：06/09 19:00～06/15 23:59 活動內容：活動期間內前往官方粉絲專頁並於 活動貼文 下方留下：＠一位好友 端午節快樂！一起在奇迹暖暖線上見！ 活動結束後，累積貼文留言數達指定目標，可獲得的對應獎勵如下： ✿? | 粉絲團歡慶端午送好禮活動 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 525 / Notice 1:14360

- Date: 2021-06-10T00:00:00
- Title: 限時簽到送【墨筆檀香】
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14360](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14360)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 197bb49e0d2cb7760b4179a7f2b674a547c646fe3241c92d0a7a2d48f52d41a6 | whole_notice | 限時簽到送【墨筆檀香】 限時簽到送【墨筆檀香】 2021.06.10 12:00 | 限時簽到送【墨筆檀香】 | event | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | eefe37731dbed97d1b7449ca086f435f7fb51666e1885955a60c707c370bc2de | explicit_activity | 限時簽到送 活動時間：06/11 05:00 - 06/16 23:59 活動內容：於活動期間登入遊戲，即可從遊戲主畫面→活動→點擊「活動宣傳圖」每天簽到領取一個部件。 累計簽到滿5天，即可完成【墨筆檀香】套裝。 ※請於活動時間內領取對應獎勵；若未進行領取，? | 限時簽到送 | suit_event | 墨筆檀香 | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: Correct names; Story: No direct match; Draft: Keep: human review needed |
| 3 | 活動二 | ddac1b17d3babd1c8c49501e3cfe6e4a9d88242916335b0b5c195d3259837cc5 | explicit_activity | 公主級雙倍 活動時間：06/11 05:00 - 06/13 23:59 活動內容：指定的公主級關卡－服裝掉落率、通關後獲得金幣加倍。 服裝掉落率加倍：第7章、第12章、第15章。 通關後獲得金幣加倍：第4章、第16章、第19章。 通關後獲得金幣、服裝掉落率? | 公主級雙倍 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 4 | 活動三 | b824ebdbfaef09b9501b0709ef336df310c1aa4ebea44d5f8b9da0c58425b6b0 | explicit_activity | 神秘商店 活動時間：06/13 05:00 - 06/16 23:59 活動內容：活動期間內，搭配師可於神秘商店中購買尚未獲得之套裝禮包， 禮包內含未獲得之隨機套裝、鑽石、VIP經驗等，禮包內有機會出現多套套裝。 禮包每天凌晨5點後可免費刷新一次，若神祕商店? | 神秘商店 | suit_event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 599 / Notice 1:14803

- Date: 2021-12-02T00:00:00
- Title: 復刻 拂蘇 螢光之靈
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14803](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=14803)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 7bb12e415fd2ea838811eaffb36f98fa6e558ea18f8faa5ba206eea148baa40a | whole_notice | 復刻 拂蘇 螢光之靈 復刻 拂蘇 螢光之靈 2021.12.02 12:00 | 復刻 拂蘇 螢光之靈 | event | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | a55b338e2e52f3d42fc22773692b44fbc19ca14f5b8c48cddff6dd436a68e490 | explicit_activity | 復刻 珍稀螢光之靈 活動時間：12/03 05:00 - 12/05 23:59 活動內容：在浮夢島進行探索將有機會獲得稀有螢光之靈［呦呦鹿鳴］， 獲得［呦呦鹿鳴］即可開啟拂蘇回憶夢境［花田往事］。 ※每個遊戲帳號僅限獲得一次 | 復刻 珍稀螢光之靈 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 3 | 活動二 | 4e2d23d89b45795913890acde2c1d8868787933b169df053d055dfcc5ff85220 | explicit_activity | 公主級雙倍 活動時間：12/03 05:00 - 12/05 23:59 活動內容：指定的公主級關卡－服裝掉落率、通關後獲得金幣加倍。 通關後獲得金幣、服裝掉落率加倍：第1章、第6章、第12章。 服裝掉落率加倍：第2章、第5章、第18章。 通關後獲得金幣加倍? | 公主級雙倍 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 606 / Notice 1:15247

- Date: 2022-05-12T00:00:00
- Title: 星光幣雙倍活動
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15247](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15247)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 58d6afbeba1423bc7e9bb39698e9338bb6e5c7ef86041c1e643921595147ed79 | whole_notice | 星光幣雙倍活動 星光幣雙倍活動 2022.05.12 12:00 活動ㄧ、星光幣雙倍 活動時間：05/13 05:00 - 05/15 23:59 活動內容：活動期間內進行搭配競技場比拚不論輸贏，皆可獲得星光幣雙倍獎勵！ 比拚勝利將獲得10個星光幣，比拚失敗? | 星光幣雙倍活動 | event | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動二 | d3a0396b660a14cf40fa432eac8537cdd692242de50c16c8280d0650095130af | explicit_activity | 公主級雙倍 活動時間：05/13 05:00 - 05/15 23:59 活動內容：活動期間內，指定的公主級關卡－服裝掉落率、通關後獲得金幣加倍。 通關後獲得金幣、服裝掉落率加倍：第1章、第5章、第7章。 服裝掉落率加倍：第11章、第17章、第二卷第3章。 ? | 公主級雙倍 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 609 / Notice 11:15263

- Date: 2022-05-10T00:00:00
- Title: 5/12部分系統維護公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=15263](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=15263)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 9010854a58dd45773fafb7e9f720bb450927d579fd7eece60ae5088a569ba419 | whole_notice | 5/12部分系統維護公告 5/12部分系統維護公告 2022.05.10 14:57 親愛的搭配師您好， 網石棒辣椒會員系統將於5/12 (四) 09:00-10:30進行維護， 無法登入及無法使用之功能如下： 1. Netmarble Joybomb會員中? | 5/12部分系統維護公告 | system | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 615 / Notice 1:15350

- Date: 2022-06-15T00:00:00
- Title: 奇迹大陸 知識問答
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15350](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15350)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 86f05e44a8dbc8331c860a67b3afdd25517197706afeec6537ded6328622756d | whole_notice | 奇迹大陸 知識問答 奇迹大陸 知識問答 2022.06.15 12:00 | 奇迹大陸 知識問答 | other | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | 2c18c2c32cc2c7724e4260f66d380493c85bf1669c67dd651a8e6608aeb0152a | explicit_activity | 奇迹大陸知識問答 活動時間：06/16 維護後 - 06/28 23:59 活動內容：活動期間內，通關全地圖關卡（聯盟地圖除外）有機會獲得「羽毛筆」， 使用「羽毛筆」答對題目達到指定次數可領取對應獎勵。 答對66道題共可獲得套裝設計圖【爍金秋意】以及獎勵等。? | 奇迹大陸知識問答 | system | 爍金秋意 | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: Correct names; Story: No direct match; Draft: Keep: huma? |
| 3 | 活動二 | a08d27f1f633dc0177859cb6950fdc5f60123688953a875f342671e1d3007eb4 | explicit_activity | 限時簽到送 活動時間：06/16維護後 - 06/25 23:59 活動內容：於活動期間登入遊戲，即可從活動介面每天簽到領取一個部件。 累計簽到滿7天，即可完成【沉夜樂章】套裝。 ※請於活動時間內領取對應獎勵；若未進行領取，活動結束後不予進行兌換與補發 ※妝? | 限時簽到送 | system | 沉夜樂章 | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: Correct names; Story: No direct match; Draft: Keep: huma? |
| 4 | 活動三 | 6e3c7bf9336cc1a94fdee5fc01ac066d1742e661d71489c11a04bbd372b13184 | explicit_activity | 神秘商店 活動時間：06/16 維護後 - 06/16 23:59 活動內容：活動期間內，搭配師可於神秘商店中購買尚未獲得之套裝禮包， 禮包內含未獲得之隨機套裝、鑽石、VIP經驗等，禮包內有機會出現多套套裝。 禮包每天凌晨5點後可免費刷新一次，若神祕商店中的? | 神秘商店 | system | ? | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: No named suit; Story: No direct match; Draft: Keep: huma? |
| 5 | 活動四 | bb161d11371f8b21e40161e5328083c20e42f05521b28dafe138e6b9919a4b94 | explicit_activity | 超值購販售限時禮盒 活動時間：06/16 維護後 - 07/02 23:59 活動內容：遊戲內限時販售指定金額的［清涼超值購］禮盒。 內含散件-爽口紅茶＋鑽石x66＋金幣x10,000，每個遊戲帳號限購1次。 ※僅限使用iOS/Android的方式進行購買 | 超值購販售限時禮盒 | system | ? | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: No named suit; Story: No direct match; Draft: Keep: huma? |
| 6 | 活動五 | efc72977f924c4261232e538093e8231e2d760c1a31d01a7bf7611ecf9274035 | explicit_activity | 大喵限時任務 活動時間：06/16 維護後 - 06/27 23:59 活動內容：活動期間內，參與限時任務活動，完成階段的部件製作任務，可獲得階段獎勵。 本次任務套裝為【爍金秋意】，集齊共可獲得［公主級刷新券x2+星光幣x20+體力x60+金幣x20,000? | 大喵限時任務 | system | 爍金秋意 | ? | pending | Event: Correct/usable; Type: Incorrect: activity misclassified by maintenance wording; Suit: Correct names; Story: No direct match; Draft: Keep: huma? |
| 7 | 活動六 | 5f70f1e30a5a6770e4d2002377fb639eb0ce6851d2019dfe8b0b6e04598a6efe | explicit_activity | 星光幣雙倍 活動時間：06/17 05:00 - 06/19 23:59 活動內容：活動期間內進行搭配競技場比拚不論輸贏，皆可獲得星光幣雙倍獎勵！ 比拚勝利將獲得10個星光幣，比拚失敗將會獲得6個星光幣。 | 星光幣雙倍 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |
| 8 | 活動七 | 8f3ae08648279167fec0572c344b33d9b0a98ceebccd5e32e15e0c12dc4822b7 | explicit_activity | 公主級雙倍 活動時間：06/17 05:00 - 06/19 23:59 活動內容：活動期間內，指定的公主級關卡－服裝掉落率、通關後獲得金幣加倍。 通關後獲得金幣、服裝掉落率加倍：第2章、第9章、第二卷第6章。 服裝掉落率加倍：第5章、第12章、第17章。 ? | 公主級雙倍 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 618 / Notice 11:15310

- Date: 2022-05-19T00:00:00
- Title: 5/18 FB登入異常補償公告
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=15310](https://nu3.joybomb.com.tw/notice/noticecontent?N=11&K=15310)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 63ffb435b8f0a076bb0479051866d62f95a965b549c90182344350721a077f1f | whole_notice | 5/18 FB登入異常補償公告 5/18 FB登入異常補償公告 2022.05.19 16:30 親愛的搭配師您好， 針對5/18 18:30-5/19 04:30期間遊戲FB登入異常問題， 造成搭配師們不便及困擾我們深感抱歉。 在此補償「鑽石x180+體力? | 5/18 FB登入異常補償公告 | welfare | ? | ? | pending | Event: Not applicable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: system/community/maintenance |

### Raw 619 / Notice 1:15293

- Date: 2022-06-03T00:00:00
- Title: 暖暖慶端午獎勵活動
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15293](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15293)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 3f7c8eb17431867ee7c6c18f855877f9e182b75a8acf3b6e420804002694cf70 | whole_notice | 暖暖慶端午獎勵活動 暖暖慶端午獎勵活動 2022.06.03 12:00 | 暖暖慶端午獎勵活動 | other | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | d58f2803afc4159bb1670422dae8978c66327b4302c0b124c4c9468da9e61f12 | explicit_activity | 暖暖慶端午獎勵活動 活動時間：即日起～6/9(四) 23:59 活動內容：活動期間內前往官方粉絲專頁於活動貼文下方留言＠好友， 並留言分享你端午節想要一起在奇迹暖暖進行的活動： 範例：＠一位好友 端午節快樂！端午節一起在奇迹暖暖_______嘛～。 活動結束? | 暖暖慶端午獎勵活動 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 621 / Notice 1:15250

- Date: 2022-05-15T00:00:00
- Title: 主題商店 限時開啟
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15250](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15250)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | d417e86bc786e60418f6af4e74a8808716d2242e60ed2f58e5e13c8922201c23 | whole_notice | 主題商店 限時開啟 主題商店 限時開啟 2022.05.15 12:00 活動ㄧ、主題商店販售限時禮盒 活動時間：05/17 05:00 - 05/23 23:59 活動內容：活動期間內，主題商店限時販售以下禮盒—— 限時販售NT.33的［夏日祭典］禮盒， ? | 主題商店 限時開啟 | suit_event | 決勝時刻 | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: Correct names; Story: No direct match; Draft: Keep: human review needed |

### Raw 622 / Notice 1:15245

- Date: 2022-05-07T00:00:00
- Title: 五月芬芳登入送
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15245](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15245)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 7423a40280ed3910ffd5b4cd6ca50d360ea3bbc4a44d2771985259845f6dadec | whole_notice | 五月芬芳登入送 五月芬芳登入送 2022.05.07 12:00 活動ㄧ、五月芬芳登入送 活動時間：05/08 05:00 - 05/13 23:59 活動內容：活動期間內登入遊戲即可透過信箱信件領取散件-忘憂寄思+暄風凝暉+ 北堂芳草+鮮果樂園+水潤邂逅+? | 五月芬芳登入送 | event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

### Raw 643 / Notice 1:15465

- Date: 2022-07-29T00:00:00
- Title: 六週年紀念貼圖 集章活動
- URL: [https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15465](https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=15465)

| Sec | Heading | Hash | Split | Summary | Event candidate | Type | Suits | Story | Status | Human judgement |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | ? | 1a5bca746fddd9bf72fdbd2a7ad6db630387a0244115e371b2228a86c05a6d84 | whole_notice | 六週年紀念貼圖 集章活動 六週年紀念貼圖 集章活動 2022.07.29 12:00 | 六週年紀念貼圖 集章活動 | other | ? | ? | pending | Event: Not assessed: preamble; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Skip: preamble |
| 2 | 活動一 | 7932786c2bdac8c992304655ee4fdb72aac6f6841b1757e137708beddb7ef264 | explicit_activity | 6週年紀念貼圖 集章活動 活動時間：8/1(一) 12:00～8/21(日) 23:59 活動內容：為了慶祝奇迹暖暖6週年和大貼圖上市，官方粉絲專頁上舉辦了的集章活動， 活動共有三個階段，每階段活動將於週一公布於粉絲團， 參與每週活動，除了有機會可獲得免費的? | 6週年紀念貼圖 集章活動 | suit_event | ? | ? | pending | Event: Correct/usable; Type: Reasonable; Suit: No named suit; Story: No direct match; Draft: Keep: human review needed |

## Findings

### A. Splitter

- **Explicit headings are useful:** 18/50 posts split into multiple sections, producing 102 sections. Text order and hashes were stable for `???` style headings.
- **Missed split:** raw 606, 621, and 622 use the legacy `???` form, so multiple activities remain in one whole-notice section.
- **False split:** raw 232 has a `??` line in legal notes; it was treated as a category heading and its first line became an invalid event candidate.
- **Preambles:** the first section of 18 multi-section notices is shared title/preamble material and should not automatically become an importable activity draft.

### B. Parser

- The legacy source title is often `????`. Nineteen sections received this generic string directly, so it cannot be used as an event name.
- Raw 305 section 2 starts with `????`; this demonstrates that section first-line extraction is not always an event name.
- Fourteen explicit activity sections became `system` because their text includes maintenance wording. Raw 381, 451, 513, and 615 are real activity notices. This is the largest content-type error cluster.
- The current type set has no dedicated Recharge or Shop type. Recharge, store, and welfare material is therefore only approximated by event/suit_event/system/welfare/other.

### C. Suit Rules

- The sample produced 28 candidates. Names were mostly valid; raw 159 candidate `??` is a clear false positive.
- Confirmed misses: raw 119, raw 199 section 2, raw 224, and raw 383. Their relevant suit names use Chinese quotes, full-width square brackets, or ordinary suit prose rather than the current high-confidence `??` form.
- Generic random-suit text in Mystery Shop sections is not counted as a missed suit because it contains no stable suit name.

### D. Story Event Reference

- Direct matches: raw 224 contains `????`; raw 513 contains `????` in both preamble and activity text.
- No false positive was found. This establishes exact-text matching only; it does not prove that the reference covers every legacy story event.

## Scale Decision

### 10 to 100

**Recommended only in draft-only mode with an audit output.** Section identity, idempotency behavior, and the absence of Knowledge DB writes were verified by this sample. The next 100-post audit should measure the generic-title, `???`, maintenance-wording, and legacy-quote error rates.

### Directly to 575

**Do not promote 575 posts directly into the Knowledge DB.** Creating draft-only audit records is technically feasible, but these results are not ready for automatic knowledge import.

### Top Three Blockers Before Knowledge Creation

1. **Unstable event-name source:** `????`, preambles, and `????` are accepted as event names.
2. **Maintenance wording contaminates classification:** 14 obvious activity sections are labelled `system`.
3. **Legacy suit typography differs from the high-confidence rule:** Chinese quotes, full-width square brackets, and prose forms are missed.

### Must Fix vs Acceptable Needs Review

**Must fix before automatic Knowledge creation:** generic-title exclusion for event names, activity-versus-system priority, and conservative recognition of legacy named-suit formats.

**Acceptable as needs_review:** social giveaways, external promotions, Mystery Shop random-suit descriptions, non-suit multiplier events, system incidents, and maintenance notices.

## Constraints Confirmed

- No Parser, Splitter, Story Dictionary, Schema, Discord, Queue, or production SQLite change was made.
- No events, event_periods, suits, event_suits, cost_records, or announcement jobs were created.
- The only repository write in this task is this Markdown report. Reparse results existed only in a temporary SQLite copy.
