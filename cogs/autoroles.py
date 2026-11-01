import logging
import json

import discord
from discord.ext import commands
from discord import app_commands

from cogs._role_safety import (
    safe_for_automatic_assignment,
    safe_for_automatic_removal,
    self_service_forbidden_role_ids,
)

logger = logging.getLogger(__name__)

class AutoRoles(commands.Cog):
    """Módulo de Autoroles: por reacción + asignación automática al unirse."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db # type: ignore

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Asigna los join-autoroles configurados al nuevo miembro."""
        if member.bot:
            return
        rows = self.db.get_join_autoroles(member.guild.id)
        if not rows:
            return
        roles_to_add = []
        bot_member = member.guild.me
        forbidden_role_ids = self_service_forbidden_role_ids(self.db, member.guild.id)
        for row in rows:
            role = member.guild.get_role(int(row["role_id"]))
            if safe_for_automatic_assignment(
                role,
                bot_member,
                forbidden_role_ids=forbidden_role_ids,
            ):
                roles_to_add.append(role)
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Auto-asignación al unirse")
            except discord.Forbidden:
                logger.warning("Sin permisos para asignar autoroles en %s", member.guild.name)
            except discord.HTTPException as e:
                logger.warning("Error asignando autoroles: %s", e)

    @app_commands.command(name="autorolereact", description="Configura un rol por reacción en un mensaje existente")
    @app_commands.describe(
        mensaje_id="ID del mensaje al que se reaccionará",
        emoji="Emoji a reaccionar (solo pon el emoji, ej: 👍 o un emoji personalizado)",
        rol="Rol a entregar"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def autorolereact_setup(self, interaction: discord.Interaction, mensaje_id: str, emoji: str, rol: discord.Role):
        try:
            msg_id = int(mensaje_id)
            msg = await interaction.channel.fetch_message(msg_id)
        except (ValueError, discord.NotFound):
            return await interaction.response.send_message("❌ Mensaje no encontrado en este canal. Asegúrate de poner el ID correcto.", ephemeral=True)
        
        forbidden_role_ids = self_service_forbidden_role_ids(
            self.db, interaction.guild_id
        )
        if not safe_for_automatic_assignment(
            rol,
            interaction.guild.me,
            forbidden_role_ids=forbidden_role_ids,
        ):
            return await interaction.response.send_message(
                "❌ Ese rol no es seguro para autoasignación: debe estar bajo mi rol y no "
                "puede conceder permisos administrativos o de moderación.",
                ephemeral=True,
            )

        existing = self.db.get_autorole(msg_id)
        mapping = {}
        if existing:
            try:
                mapping = json.loads(existing.get("mapping_data") or "{}")
            except Exception:
                mapping = {}

        # La representación completa incluye el ID de emojis personalizados.
        mapping[str(emoji)] = rol.id
        
        try:
            await msg.add_reaction(emoji)
        except (discord.Forbidden, discord.HTTPException, TypeError) as e:
            logger.warning("No se pudo añadir reacción inicial: %s", e)
            return await interaction.response.send_message(
                f"❌ No pude añadir la reacción al mensaje: {e}", ephemeral=True
            )

        self.db.set_autorole(msg_id, interaction.guild_id, interaction.channel.id, json.dumps(mapping))
            
        await interaction.response.send_message(f"✅ AutoRol configurado. Al reaccionar con {emoji} en el mensaje, se dará el rol {rol.mention}.", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, add=False)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, *, add: bool) -> None:
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        row = self.db.get_autorole(payload.message_id)
        if not row:
            return
        if int(row.get("guild_id") or 0) != int(payload.guild_id or 0):
            return
        if int(row.get("channel_id") or 0) != int(payload.channel_id or 0):
            return
        try:
            mapping = json.loads(row.get("mapping_data") or "{}")
        except (TypeError, json.JSONDecodeError):
            mapping = {}
        matched = mapping.get(str(payload.emoji))
        if matched is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(int(matched))
        if role is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if member.bot:
            return
        role = guild.get_role(role.id)
        bot_member = guild.me or (guild.get_member(self.bot.user.id) if self.bot.user else None)
        forbidden_role_ids = self_service_forbidden_role_ids(self.db, guild.id)
        role_is_safe = (
            safe_for_automatic_assignment(
                role,
                bot_member,
                forbidden_role_ids=forbidden_role_ids,
            )
            if add
            else (
                forbidden_role_ids is not None
                and role.id not in forbidden_role_ids
                and safe_for_automatic_removal(role, bot_member)
            )
        )
        if not role_is_safe:
            return
        try:
            if add:
                await member.add_roles(role, reason="AutoRole Reaction")
            else:
                await member.remove_roles(role, reason="AutoRole Reaction")
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(
                "No se pudo %s autorol %s a %s en %s: %s",
                "asignar" if add else "retirar",
                role.id,
                member.id,
                guild.id,
                exc,
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRoles(bot))
