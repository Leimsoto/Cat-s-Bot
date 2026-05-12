"""
cogs/custom_commands.py
───────────────────────
Sistema de Custom Commands — comandos personalizados con acciones.

Comandos slash:
  /customcommand create <name> <content>        — Crear comando simple
  /customcommand delete <name>                  — Eliminar comando
  /customcommand list                            — Listar comandos
  /customcommand info <name>                     — Información del comando
  /customcommand variable get <key>              — Obtener variable
  /customcommand variable set <key> <value>      — Establecer variable

Triggers por prefijo (por defecto "!").
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "!"
MAX_COMMANDS = 100


# ── Helpers ───────────────────────────────────────────────────────────────────

def _can_manage(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild


async def _cc_autocomplete(interaction: discord.Interaction, current: str):
    cmds = interaction.client.db.get_custom_commands(interaction.guild_id)
    return [
        app_commands.Choice(name=c["name"], value=c["name"])
        for c in cmds if current.lower() in c["name"]
    ][:25]


# ── Cog ───────────────────────────────────────────────────────────────────────

class CustomCommands(commands.Cog):
    """Comandos personalizados del servidor con acciones configurables."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    cc_group = app_commands.Group(
        name="customcommand",
        description="Gestiona los comandos personalizados del servidor",
    )

    # ── Listeners ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        prefix = await self._get_prefix(guild_id)

        if not message.content.startswith(prefix):
            return

        after_prefix = message.content[len(prefix):].strip()
        if not after_prefix:
            return

        parts = after_prefix.split()
        cmd_name = parts[0].lower()

        command = self.db.get_custom_command(guild_id, cmd_name)
        if not command or not command["enabled"]:
            return

        self.db.increment_cc_uses(guild_id, cmd_name)

        actions = self._parse_actions(command["actions"])
        if not actions:
            return

        args = parts[1:] if len(parts) > 1 else []
        await self._execute_actions(
            message.channel, actions,
            author=message.author,
            guild=message.guild,
            args=args,
        )

    # ── Internals ──────────────────────────────────────────────────────────

    async def _get_prefix(self, guild_id: int) -> str:
        raw = self.db.get_cc_variable(guild_id, "cc_prefix")
        return raw or DEFAULT_PREFIX

    def _parse_actions(self, raw: str) -> List[Dict[str, Any]]:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            logger.warning("Error parseando actions JSON")
            return []

    async def _execute_actions(
        self,
        channel: discord.TextChannel,
        actions: List[Dict[str, Any]],
        **ctx: Any,
    ) -> None:
        author: discord.Member = ctx.get("author")
        args: List[str] = ctx.get("args", [])

        for action in actions:
            action_type = action.get("type", "")
            if action_type == "send_message":
                content = action.get("content", "")
                content = self._format_content(content, author, args)
                try:
                    await channel.send(content)
                except discord.Forbidden:
                    logger.warning("Sin permisos para enviar mensaje en %s", channel)
                except discord.HTTPException as exc:
                    logger.warning("Error enviando mensaje CC en %s: %s", channel, exc)

    def _format_content(self, content: str, author: Optional[discord.Member], args: List[str]) -> str:
        if author:
            content = content.replace("{user}", author.mention)
            content = content.replace("{username}", str(author))
            content = content.replace("{display_name}", author.display_name)
            content = content.replace("{id}", str(author.id))
        for i, arg in enumerate(args, 1):
            content = content.replace(f"{{{i}}}", arg)
        content = content.replace("{args}", " ".join(args))
        return content

    # ── /customcommand create ──────────────────────────────────────────────

    @cc_group.command(name="create", description="Crea un comando personalizado de texto")
    @app_commands.describe(
        name="Nombre del comando (sin prefijo)",
        content="Contenido que responderá el comando",
    )
    async def cc_create(self, interaction: discord.Interaction, name: str, content: str):
        if not _can_manage(interaction.user):
            return await interaction.response.send_message(
                "❌ Necesitas el permiso **Gestionar Servidor** para crear comandos.",
                ephemeral=True,
            )

        name = name.strip().lower()
        if not name.isidentifier() and " " in name:
            return await interaction.response.send_message(
                "❌ El nombre no puede contener espacios.", ephemeral=True,
            )

        existing = self.db.get_custom_commands(interaction.guild_id)
        if len(existing) >= MAX_COMMANDS:
            return await interaction.response.send_message(
                f"❌ Este servidor ya tiene el máximo de {MAX_COMMANDS} comandos.",
                ephemeral=True,
            )

        if self.db.get_custom_command(interaction.guild_id, name):
            return await interaction.response.send_message(
                f"❌ Ya existe un comando llamado **{name}**.",
                ephemeral=True,
            )

        actions = json.dumps([{"type": "send_message", "content": content}], ensure_ascii=False)

        self.db.create_custom_command(
            guild_id=interaction.guild_id,
            name=name,
            trigger_type="prefix",
            trigger_value=name,
            conditions="{}",
            actions=actions,
            creator_id=interaction.user.id,
        )

        embed = discord.Embed(
            title="✅ Comando creado",
            description=f"**{name}** responderá con el contenido especificado.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Contenido", value=content[:1000], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /customcommand delete ──────────────────────────────────────────────

    @cc_group.command(name="delete", description="Elimina un comando personalizado")
    @app_commands.describe(name="Nombre del comando a eliminar")
    @app_commands.autocomplete(name=_cc_autocomplete)
    async def cc_delete(self, interaction: discord.Interaction, name: str):
        if not _can_manage(interaction.user):
            return await interaction.response.send_message(
                "❌ Necesitas el permiso **Gestionar Servidor** para eliminar comandos.",
                ephemeral=True,
            )

        name = name.strip().lower()
        command = self.db.get_custom_command(interaction.guild_id, name)
        if not command:
            return await interaction.response.send_message(
                f"❌ No existe ningún comando llamado **{name}**.", ephemeral=True,
            )

        self.db.delete_custom_command(interaction.guild_id, name)

        embed = discord.Embed(
            title="🗑️ Comando eliminado",
            description=f"El comando **{name}** fue eliminado.",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /customcommand list ────────────────────────────────────────────────

    @cc_group.command(name="list", description="Lista todos los comandos personalizados del servidor")
    async def cc_list(self, interaction: discord.Interaction):
        commands = self.db.get_custom_commands(interaction.guild_id)
        if not commands:
            return await interaction.response.send_message(
                "📭 Este servidor no tiene comandos personalizados todavía.\n"
                "Crea uno con `/customcommand create`.",
                ephemeral=True,
            )

        lines = []
        for cmd in commands:
            status = "✅" if cmd["enabled"] else "❌"
            lines.append(f"{status} **{cmd['name']}** — {cmd['uses']} uso(s)")

        description = "\n".join(lines)
        if len(description) > 4000:
            description = description[:4000] + "\n..."

        embed = discord.Embed(
            title=f"⚙️ Comandos personalizados — {interaction.guild.name}",
            description=description,
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"{len(commands)}/{MAX_COMMANDS} comandos")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /customcommand info ────────────────────────────────────────────────

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

        actions = self._parse_actions(cmd["actions"])
        preview = ""
        for a in actions:
            if a.get("type") == "send_message":
                preview = a.get("content", "")[:500]
                break

        embed = discord.Embed(
            title=f"⚙️ Info: {cmd['name']}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Creador", value=creator_text, inline=True)
        embed.add_field(name="Usos", value=str(cmd["uses"]), inline=True)
        embed.add_field(name="Creado", value=f"`{cmd['created_at'][:10]}`", inline=True)
        embed.add_field(name="Habilitado", value="✅ Sí" if cmd["enabled"] else "❌ No", inline=True)
        if preview:
            embed.add_field(name="Respuesta", value=preview, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /customcommand variable group ──────────────────────────────────────

    cc_variable_group = app_commands.Group(
        name="variable",
        description="Gestiona variables persistentes de comandos personalizados",
        parent=cc_group,
    )

    @cc_variable_group.command(name="get", description="Obtiene el valor de una variable persistente")
    @app_commands.describe(key="Nombre de la variable")
    async def cc_variable_get(self, interaction: discord.Interaction, key: str):
        value = self.db.get_cc_variable(interaction.guild_id, key)
        if value is None:
            return await interaction.response.send_message(
                f"❌ La variable **{key}** no existe.", ephemeral=True,
            )

        embed = discord.Embed(
            title="📦 Variable",
            description=f"**{key}** = `{value}`",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @cc_variable_group.command(name="set", description="Establece el valor de una variable persistente")
    @app_commands.describe(key="Nombre de la variable", value="Valor a asignar")
    async def cc_variable_set(self, interaction: discord.Interaction, key: str, value: str):
        if not _can_manage(interaction.user):
            return await interaction.response.send_message(
                "❌ Necesitas el permiso **Gestionar Servidor** para establecer variables.",
                ephemeral=True,
            )

        self.db.set_cc_variable(interaction.guild_id, key, value)

        embed = discord.Embed(
            title="✅ Variable actualizada",
            description=f"**{key}** = `{value}`",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomCommands(bot))
