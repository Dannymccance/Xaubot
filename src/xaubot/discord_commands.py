"""Discord slash command service for one explicitly configured server/channel.

This optional service uses discord.py. It reads paper research output files only.
It cannot trade, edit configurations or access broker credentials.
"""
from __future__ import annotations

import os
from pathlib import Path

from .reporting import leaderboard_report, signals_report, status_report, strategies_report


def _snowflake(name: str) -> int:
    value = os.getenv(name, "").strip()
    if not value.isascii() or not value.isdecimal() or not (15 <= len(value) <= 24):
        raise RuntimeError(f"{name} must contain a valid Discord numeric ID")
    return int(value)


def main() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set DISCORD_BOT_TOKEN on the VPS before enabling Discord commands")
    guild_id = _snowflake("DISCORD_GUILD_ID")
    channel_id = _snowflake("DISCORD_CHANNEL_ID")
    try:
        import discord
        from discord import app_commands
    except ImportError:
        raise SystemExit("Missing discord.py; install Xaubot with the [discord] optional extra") from None

    data_dir = Path(os.getenv("XAUBOT_DATA_DIR", "data")).resolve()
    intents = discord.Intents.none()
    intents.guilds = True

    class ReadOnlyClient(discord.Client):
        def __init__(self):
            super().__init__(intents=intents)
            self.tree = app_commands.CommandTree(self)

        async def setup_hook(self):
            target = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=target)
            await self.tree.sync(guild=target)

    client = ReadOnlyClient()

    async def respond(interaction: discord.Interaction, text: str):
        # Read-only commands are restricted to one pre-authorised destination.
        if interaction.guild_id != guild_id or interaction.channel_id != channel_id:
            await interaction.response.send_message(
                "Xaubot commands are restricted to the configured research channel.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(text[:1900], ephemeral=True)

    @client.tree.command(name="status", description="Show current XAUUSD feed and paper engine status")
    async def status(interaction: discord.Interaction):
        await respond(interaction, status_report(data_dir))

    @client.tree.command(name="signals", description="Show most recent primary paper trade candidates")
    async def signals(interaction: discord.Interaction):
        await respond(interaction, signals_report(data_dir))

    @client.tree.command(name="leaderboard", description="Show qualified experimental paper strategy ranking")
    async def leaderboard(interaction: discord.Interaction):
        await respond(interaction, leaderboard_report(data_dir))

    @client.tree.command(name="strategies", description="Show Xaubot's strategy registry")
    async def strategies(interaction: discord.Interaction):
        await respond(interaction, strategies_report())

    # No message-content privileged intent, no text listener, no broker calls.
    client.run(token, log_handler=None)


if __name__ == "__main__":
    main()
