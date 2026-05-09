import logging
import json

import discord
from discord.ext import commands
from discord import app_commands

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
        for row in rows:
            role = member.guild.get_role(int(row["role_id"]))
            if role and not role.managed and role != member.guild.default_role:
                if role.position < member.guild.me.top_role.position:
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
        
        # Evitar roles gestionados por integraciones o @everyone
        if rol.managed or rol == interaction.guild.default_role:
            return await interaction.response.send_message(
                "❌ No puedes usar roles gestionados por integraciones o @everyone.", ephemeral=True
            )
            
        if rol.position >= interaction.guild.me.top_role.position:
            return await interaction.response.send_message("❌ El rol es superior al rol más alto del bot. Mueve el rol del bot hacia arriba en la configuración del servidor.", ephemeral=True)

        existing = self.db.get_autorole(msg_id)
        mapping = {}
        if existing:
            try:
                mapping = json.loads(existing.get("mapping_data") or "{}")
            except Exception:
                mapping = {}

        # Normalizar y almacenar múltiples claves para el emoji (forma completa y nombre)
        keys = {emoji}
        if isinstance(emoji, str) and emoji.startswith("<") and ":" in emoji:
            try:
                name = emoji.split(":")[1]
                keys.add(name)
            except Exception:
                pass

        for k in keys:
            mapping[k] = rol.id
        
        self.db.set_autorole(msg_id, interaction.guild_id, interaction.channel.id, json.dumps(mapping))
        
        try:
            await msg.add_reaction(emoji)
        except Exception as e:
            logger.warning(f"No se pudo añadir reacción inicial: {e}")
            
        await interaction.response.send_message(f"✅ AutoRol configurado. Al reaccionar con {emoji} en el mensaje, se dará el rol {rol.mention}.", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        row = self.db.get_autorole(payload.message_id)
        if not row:
            return

        try:
            mapping = json.loads(row.get("mapping_data") or "{}")
        except Exception:
            mapping = {}

        # Probar varias representaciones del emoji: str() y name
        keys_to_try = [str(payload.emoji)]
        if hasattr(payload.emoji, "name") and payload.emoji.name:
            keys_to_try.append(payload.emoji.name)

        matched_role_id = None
        for k in keys_to_try:
            if k in mapping:
                matched_role_id = mapping[k]
                break

        if matched_role_id:
            guild = self.bot.get_guild(payload.guild_id)
            if guild:
                role = guild.get_role(matched_role_id)
                member = guild.get_member(payload.user_id)
                if role and member:
                    try:
                        await member.add_roles(role, reason="AutoRole Reaction")
                    except discord.Forbidden:
                        pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        row = self.db.get_autorole(payload.message_id)
        if not row:
            return

        try:
            mapping = json.loads(row.get("mapping_data") or "{}")
        except Exception:
            mapping = {}

        keys_to_try = [str(payload.emoji)]
        if hasattr(payload.emoji, "name") and payload.emoji.name:
            keys_to_try.append(payload.emoji.name)

        matched_role_id = None
        for k in keys_to_try:
            if k in mapping:
                matched_role_id = mapping[k]
                break

        if matched_role_id:
            guild = self.bot.get_guild(payload.guild_id)
            if guild:
                role = guild.get_role(matched_role_id)
                member = guild.get_member(payload.user_id)
                if role and member:
                    try:
                        await member.remove_roles(role, reason="AutoRole Reaction")
                    except discord.Forbidden:
                        pass

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRoles(bot))
