from bot.main import bot


def test_only_current_knowledge_commands_are_registered() -> None:
    command_names = {command.name for command in bot.tree.get_commands()}

    assert {"活動", "套裝"} <= command_names
    assert {"審核列表", "審核", "編輯草稿"}.isdisjoint(command_names)
    assert bot.get_command("latest") is None
