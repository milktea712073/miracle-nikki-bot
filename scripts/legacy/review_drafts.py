"""給管理員使用的終端機草稿審核工具。"""

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from database.database import get_connection
from database.import_service import import_parse_draft
from database.review_repository import ReviewRepository
from database.database import init_database


STATUS_LABELS = {
    "pending": "待審核",
    "reviewed": "已審核",
    "approved": "匯入正式資料",
    "rejected": "已拒絕",
    "ignored": "已忽略",
}
MANSION_EVENT_TYPE = "\u5927\u95a3"


def get_draft_details(draft_id: int) -> dict[str, object]:
    """讀取僅供畫面顯示的 Parser 草稿資料。"""
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT title, event_name_candidate, period_type_candidate, "
            "start_at_candidate, end_at_candidate, parser_notes "
            "FROM parse_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"找不到草稿 {draft_id}。")
        suits = connection.execute(
            "SELECT suit_name_candidate FROM parse_draft_suits "
            "WHERE parse_draft_id = ? ORDER BY position",
            (draft_id,),
        ).fetchall()
        return {
            "title": row[0],
            "event_name_candidate": row[1],
            "period_type_candidate": row[2],
            "start_at_candidate": row[3],
            "end_at_candidate": row[4],
            "parser_notes": row[5],
            "parser_suits": [suit[0] for suit in suits],
        }
    finally:
        connection.close()


def display_parser_result(draft_id: int, details: dict[str, object]) -> None:
    """顯示 Parser 結果，不要求管理員逐項重新輸入。"""
    period_type = {"debut": "首次", "rerun": "復刻"}.get(
        details["period_type_candidate"], "未知"
    )
    print("\n" + "=" * 40)
    print(f"草稿 #{draft_id}")
    print(f"公告標題：{details['title'] or '未辨識'}")
    print(f"Parser 辨識活動：{details['event_name_candidate'] or '未辨識'}")
    print(f"活動類型：{period_type}")
    print(f"活動時間：{format_period(details['start_at_candidate'], details['end_at_candidate'])}")
    print("Parser 找到的套裝：")
    for suit in details["parser_suits"]:
        print(f"  ✓ {suit}")
    print("=" * 40)


def format_period(start_at: object, end_at: object) -> str:
    """把 ISO 期間轉成管理員易讀格式。"""
    if not start_at or not end_at:
        return "未辨識"
    return f"{str(start_at)[:10].replace('-', '/')} ～ {str(end_at)[:10].replace('-', '/') }"


def choose_option(title: str, options: list[tuple[int, str]], current: int | None) -> tuple[int | None, str | None]:
    """以繁中提示選取參考資料，Enter 保持既有值。"""
    print(f"\n{title}：")
    option_names = {option_id: name for option_id, name in options}
    for option_id, name in options:
        marker = "（目前）" if option_id == current else ""
        print(f"  {option_id}. {name}{marker}")
    while True:
        value = input("請輸入編號（直接 Enter 保持目前值）：").strip()
        if not value:
            return current, option_names.get(current)
        if value.isdigit() and int(value) in option_names:
            selected = int(value)
            return selected, option_names[selected]
        print("輸入無效，請輸入清單中的編號。")


def ask_yes_no(prompt: str) -> bool:
    """要求明確的 Y/N 回答。"""
    while True:
        value = input(f"{prompt}（Y/N）：").strip().lower()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no", ""}:
            return False
        print("請輸入 Y 或 N。")


def edit_suits(review: dict[str, object]) -> list[dict[str, object]]:
    """只有管理員主動選擇時才開啟的套裝編輯模式。"""
    suits = [dict(suit) for suit in review["suits"]]
    while True:
        print("\n套裝編輯模式：")
        for index, suit in enumerate(suits, 1):
            live2d = "，Live2D" if suit["is_live2d"] else ""
            cost = f"，花費：{suit['cost_text']}" if suit["cost_text"] else ""
            print(f"  {index}. {suit['suit_name']}{live2d}{cost}")
        print("1 新增  2 修改  3 刪除  4 排序  0 完成")
        action = input("請輸入編號（直接 Enter 保持目前值）：").strip()
        if action in {"", "0"}:
            return suits
        if action == "1":
            name = input("套裝名稱：").strip()
            if name:
                suits.append({"suit_name": name, "is_live2d": False, "cost_text": None, "notes": None})
        elif action in {"2", "3", "4"}:
            value = input("套裝編號：").strip()
            if not value.isdigit() or not 1 <= int(value) <= len(suits):
                print("輸入無效。")
                continue
            index = int(value) - 1
            if action == "3":
                suits.pop(index)
            elif action == "4":
                target = input("移動到第幾個位置：").strip()
                if target.isdigit() and 1 <= int(target) <= len(suits):
                    suits.insert(int(target) - 1, suits.pop(index))
            else:
                suit = suits[index]
                suit["suit_name"] = input(f"套裝名稱（目前：{suit['suit_name']}）：").strip() or suit["suit_name"]
                suit["is_live2d"] = ask_yes_no("是否為 Live2D 套裝")
                suit["cost_text"] = input(f"單套花費（目前：{suit['cost_text'] or '未填'}）：").strip() or None


