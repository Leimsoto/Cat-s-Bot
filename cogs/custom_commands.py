"""
cogs/custom_commands.py
───────────────────────
Sistema de Custom Commands — comandos personalizados con respuesta tipo embed
y control de permisos.

  • Prefijo fijo "!" (no se puede cambiar — el dashboard expone el resto).
  • Cada comando puede tener:
      - response_data: JSON del MessageEditor (content + embed).
      - actions/content (legacy): fallback si no hay response_data.
      - permission_data: {everyone:bool, role_ids:[…]}.
      - delete_invocation: si 1, el bot borra el mensaje que invocó el comando.
  • Variables soportadas en title/description/footer/content:
      {user} {username} {display_name} {id} {server} {channel}
      {args} {1} {2} … {N}

Comandos slash (solo inspección — todo se gestiona en el dashboard):
  /customcommand list
  /customcommand info <name>
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs._message_payload import render_message_payload

logger = logging.getLogger("CustomCommands")

# Prefijo fijo por requisito de producto.
PREFIX = "!"


def _can_manage(member: discord.Member) -> bool:
    return (
        member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
    )


def _user_can_use(member: discord.Member, permission_data: Optional[str]) -> bool:
    """Devuelve True si el miembro puede ejecutar el comando.

    Reglas:
      • permission_data vacío o everyone=true → cualquiera.
      • role_ids no vacío y el miembro NO tiene ninguno → False.
      • Administradores siempre pueden.
    """
    if member.guild_permissions.administrator:
        return True
    if not permission_data:
        return True
    try:
        data = json.loads(permission_data) if isinstance(permission_data, str) else permission_data
    except (json.JSONDecodeError, TypeError):
        return True
    if not isinstance(data, dict):
        return True
    if data.get("everyone", True):
        return True
    allowed = set(data.get("role_ids") or [])
    if not allowed:
        return True
    return any(r.id in allowed for r in member.roles)


async def _cc_autocomplete(interaction: discord.Interaction, current: str):
    cmds = interaction.client.db.get_custom_commands(interaction.guild_id)
    return [
        app_commands.Choice(name=c["name"], value=c["name"])
        for c in cmds if current.lower() in c["name"]
    ][:25]


class CustomCommands(commands.Cog):
    """Comandos personalizados del servidor con respuesta embed y permisos."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    cc_group = app_commands.Group(
        name="customcommand",
        description="Inspecciona los comandos personalizados (gestiona desde el dashboard)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not message.content.startswith(PREFIX):
            return

        after_prefix = message.content[len(PREFIX):].strip()
        if not after_prefix:
            return

        parts = after_prefix.split()
        cmd_name = parts[0].lower()
        args = parts[1:]

        command = self.db.get_custom_command(message.guild.id, cmd_name)
        if not command or not command.get("enabled", 1):
            return

        if not _user_can_use(message.author, command.get("permission_data")):
            return

        self.db.increment_cc_uses(message.guild.id, cmd_name)

        # Auto-delete del mensaje de invocación si está activado.
        if command.get("delete_invocation"):
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

        variables = {
            "user": message.author.mention,
            "username": str(message.author),
            "display_name": message.author.display_name,
            "id": str(message.author.id),
            "server": message.guild.name,
            "channel": message.channel.mention,
            "args": " ".join(args),
        }
        for i, arg in enumerate(args, 1):
            variables[str(i)] = arg

        response_data = command.get("response_data")
        if response_data:
            try:
                payload = render_message_payload(
                    response_data, variables, member=message.author,
                )
                await message.channel.send(
                    content=payload["content"],
                    embed=payload["embed"],
                )
                return
            except Exception as exc:
                logger.warning("Error renderizando response_data: %s", exc)

        # Fallback legacy: actions JSON.
        actions = self._parse_actions(command.get("actions"))
        for action in actions:
            if action.get("type") == "send_message":
                content = action.get("content", "")
                for k, v in variables.items():
                    content = content.replace("{" + k + "}", str(v))
                try:
                    await message.channel.send(content)
                except discord.HTTPException as exc:
                    logger.warning("Error enviando custom command: %s", exc)
                break

    def _parse_actions(self, raw) -> List[Dict[str, Any]]:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @cc_group.command(name="list", description="Lista todos los comandos personalizados del servidor")
    async def cc_list(self, interaction: discord.Interaction):
        cmds = self.db.get_custom_commands(interaction.guild_id)
        if not cmds:
            return await interaction.response.send_message(
                f"📭 Este servidor no tiene comandos personalizados.\n"
                f"Configura desde el dashboard. Prefijo: `{PREFIX}`",
                ephemeral=True,
            )

        embed = discord.Embed(
            title=f"⚙️ Comandos personalizados — {interaction.guild.name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        lines = []
        for cmd in cmds[:25]:
            status = "✅" if cmd.get("enabled", 1) else "❌"
            lines.append(f"{status} `{PREFIX}{cmd['name']}` — {cmd.get('uses', 0)} uso(s)")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"{len(cmds)} comandos · prefijo {PREFIX} · edita en dashboard")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @cc_group.command(name="info", description="Muestra información detallada de un comando")
    @app_commands.describe(name="Nombre del comando")
    @app_commands.autocomplete(name=_cc_autocomplete)
    async def cc_info(self, interaction: discord.Interaction, name: str):
        name = name.strip().lower()
        cmd = self.db.get_custom_command(interaction.guild_id, name)
        if not cmd:
            return await interaction.response.send_message(
                f"❌ No existe ningún comando llamado **{name}**.", ephemeral=True,
            )

        creator = interaction.guild.get_member(int(cmd["creator_id"]))
        creator_text = creator.mention if creator else f"ID: {cmd['creator_id']}"
        embed = discord.Embed(
            title=f"⚙️ {PREFIX}{cmd['name']}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Creador", value=creator_text, inline=True)
        embed.add_field(name="Usos", value=str(cmd.get("uses", 0)), inline=True)
        embed.add_field(
            name="Auto-borra invocación",
            value="✅" if cmd.get("delete_invocation") else "❌",
            inline=True,
        )

        # Resumen permisos
        perm_data = cmd.get("permission_data")
        perm_text = "@everyone"
        if perm_data:
            try:
                pd = json.loads(perm_data) if isinstance(perm_data, str) else perm_data
                if not pd.get("everyone", True):
                    roles = pd.get("role_ids") or []
                    perm_text = ", ".join(f"<@&{rid}>" for rid in roles) or "@everyone"
            except (json.JSONDecodeError, TypeError):
                pass
        embed.add_field(name="Permisos", value=perm_text, inline=False)

        if cmd.get("response_data"):
            try:
                rd = json.loads(cmd["response_data"]) if isinstance(cmd["response_data"], str) else cmd["response_data"]
                preview = rd.get("content") or (rd.get("embed") or {}).get("description", "(embed)")
                embed.add_field(name="Respuesta", value=str(preview)[:500], inline=False)
            except (json.JSONDecodeError, TypeError):
                pass

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomCommands(bot))
