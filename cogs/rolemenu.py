"""
cogs/rolemenu.py
────────────────
Menú de roles con dropdown (self-roles).
Los usuarios se asignan/quitan roles ellos mismos.

Comandos slash:
  /rolemenu create  – Crear un menú de roles en el canal actual
  /rolemenu delete  – Eliminar un menú de roles existente
"""

import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs._role_safety import (
    safe_for_automatic_assignment,
    safe_for_automatic_removal,
    self_service_forbidden_role_ids,
)

logger = logging.getLogger(__name__)


class RoleSelect(discord.ui.Select):
    def __init__(self, roles: list[discord.Role], placeholder: str, max_values: int):
        options = [
            discord.SelectOption(
                label=role.name,
                value=str(role.id),
                emoji="✅",
                description=f"Miembros: {len(role.members)}",
            )
            for role in roles[:25]
        ]
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=min(max_values, len(options)),
            options=options,
            custom_id="rolemenu_select",
        )
        self.role_map = {str(r.id): r for r in roles[:25]}

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        added = []
        removed = []
        selected_ids = set(self.values)
        current_ids = {str(r.id) for r in member.roles}
        bot_member = interaction.guild.me if interaction.guild else None
        db = getattr(interaction.client, "db", None)
        forbidden_role_ids = self_service_forbidden_role_ids(
            db, interaction.guild_id
        )

        for role_id in self.role_map:
            role = interaction.guild.get_role(int(role_id)) if interaction.guild else None
            if role is None:
                continue
            if role_id in selected_ids and role_id not in current_ids:
                if not safe_for_automatic_assignment(
                    role,
                    bot_member,
                    forbidden_role_ids=forbidden_role_ids,
                ):
                    continue
                try:
                    await member.add_roles(role, reason="RoleMenu self-assign")
                    added.append(role.mention)
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.warning("Error asignando rol %s: %s", role_id, e)
            elif role_id not in selected_ids and role_id in current_ids:
                if (
                    forbidden_role_ids is None
                    or role.id in forbidden_role_ids
                    or not safe_for_automatic_removal(role, bot_member)
                ):
                    continue
                try:
                    await member.remove_roles(role, reason="RoleMenu self-remove")
                    removed.append(role.mention)
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.warning("Error quitando rol %s: %s", role_id, e)

        lines = []
        if added:
            lines.append(f"✅ Roles asignados: {', '.join(added)}")
        if removed:
            lines.append(f"❌ Roles quitados: {', '.join(removed)}")
        if not lines:
            lines.append("ℹ️ No hubo cambios en tus roles.")

        await interaction.followup.send("\n".join(lines), ephemeral=True)


class RoleMenuView(discord.ui.View):
    def __init__(self, roles: list[discord.Role], placeholder: str, max_values: int):
        super().__init__(timeout=None)
        self.add_item(RoleSelect(roles, placeholder, max_values))


class RoleMenu(commands.Cog):
    """Menús de roles autoasignables con dropdown."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self._restored = False

    @commands.Cog.listener()
    async def on_ready(self):
        if self._restored:
            return
        restored = 0
        for record in self.db.get_role_menus():
            guild = self.bot.get_guild(int(record["guild_id"]))
            if guild is None:
                continue
            roles = [guild.get_role(int(role_id)) for role_id in record.get("role_ids", [])]
            forbidden_role_ids = self_service_forbidden_role_ids(self.db, guild.id)
            roles = [
                role
                for role in roles
                if safe_for_automatic_assignment(
                    role,
                    guild.me,
                    forbidden_role_ids=forbidden_role_ids,
                )
            ]
            if not roles:
                logger.warning("RoleMenu %s sin roles válidos; se omite", record["message_id"])
                continue
            view = RoleMenuView(
                roles,
                str(record.get("placeholder") or "Selecciona tus roles"),
                int(record.get("max_values") or 1),
            )
            self.bot.add_view(view, message_id=int(record["message_id"]))
            restored += 1
        self._restored = True
        logger.info("RoleMenus persistentes restaurados: %s", restored)

    @app_commands.command(name="menu_roles", description="Crea un menú de roles autoasignables")
    @app_commands.describe(
        roles="Roles disponibles (separados por espacio, mencionándolos)",
        placeholder="Texto guía del menú (ej: 'Elige tus roles')",
        max_roles="Máximo de roles que puede elegir cada usuario",
        titulo="Título del embed (opcional)",
        descripcion="Descripción del embed (opcional)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def rolemenu_create(
        self,
        interaction: discord.Interaction,
        roles: str,
        placeholder: str = "Selecciona tus roles",
        max_roles: app_commands.Range[int, 1, 25] = 1,
        titulo: str = "Menú de Roles",
        descripcion: str = "Selecciona los roles que quieras del menú desplegable.",
    ):
        role_list = []
        forbidden_role_ids = self_service_forbidden_role_ids(
            self.db, interaction.guild_id
        )
        for part in roles.split():
            role_id = part.strip("<@&>")
            try:
                role = interaction.guild.get_role(int(role_id))
                if safe_for_automatic_assignment(
                    role,
                    interaction.guild.me,
                    forbidden_role_ids=forbidden_role_ids,
                ):
                    if role not in role_list:
                        role_list.append(role)
            except ValueError:
                continue

        role_list = role_list[:25]
        if not role_list:
            return await interaction.response.send_message(
                "❌ No se encontraron roles válidos. Asegúrate de mencionarlos y de que estén por debajo de mi rol.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title=titulo,
            description=descripcion,
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Roles disponibles",
            value="\n".join(f"{r.mention}" for r in role_list),
            inline=False,
        )
        embed.set_footer(text=f"Máximo {max_roles} rol(es) por persona")

        view = RoleMenuView(role_list, placeholder, max_roles)
        from cogs._managed_messages import send_managed
        await send_managed(self.bot, interaction.guild_id, "rolemenu", interaction.response.send_message, embed=embed, view=view)
        message = await interaction.original_response()
        self.db.save_role_menu(
            message.id,
            interaction.guild_id,
            interaction.channel_id,
            [role.id for role in role_list],
            placeholder,
            int(max_roles),
            titulo,
            descripcion,
        )

    @app_commands.command(name="menu_roles_eliminar", description="Elimina un menú de roles persistente")
    @app_commands.describe(mensaje_id="ID del mensaje que contiene el menú")
    @app_commands.checks.has_permissions(administrator=True)
    async def rolemenu_delete(self, interaction: discord.Interaction, mensaje_id: str):
        try:
            message_id = int(mensaje_id)
        except ValueError:
            return await interaction.response.send_message("❌ ID de mensaje inválido.", ephemeral=True)

        record = next(
            (
                item
                for item in self.db.get_role_menus(interaction.guild_id)
                if int(item["message_id"]) == message_id
            ),
            None,
        )
        if record is None:
            return await interaction.response.send_message(
                "❌ Ese mensaje no corresponde a un menú registrado.", ephemeral=True
            )

        channel = interaction.guild.get_channel(int(record["channel_id"]))
        if channel is not None and hasattr(channel, "fetch_message"):
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException) as exc:
                return await interaction.response.send_message(
                    f"❌ No pude eliminar el mensaje del menú: {exc}", ephemeral=True
                )
        self.db.delete_role_menu(message_id, interaction.guild_id)
        await interaction.response.send_message("✅ Menú de roles eliminado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleMenu(bot))
