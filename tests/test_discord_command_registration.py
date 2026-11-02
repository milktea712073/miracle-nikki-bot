from bot.main import bot


def test_only_announcement_search_command_is_registered() -> None:
    command_names = {command.name for command in bot.tree.get_commands()}

    assert command_names == {"公告搜尋"}
    assert bot.get_command("latest") is None
