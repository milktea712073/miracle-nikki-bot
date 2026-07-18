# Announcement Resend Incident Report

> Investigation date: 2026-07-17  
> Scope: read-only inspection of `database/database.db`, existing source code, and existing local logs. No job, ledger, raw post, Queue state, Parser, schema, Discord, or Bot process was modified.

## Executive Summary

- **Resent announcement:** `🌊 7月社群活動 🌊 得獎名單公告`.
- **First delivery:** job **110**, raw post **102**, ledger announcement **20**, sent `2026-07-15T15:09:48.125448+00:00`.
- **Second delivery:** job **111**, raw post **678**, ledger announcement **21**, sent `2026-07-16T17:38:54.512017+00:00`.
- The two raw posts have different canonical pfbid URLs but **identical full content**, the same two stable Facebook media filenames, and both have `published_at = NULL`.
- The second job was newly inserted, not requeued. It was created at the same timestamp as raw post 678 (`2026-07-16T17:38:52.678789+00:00`).
- Root cause: the conservative Facebook alias merge required `official_post_verified` on both the incoming post and the existing raw row. Raw post 102 has `metadata_json = NULL`; the verified incoming post therefore did not merge. The Queue then saw a new canonical pfbid URL and correctly created a new job/ledger under its current URL-only identity.

## 1. Resent Announcement Identity and Timeline