def display_confirmation(review: dict[str, object], details: dict[str, object], event_type_name: str | None, acquisition_name: str | None) -> None:
    """顯示保存或匯入前的唯一確認畫面。"""
    print("\n" + "=" * 40)
    print(f"活動名稱：\n{review['confirmed_event_name'] or details['event_name_candidate'] or '未填'}")
    print(f"活動分類：\n{event_type_name or '未選擇'}")
    print(f"取得方式：\n{acquisition_name or '未選擇'}")
    print(f"活動總花費：\n{review['event_cost_text'] or '未填'}")
    print(f"活動時間：\n{format_period(details['start_at_candidate'], details['end_at_candidate'])}")
    print("套裝：")
    for suit in review["suits"]:
        print(f"✓ {suit['suit_name']}")
    print("=" * 40)
    print("1 保存待審核")
    print("2 保存已審核")
    print("3 匯入正式資料")
    print("4 已拒絕")
    print("5 已忽略")
    print("=" * 40)


def review_draft(repository: ReviewRepository, draft_id: int, advanced: bool) -> None:
    details = get_draft_details(draft_id)
    review = repository.get_or_create_review(draft_id)
    display_parser_result(draft_id, details)

    event_type_id, event_type_name = choose_option("活動分類", repository.get_reference_options("event_types"), review["event_type_id"])
    acquisition_id, acquisition_name = choose_option("取得方式", repository.get_reference_options("acquisition_methods"), review["acquisition_method_id"])
    event_cost = input(f"活動總花費（可留空，目前：{review['event_cost_text'] or '未填'}）：").strip()
    updates: dict[str, object] = {
        "event_type_id": event_type_id,
        "acquisition_method_id": acquisition_id,
        "event_cost_text": event_cost or review["event_cost_text"],
    }

    if event_type_name == MANSION_EVENT_TYPE:
        if ask_yes_no("是否有 Live2D"):
            updates["live2d_cost_text"] = input(f"Live2D 花費（可留空，目前：{review['live2d_cost_text'] or '未填'}）：").strip() or review["live2d_cost_text"]
        else:
            updates["live2d_cost_text"] = None

    if ask_yes_no("是否編輯單套花費或套裝資料"):
        repository.replace_review_suits(draft_id, edit_suits(review))
        review = repository.get_or_create_review(draft_id)

    if advanced:
        print(f"\nParser 備註：{details['parser_notes'] or '無'}")
        updates["confirmed_event_name"] = input(f"活動名稱（目前：{review['confirmed_event_name'] or '未填'}）：").strip() or review["confirmed_event_name"]
        updates["official_series"] = input(f"官方系列（可留空，目前：{review['official_series'] or '未填'}）：").strip() or None
        updates["review_notes"] = input(f"審核備註（可留空，目前：{review['review_notes'] or '未填'}）：").strip() or None

    repository.save_review(draft_id, **updates)
    review = repository.get_or_create_review(draft_id)
    display_confirmation(review, details, event_type_name, acquisition_name)
    choice = input("請輸入編號（直接 Enter 保持待審核）：").strip() or "1"
    statuses = {"1": "pending", "2": "reviewed", "3": "approved", "4": "rejected", "5": "ignored"}
    status = statuses.get(choice)
    if status is None:
        print("輸入無效，未變更狀態。")
        return
    if status == "approved":
        repository.validate_review_ready(draft_id)
    repository.update_draft_status(draft_id, status)
    if status == "approved":
        result = import_parse_draft(draft_id)
        print(f"已匯入正式資料：活動 #{result.event_id}，套裝 {len(result.suit_ids)} 套。")
    else:
        print(f"已保存：{STATUS_LABELS[status]}。")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DEPRECATED legacy terminal draft review and recovery tool"
    )
    parser.add_argument("--draft-id", type=int, help="直接開啟指定草稿")
    parser.add_argument("--advanced", action="store_true", help="顯示進階欄位")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    print(
        "DEPRECATED: daily Discord review is retired. "
        "Use activity and suit card management; this script is retained only for legacy manual recovery."
    )
    init_database()
    sys.stdout.reconfigure(encoding="utf-8")
    repository = ReviewRepository()
    draft_id = args.draft_id
    if draft_id is None:
        pending = repository.list_pending_reviews(20)
        if not pending:
            print("目前沒有待審核草稿。")
            return
        print("待審核草稿：")
        for draft in pending:
            print(f"  {draft['id']}. {draft['title'] or '未命名公告'}")
        value = input("請輸入草稿編號：").strip()
        if not value.isdigit():
            print("輸入無效。")
            return
        draft_id = int(value)
    review_draft(repository, draft_id, args.advanced)


if __name__ == "__main__":
    main()
