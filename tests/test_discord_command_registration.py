from bot.main import bot


def test_v2_does_not_register_knowledge_commands() -> None:
    command_names = {command.name for command in bot.tree.get_commands()}

    assert {"活動", "套裝", "審核列表", "審核", "編輯草稿"}.isdisjoint(command_names)
    assert bot.get_command("latest") is None