| Delivery | Job | Raw post | Facebook source_post_id | Canonical URL | Job created | Sent | Ledger ID | Discord channel/message |
|---|---:|---:|---|---|---|---|---:|---|
| First | 110 | 102 | `pfbid02HP4BziD9vVME885n6c1HKLRCCU7whYXBVgNrDD78jnAra8A89peePrwPVuGSMUnal` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02HP4BziD9vVME885n6c1HKLRCCU7whYXBVgNrDD78jnAra8A89peePrwPVuGSMUnal](https://www.facebook.com/TwNikkiNikki/posts/pfbid02HP4BziD9vVME885n6c1HKLRCCU7whYXBVgNrDD78jnAra8A89peePrwPVuGSMUnal) | 2026-07-15T15:08:15.574737+00:00 | 2026-07-15T15:09:48.125448+00:00 | 20 | Not recorded by current schema or local logs |
| Second / resend | 111 | 678 | `pfbid0DqR15Yao5F8T6UbVbz8AuUeVsZPppZ9uNuxzpLiMSAsZLfk6xMU9ToQz8s3DPN72l` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0DqR15Yao5F8T6UbVbz8AuUeVsZPppZ9uNuxzpLiMSAsZLfk6xMU9ToQz8s3DPN72l](https://www.facebook.com/TwNikkiNikki/posts/pfbid0DqR15Yao5F8T6UbVbz8AuUeVsZPppZ9uNuxzpLiMSAsZLfk6xMU9ToQz8s3DPN72l) | 2026-07-16T17:38:52.678789+00:00 | 2026-07-16T17:38:54.512017+00:00 | 21 | Not recorded by current schema or local logs |

Both records have two image filenames in the same order: `747127178_1019137040748634_3350597006999456569_n.png` and `748480517_1437381588414800_112428251955175556_n.png`. The CDN query strings differ, but filenames match. Neither raw post has an alias row.

### What is and is not recorded

- `announcements` records `id`, `publish_time`, `content`, and `post_url` only.
- `announcement_jobs` records state and timestamps only. It has no Discord channel or message ID column.
- No `announcement_deliveries` table exists, and the inspected local logs do not contain this 2026-07-15/16 delivery pair. Therefore the two Discord message IDs and channel IDs cannot be recovered from the current local data.

## 2. Recent 20 Announcement Jobs

| Job | Status | Source | Raw | Source post ID | URL | Created | Updated | Sent | Attempts | Error | Ledger ID | Title / first line | Discord delivery |
|---:|---|---|---:|---|---|---|---|---|---:|---|---|---|---|
| 111 | sent | facebook | 678 | `pfbid0DqR15Yao5F8T6UbVbz8AuUeVsZPppZ9uNuxzpLiMSAsZLfk6xMU9ToQz8s3DPN72l` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0DqR15Yao5F8T6UbVbz8AuUeVsZPppZ9uNuxzpLiMSAsZLfk6xMU9ToQz8s3DPN72l](https://www.facebook.com/TwNikkiNikki/posts/pfbid0DqR15Yao5F8T6UbVbz8AuUeVsZPppZ9uNuxzpLiMSAsZLfk6xMU9ToQz8s3DPN72l) | 2026-07-16T17:38:52.678789+00:00 | 2026-07-16T17:38:54.512017+00:00 | 2026-07-16T17:38:54.512017+00:00 | 1 | ? | 21 | 🌊 7月社群活動 🌊 得獎名單公告 | Not stored |
| 110 | sent | facebook | 102 | `pfbid02HP4BziD9vVME885n6c1HKLRCCU7whYXBVgNrDD78jnAra8A89peePrwPVuGSMUnal` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02HP4BziD9vVME885n6c1HKLRCCU7whYXBVgNrDD78jnAra8A89peePrwPVuGSMUnal](https://www.facebook.com/TwNikkiNikki/posts/pfbid02HP4BziD9vVME885n6c1HKLRCCU7whYXBVgNrDD78jnAra8A89peePrwPVuGSMUnal) | 2026-07-15T15:08:15.574737+00:00 | 2026-07-15T15:09:48.125448+00:00 | 2026-07-15T15:09:48.125448+00:00 | 1 | ? | 20 | 🌊 7月社群活動 🌊 得獎名單公告 | Not stored |
| 11 | sent | facebook | 2 | `pfbid0dPQuTaFRm9zzfaK1ZV41ntP5SbMz1KLiS13pTwLDXQgVcMDMVytmjYr4khLjewPql` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0dPQuTaFRm9zzfaK1ZV41ntP5SbMz1KLiS13pTwLDXQgVcMDMVytmjYr4khLjewPql](https://www.facebook.com/TwNikkiNikki/posts/pfbid0dPQuTaFRm9zzfaK1ZV41ntP5SbMz1KLiS13pTwLDXQgVcMDMVytmjYr4khLjewPql) | 2026-07-14T08:06:15.554146+00:00 | 2026-07-15T06:15:21.709376+00:00 | 2026-07-15T06:15:21.709376+00:00 | 1 | ? | 10 | 【預告】歲月流金 曼影風尚🌇 | Not stored |
| 69 | sent | facebook | 10 | `pfbid0uWUD2pHnTvCsBhgzAXdu2MAoyzMqfo55oZUQ9N5u8vzj25seemRAaCNy17nY1gHcl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02xsxPeqeQVXrNYcHA1uRfdMgRc8PknEbgz4GTsvMr1UmBHAYmkLF1gAvUNpYtVVTbl](https://www.facebook.com/TwNikkiNikki/posts/pfbid02xsxPeqeQVXrNYcHA1uRfdMgRc8PknEbgz4GTsvMr1UmBHAYmkLF1gAvUNpYtVVTbl) | 2026-07-15T05:33:10.468686+00:00 | 2026-07-15T06:12:19.582405+00:00 | 2026-07-15T06:12:19.582405+00:00 | 1 | ? | 19 | 【預告】繁星夜話 星輝浮夢🌃 | Not stored |
| 109 | skipped | facebook | 100 | `pfbid0aF2s3b814n8ZYQMVxx69rZcb8USEEjeBYcqE4oLwFzTqYLLMwcv6rpAVKpyyH6q2l` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0aF2s3b814n8ZYQMVxx69rZcb8USEEjeBYcqE4oLwFzTqYLLMwcv6rpAVKpyyH6q2l](https://www.facebook.com/TwNikkiNikki/posts/pfbid0aF2s3b814n8ZYQMVxx69rZcb8USEEjeBYcqE4oLwFzTqYLLMwcv6rpAVKpyyH6q2l) | 2026-07-15T05:33:10.815602+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【預告】 循光覓影 活動套裝——【葳蕤遺篇】海報公開！ | Not stored |
| 108 | skipped | facebook | 99 | `pfbid02S37widTC4CySaFHanDxb9oq8jkZCfUBQfvcsyLjifuWcjg2rds3dtR3jEY1XCrnl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02S37widTC4CySaFHanDxb9oq8jkZCfUBQfvcsyLjifuWcjg2rds3dtR3jEY1XCrnl](https://www.facebook.com/TwNikkiNikki/posts/pfbid02S37widTC4CySaFHanDxb9oq8jkZCfUBQfvcsyLjifuWcjg2rds3dtR3jEY1XCrnl) | 2026-07-15T05:33:10.805602+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【預告】 循光覓影 超稀有互動套裝——【縈香蝶影】海報公開！ | Not stored |
| 107 | skipped | facebook | 98 | `pfbid0AB7J366ieJZQH3uALtRjtGsagifaw2EgmdYkdYH4tNratmRn7VJXiNHJr2ZSdwVUl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0AB7J366ieJZQH3uALtRjtGsagifaw2EgmdYkdYH4tNratmRn7VJXiNHJr2ZSdwVUl](https://www.facebook.com/TwNikkiNikki/posts/pfbid0AB7J366ieJZQH3uALtRjtGsagifaw2EgmdYkdYH4tNratmRn7VJXiNHJr2ZSdwVUl) | 2026-07-15T05:33:10.796603+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【預告】循光覓影 活動玩法公開！ | Not stored |
| 106 | skipped | facebook | 97 | `pfbid02wReQ8NzPnkPDBPcmNcVcXJhMJ7hGc8BfZqWs8z1CM3SCU2aAisiFbSJj2Q7L93nJl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02wReQ8NzPnkPDBPcmNcVcXJhMJ7hGc8BfZqWs8z1CM3SCU2aAisiFbSJj2Q7L93nJl](https://www.facebook.com/TwNikkiNikki/posts/pfbid02wReQ8NzPnkPDBPcmNcVcXJhMJ7hGc8BfZqWs8z1CM3SCU2aAisiFbSJj2Q7L93nJl) | 2026-07-15T05:33:10.788205+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【預告】循光覓影 璃夢印象 活動即將開啟！ | Not stored |
| 105 | skipped | facebook | 46 | `pfbid02yCdVF2RfZeMSwzHjTfxG3x6LujDR5Hmmhzsvyx4H5QSZvpnTpxMDvBn1PvKW8T7Sl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0uB2mmDE6thYXruN48g9yRgzXMu3fW6z4gtRxaWhYCCrqXMNtyDxqSzuqtVPkUHHyl](https://www.facebook.com/TwNikkiNikki/posts/pfbid0uB2mmDE6thYXruN48g9yRgzXMu3fW6z4gtRxaWhYCCrqXMNtyDxqSzuqtVPkUHHyl) | 2026-07-15T05:33:10.781300+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【停機維護公告】 | Not stored |
| 104 | skipped | facebook | 95 | `pfbid02JdF3ACoytz5q2kPpawbKMsRyKC9XPP1tQ4CU5AqkC8Js8ZapyKiBRQDmctFxCwFol` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02JdF3ACoytz5q2kPpawbKMsRyKC9XPP1tQ4CU5AqkC8Js8ZapyKiBRQDmctFxCwFol](https://www.facebook.com/TwNikkiNikki/posts/pfbid02JdF3ACoytz5q2kPpawbKMsRyKC9XPP1tQ4CU5AqkC8Js8ZapyKiBRQDmctFxCwFol) | 2026-07-15T05:33:10.772295+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【預告】奇淵之嶼 心願餽贈💌 | Not stored |
| 103 | skipped | facebook | 44 | `pfbid02iJ1jaWBwfPKTVDphNrpQSike9zTrmvhaQYwkJVNyTvtUZjyM8qxEzCkEBBu1aEZvl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0eGR26gzNzUCYQcUcHYeGWFxuccDswTiwjHELMhjQqp2jFtFF4xZ6jHYLS6UA4gbEl](https://www.facebook.com/TwNikkiNikki/posts/pfbid0eGR26gzNzUCYQcUcHYeGWFxuccDswTiwjHELMhjQqp2jFtFF4xZ6jHYLS6UA4gbEl) | 2026-07-15T05:33:10.764238+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【福利】勞動節 登入送🎁 | Not stored |
| 102 | skipped | facebook | 93 | `pfbid0Eidgk8GtoWWuYAi5hkdE7BjFYVk7ppQty1C7xBvgdzt8YMC9tS9bS963GVU8A1wil` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0Eidgk8GtoWWuYAi5hkdE7BjFYVk7ppQty1C7xBvgdzt8YMC9tS9bS963GVU8A1wil](https://www.facebook.com/TwNikkiNikki/posts/pfbid0Eidgk8GtoWWuYAi5hkdE7BjFYVk7ppQty1C7xBvgdzt8YMC9tS9bS963GVU8A1wil) | 2026-07-15T05:33:10.753367+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【預告】全新凝砂套裝 聯盟協力收集⚔️ | Not stored |
| 101 | skipped | facebook | 42 | `pfbid05fmZYsNwDforUMkagsdcMFpZ1UEj5AyYWh5PpZUqJ5rHcriniBkrY3tyTYWJh1ril` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0293FkAtjZF8sQXWMrXrKUbEXZHqGSr2b2GbehEj8Zga3hF9pdBqjU7kMyue6wJ4Val](https://www.facebook.com/TwNikkiNikki/posts/pfbid0293FkAtjZF8sQXWMrXrKUbEXZHqGSr2b2GbehEj8Zga3hF9pdBqjU7kMyue6wJ4Val) | 2026-07-15T05:33:10.741642+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【開機公告】 | Not stored |
| 100 | skipped | facebook | 41 | `pfbid0WMJ3vCoeSwshiuLPmMBhP4zv7XC3YxuX7VoiHi43LGK2WGqtx1dwWKXsHaoZSS6Gl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02ZinEYEAGUXYzz1cNaqQhQeXnRBWDzuMtUakeUT5aNGBFym48ssbj13XaTKypqHJNl](https://www.facebook.com/TwNikkiNikki/posts/pfbid02ZinEYEAGUXYzz1cNaqQhQeXnRBWDzuMtUakeUT5aNGBFym48ssbj13XaTKypqHJNl) | 2026-07-15T05:33:10.733647+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【奇迹搭配室】循光覓影📰 | Not stored |
| 99 | skipped | facebook | 40 | `pfbid0Jnk9VpjSFn3v1zkYtZquDZ3dbQtirXqf7TpWsLi7otXEAS5zUendPRyoSnwDFroUl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02NAEL7r64HVCQnVPTPboMHMhyqUW9iTSLZcfPrPpsARD7wG433qFGYLQyrwSZfbiol](https://www.facebook.com/TwNikkiNikki/posts/pfbid02NAEL7r64HVCQnVPTPboMHMhyqUW9iTSLZcfPrPpsARD7wG433qFGYLQyrwSZfbiol) | 2026-07-15T05:33:10.722981+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【福利】遠方航線 限時簽到送🎁 | Not stored |
| 98 | skipped | facebook | 89 | `pfbid0BbnFPGo1adPBhc5nEmHYe2k2MfrooFDCtJn579K29sHgLmEiUH3LLDpUgKdXPaUvl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid0BbnFPGo1adPBhc5nEmHYe2k2MfrooFDCtJn579K29sHgLmEiUH3LLDpUgKdXPaUvl](https://www.facebook.com/TwNikkiNikki/posts/pfbid0BbnFPGo1adPBhc5nEmHYe2k2MfrooFDCtJn579K29sHgLmEiUH3LLDpUgKdXPaUvl) | 2026-07-15T05:33:10.715788+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【奇迹桌布】五月桌布套組釋出⭐ | Not stored |
| 97 | skipped | facebook | 88 | `pfbid02CpL5CyTFsqga2xgFDJyZyXMxuBzZob1oiVSHKErrPoE6erSST25XSEx8UgWasaTFl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02CpL5CyTFsqga2xgFDJyZyXMxuBzZob1oiVSHKErrPoE6erSST25XSEx8UgWasaTFl](https://www.facebook.com/TwNikkiNikki/posts/pfbid02CpL5CyTFsqga2xgFDJyZyXMxuBzZob1oiVSHKErrPoE6erSST25XSEx8UgWasaTFl) | 2026-07-15T05:33:10.704515+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【福利】母親節 登入送🎁 | Not stored |
| 96 | skipped | facebook | 87 | `pfbid02BKj65Vb5X6RpHKAvzSdfogL65SZ7pwqWvb3XKqWfvoZSK12ysSSM4ym1YRfsJVmYl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02BKj65Vb5X6RpHKAvzSdfogL65SZ7pwqWvb3XKqWfvoZSK12ysSSM4ym1YRfsJVmYl](https://www.facebook.com/TwNikkiNikki/posts/pfbid02BKj65Vb5X6RpHKAvzSdfogL65SZ7pwqWvb3XKqWfvoZSK12ysSSM4ym1YRfsJVmYl) | 2026-07-15T05:33:10.694567+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【復刻】沉落之海 限時復開 | Not stored |
| 95 | skipped | facebook | 36 | `pfbid0DFEKxQS2ygoHrBzzLSQWraLj9LBcmFLU1bJgxWNrHg941UtBKQSZPF6Y8QZTzrnul` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02H6g395MrpxM4gtZAJCQvuQwqeGVQHsG5es8VNsnifAHrqp7wtuDKzwN78rPxp5EUl](https://www.facebook.com/TwNikkiNikki/posts/pfbid02H6g395MrpxM4gtZAJCQvuQwqeGVQHsG5es8VNsnifAHrqp7wtuDKzwN78rPxp5EUl) | 2026-07-15T05:33:10.688519+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【預告】願之庭 秘海水族館 | Not stored |
| 94 | skipped | facebook | 35 | `pfbid0veYR4fYXy8zDM4rKmXePBtA1edzB2PQZ89H2yCha762w5g1sazsDmTUXvtqh65Zvl` | [https://www.facebook.com/TwNikkiNikki/posts/pfbid02zVz8FLUMpVG6TRc7tSMBGacqHK8kQk2sNswKRLrgcvPCiQG65QkDSXkMX1EoEvyhl](https://www.facebook.com/TwNikkiNikki/posts/pfbid02zVz8FLUMpVG6TRc7tSMBGacqHK8kQk2sNswKRLrgcvPCiQG65QkDSXkMX1EoEvyhl) | 2026-07-15T05:33:10.679083+00:00 | 2026-07-15T06:09:23.755041+00:00 | ? | 0 | ? | ? | 【預告】魔力番茄 園間童話🍅 | Not stored |

## 3. Causal Chain and SQL Evidence

1. The second crawler result had a new pfbid. `RawPostRepository.save_raw_post()` first looked up the new `source_post_id`, then aliases, and found neither.
2. It searched existing Facebook rows with exact same content. Raw post 102 was found, but `_is_conservative_facebook_duplicate()` rejected it because `metadata_json` on raw 102 is NULL; the method requires verified metadata on the existing row as well as the incoming row. See [raw_post_repository.py](C:/Users/User/Project/miracle-nikki-bot/database/raw_post_repository.py:193) and [raw_post_repository.py](C:/Users/User/Project/miracle-nikki-bot/database/raw_post_repository.py:231).
3. The fallback inserted raw post 678, then invoked `create_pending_for_new_raw_post()` for Facebook inserts. See [raw_post_repository.py](C:/Users/User/Project/miracle-nikki-bot/database/raw_post_repository.py:314).
4. The Queue first checks `announcement_jobs.post_url = canonical_url`, then checks `announcements.post_url` by the same canonical URL. Both existing records used raw 102's different pfbid URL, so neither query matched raw 678's URL. The new job was therefore inserted as `pending`. See [announcement_job_repository.py](C:/Users/User/Project/miracle-nikki-bot/database/announcement_job_repository.py:76).
5. The worker claimed the pending job and `mark_sent()` inserted a second ledger row because its URL did not equal the prior ledger URL. See [announcement_job_repository.py](C:/Users/User/Project/miracle-nikki-bot/database/announcement_job_repository.py:221) and [announcement_job_repository.py](C:/Users/User/Project/miracle-nikki-bot/database/announcement_job_repository.py:286).

### Why the sent ledger did not prevent it

The ledger did not lose or overwrite its previous record. It contains two rows, each keyed by a different canonical pfbid URL. Current canonicalization removes Facebook query parameters but cannot prove that two different `/posts/pfbid...` path values represent one underlying Facebook post. Thus the ledger behaved correctly for its current identity, while that identity was too weak for this pfbid-alias case.

## 4. Recent Operations: Code-path Review

| Operation | Can create pending job? | Evidence |
|---|---|---|
| `scripts/data/import_joybomb_archive.py` | No | It calls `save_raw_post(..., enqueue_announcement=False)` for JoyBomb records. [source](C:/Users/User/Project/miracle-nikki-bot/scripts/data/import_joybomb_archive.py:237) |
| `parse_raw_posts.py --source joybomb_archive --draft-only` | No job creation / no auto import | The auto-import call is guarded by `not draft_only` and JoyBomb source. [source](C:/Users/User/Project/miracle-nikki-bot/scripts/data/parse_raw_posts.py:90) |
| Parse-draft schema initialization | Does not enqueue | It may run `init_database()` and queue table DDL/migration, but the shown initialization sequence does not call `create_pending_for_new_raw_post()`. [source](C:/Users/User/Project/miracle-nikki-bot/database/database.py:708) |
| Facebook alias repair | Does not insert a job | It only retargets `announcement_jobs.raw_post_id` during an explicit merge; it does not create queue rows. |
| Normal Facebook poll/new raw insert | Yes | Facebook insert path calls `create_pending_for_new_raw_post()` with the poller's enqueue setting. [source](C:/Users/User/Project/miracle-nikki-bot/database/raw_post_repository.py:347) |

The evidence points to the normal Facebook insert path, not to JoyBomb import, draft-only parsing, draft migration, or database initialization as the trigger.

## 5. Identity Cross-check

| Property | Raw 102 | Raw 678 | Result |
|---|---|---|---|
| source_post_id | `pfbid02HP4BziD9vVME885n6c1HKLRCCU7whYXBVgNrDD78jnAra8A89peePrwPVuGSMUnal` | `pfbid0DqR15Yao5F8T6UbVbz8AuUeVsZPppZ9uNuxzpLiMSAsZLfk6xMU9ToQz8s3DPN72l` | Different pfbid aliases |
| canonical URL | [first](https://www.facebook.com/TwNikkiNikki/posts/pfbid02HP4BziD9vVME885n6c1HKLRCCU7whYXBVgNrDD78jnAra8A89peePrwPVuGSMUnal) | [second](https://www.facebook.com/TwNikkiNikki/posts/pfbid0DqR15Yao5F8T6UbVbz8AuUeVsZPppZ9uNuxzpLiMSAsZLfk6xMU9ToQz8s3DPN72l) | Different path identity |
| published_at | ? | ? | Both NULL; passes time-equality condition |
| full content | SHA-256 `134b1f660189bbbe59267baed8795120d845ef08d52bc5d14c7b960497755022` | Same exact SHA-256 | Exact match |
| stable image filename set | 2 files | Same 2 files | Exact match |
| existing metadata | ? | {"official_post_verified": true} | Existing row fails verified-metadata gate |
| aliases | none | none | Alias layer did not link either pfbid |

## 6. Impact Scope at Investigation Time

- Pending jobs: **0**.
- Failed jobs: **0**; sending jobs: **0**.
- Pending jobs with an existing sent ledger: **0**.
- Pending jobs with non-null `published_at` older than seven days: **0**. This does not count NULL publication times.
- Duplicate `announcement_jobs.post_url`: **0**; the unique constraint is intact.
- Sent jobs: **13**; skipped jobs: **89**; ledger rows: **13**.
- Ledger rows without a corresponding sent job: **0**.
- Exact content + stable-media + publication-time duplicate Facebook groups: **1**, consisting only of raw posts [102, 678].

There are no currently pending jobs to list. The immediate queue is empty, but the same pfbid-alias weakness remains and can create another pending job on a future poll.

## 7. Recommended Remediation (Not Applied)

1. **First fix:** strengthen the Facebook duplicate/alias path for legacy raw rows whose content, stable media filename set, and `published_at` exactly match a newly verified official post. The historical row lacking `official_post_verified` should not by itself defeat otherwise complete duplicate evidence; retain a log/audit trail for this exceptional legacy case.
2. Before enqueueing a newly inserted Facebook raw post, perform a stable source-identity/alias lookup that can recognize a verified exact duplicate and bind the new pfbid to the existing raw row instead of creating a second job.
3. Keep URL canonicalization for ordinary URLs, but do not rely on pfbid-path equality as the sole delivery identity when Facebook itself exposes aliases.
4. Add delivery records or at least store channel/message IDs per successful channel delivery. This is needed for future incident reconstruction and partial multi-channel delivery handling.
5. Add a pre-send guard that detects an exact trusted duplicate of any already-sent Facebook raw post even when its canonical pfbid URL differs. It must be conservative and should never merge merely similar text.

## 8. Immediate Operational Recommendation

- **Pause the Bot or at minimum disable the Facebook poller before the next poll.** There are no pending jobs now, but the next unseen pfbid alias can recreate this failure and send again.
- Do not run requeue, rebuild, reset, alias repair, or JoyBomb bulk parsing until the duplicate identity/queue guard is fixed and regression-tested.
- Preserve the two ledger entries for audit. Do not delete the already-sent Discord messages as part of the incident response unless an operator separately decides so.

## 9. Required Regression Tests

1. Existing legacy Facebook raw row with NULL metadata + new verified pfbid, exact content, exact stable media filenames, and equal/NULL `published_at` ? one raw post, one alias, no new job.
2. Same pfbid-alias pair where an existing sent ledger uses the first URL ? crawler input for the second URL must not create pending or send again.
3. Same content but different stable image filename set or different non-null `published_at` ? no automatic merge and no unsafe ledger suppression.
4. Alias repair retargets `raw_post_id` without changing a sent/skipped job into pending.
5. Successful delivery records per-channel message ID, and a duplicate guard is exercised before Discord send.
