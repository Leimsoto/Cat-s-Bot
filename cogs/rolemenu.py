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
        )
        self.role_map = {str(r.id): r for r in roles}

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        added = []
        removed = []
        selected_ids = set(self.values)
        current_ids = {str(r.id) for r in member.roles}

        for role_id, role in self.role_map.items():
            if role_id in selected_ids and role_id not in current_ids:
                try:
                    await member.add_roles(role, reason="RoleMenu self-assign")
                    added.append(role.mention)
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.warning("Error asignando rol %s: %s", role_id, e)
            elif role_id not in selected_ids and role_id in current_ids:
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

        await interaction.response.send_message("\n".join(lines), ephemeral=True)


class RoleMenuView(discord.ui.View):
    def __init__(self, roles: list[discord.Role], placeholder: str, max_values: int):
        super().__init__(timeout=None)
        self.add_item(RoleSelect(roles, placeholder, max_values))


class RoleMenu(commands.Cog):
    """Menús de roles autoasignables con dropdown."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

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
        for part in roles.split():
            role_id = part.strip("<@&>")
            try:
                role = interaction.guild.get_role(int(role_id))
                if role and role < interaction.guild.me.top_role:
                    role_list.append(role)
            except ValueError:
                continue

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
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleMenu(bot))
