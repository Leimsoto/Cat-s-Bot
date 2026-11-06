"""
cogs/tags.py
────────────
Sistema de Tags / Comandos personalizados del servidor.

Comandos:
  /tag get    nombre   — Usa un tag (autocomplete)
  /tag create          — Crea un tag (modal)
  /tag edit   nombre   — Edita el contenido (modal)
  /tag delete nombre   — Elimina con confirmación
  /tag list            — Lista todos los tags del servidor
  /tag info   nombre   — Info: creador, usos, fecha

Permisos para crear/editar/borrar: manage_messages o admin.
"""

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)
MAX_TAGS = 50  # máximo por servidor


# ── Helpers ───────────────────────────────────────────────────────────────────

def _can_manage(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or member.guild_permissions.manage_messages


async def _require_manage(interaction: discord.Interaction) -> bool:
    if interaction.guild is not None and _can_manage(interaction.user):
        return True
    await interaction.response.send_message(
        "❌ Necesitas el permiso **Gestionar Mensajes** para modificar tags.", ephemeral=True
    )
    return False


async def _tag_autocomplete(interaction: discord.Interaction, current: str):
    tags = interaction.client.db.get_all_tags(interaction.guild_id)
    return [
        app_commands.Choice(name=t["name"], value=t["name"])
        for t in tags if current.lower() in t["name"]
    ][:25]


# ── Modals ────────────────────────────────────────────────────────────────────

class TagCreateModal(discord.ui.Modal, title="Crear Tag"):
    name_input = discord.ui.TextInput(
        label="Nombre del tag",
        placeholder="faq, reglas, info...",
        max_length=50,
        min_length=1,
    )
    content_input = discord.ui.TextInput(
        label="Contenido",
        style=discord.TextStyle.paragraph,
        placeholder="Escribe el contenido del tag aquí...",
        max_length=2000,
        min_length=1,
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if not await _require_manage(interaction):
            return
        name = self.name_input.value.strip().lower()
        content = self.content_input.value.strip()

        if not name or not content:
            return await interaction.response.send_message(
                "❌ El nombre y el contenido del tag no pueden quedar en blanco.", ephemeral=True
            )

        if not name.isidentifier() and " " in name:
            return await interaction.response.send_message(
                "❌ El nombre no puede tener espacios. Usa guiones o guiones bajos.", ephemeral=True
            )

        existing = self.cog.db.get_all_tags(interaction.guild_id)
        if len(existing) >= MAX_TAGS:
            return await interaction.response.send_message(
                f"❌ Este servidor ya tiene el máximo de {MAX_TAGS} tags.", ephemeral=True
            )

        if self.cog.db.get_tag(interaction.guild_id, name):
            return await interaction.response.send_message(
                f"❌ Ya existe un tag con el nombre **{name}**. Usa `/tag edit` para modificarlo.", ephemeral=True
            )

        self.cog.db.create_tag(interaction.guild_id, name, content, interaction.user.id)
        await interaction.response.send_message(f"✅ Tag **{name}** creado correctamente.", ephemeral=True)


class TagEditModal(discord.ui.Modal, title="Editar Tag"):
    content_input = discord.ui.TextInput(
        label="Nuevo contenido",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        min_length=1,
    )

    def __init__(self, cog, tag_name: str, current_content: str):
        super().__init__()
        self.cog = cog
        self.tag_name = tag_name
        self.content_input.default = current_content

    async def on_submit(self, interaction: discord.Interaction):
        if not await _require_manage(interaction):
            return
        content = self.content_input.value.strip()
        if not content:
            return await interaction.response.send_message("❌ El contenido no puede quedar en blanco.", ephemeral=True)
        if not self.cog.db.get_tag(interaction.guild_id, self.tag_name):
            return await interaction.response.send_message("❌ Este tag ya no existe.", ephemeral=True)
        self.cog.db.update_tag(interaction.guild_id, self.tag_name, content)
        await interaction.response.send_message(f"✅ Tag **{self.tag_name}** actualizado.", ephemeral=True)


# ── Confirm View ──────────────────────────────────────────────────────────────

class TagDeleteView(discord.ui.View):
    def __init__(self, cog, tag_name: str, author_id: int):
        super().__init__(timeout=30)
        self.cog = cog
        self.tag_name = tag_name
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Solo quien ejecutó el comando puede confirmar.", ephemeral=True)
            return False
        return await _require_manage(interaction)

    @discord.ui.button(label="Eliminar", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_check(interaction):
            return
        self.cog.db.delete_tag(interaction.guild_id, self.tag_name)
        await interaction.response.edit_message(content=f"✅ Tag **{self.tag_name}** eliminado.", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Operación cancelada.", embed=None, view=None)
        self.stop()


# ── Cog ───────────────────────────────────────────────────────────────────────

class Tags(commands.Cog):
    """Sistema de tags personalizados del servidor."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    tag_group = app_commands.Group(name="tag", description="Sistema de tags personalizados")

    @tag_group.command(name="get", description="Usa un tag del servidor")
    @app_commands.describe(nombre="Nombre del tag")
    @app_commands.autocomplete(nombre=_tag_autocomplete)
    async def tag_get(self, interaction: discord.Interaction, nombre: str):
        tag = self.db.get_tag(interaction.guild_id, nombre.lower())
        if not tag:
            return await interaction.response.send_message(
                f"❌ No existe ningún tag con el nombre **{nombre}**.", ephemeral=True
            )
        from cogs._managed_messages import send_managed
        await send_managed(self.bot, interaction.guild_id, "tags", interaction.response.send_message, tag["content"])
        self.db.increment_tag_uses(interaction.guild_id, nombre.lower())

    @tag_group.command(name="create", description="Crea un nuevo tag del servidor")
    @app_commands.default_permissions(manage_messages=True)
    async def tag_create(self, interaction: discord.Interaction):
        if not _can_manage(interaction.user):
            return await interaction.response.send_message(
                "❌ Necesitas el permiso **Gestionar Mensajes** para crear tags.", ephemeral=True
            )
        await interaction.response.send_modal(TagCreateModal(self))

    @tag_group.command(name="edit", description="Edita el contenido de un tag existente")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(nombre="Nombre del tag a editar")
    @app_commands.autocomplete(nombre=_tag_autocomplete)
    async def tag_edit(self, interaction: discord.Interaction, nombre: str):
        if not _can_manage(interaction.user):
            return await interaction.response.send_message(
                "❌ Necesitas el permiso **Gestionar Mensajes** para editar tags.", ephemeral=True
            )
        tag = self.db.get_tag(interaction.guild_id, nombre.lower())
        if not tag:
            return await interaction.response.send_message(
                f"❌ No existe ningún tag con el nombre **{nombre}**.", ephemeral=True
            )
        await interaction.response.send_modal(TagEditModal(self, nombre.lower(), tag["content"]))

    @tag_group.command(name="delete", description="Elimina un tag del servidor")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(nombre="Nombre del tag a eliminar")
    @app_commands.autocomplete(nombre=_tag_autocomplete)
    async def tag_delete(self, interaction: discord.Interaction, nombre: str):
        if not _can_manage(interaction.user):
            return await interaction.response.send_message(
                "❌ Necesitas el permiso **Gestionar Mensajes** para eliminar tags.", ephemeral=True
            )
        tag = self.db.get_tag(interaction.guild_id, nombre.lower())
        if not tag:
            return await interaction.response.send_message(
                f"❌ No existe ningún tag con el nombre **{nombre}**.", ephemeral=True
            )
        embed = discord.Embed(
            title="🗑️ Confirmar eliminación",
            description=f"¿Seguro que quieres eliminar el tag **{nombre}**?\n\n> {tag['content'][:200]}{'...' if len(tag['content']) > 200 else ''}",
            color=discord.Color.red(),
        )
        view = TagDeleteView(self, nombre.lower(), interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @tag_group.command(name="list", description="Lista todos los tags del servidor")
    async def tag_list(self, interaction: discord.Interaction):
        tags = self.db.get_all_tags(interaction.guild_id)
        if not tags:
            return await interaction.response.send_message(
                "📭 Este servidor no tiene tags todavía. Crea uno con `/tag create`.", ephemeral=True
            )

        # Paginación simple: 20 por embed
        lines = [f"**{t['name']}** — {t['uses']} uso(s)" for t in tags]
        description = "\n".join(lines)
        if len(description) > 4000:
            description = description[:4000] + "\n..."

        embed = discord.Embed(
            title=f"🏷️ Tags del servidor — {interaction.guild.name}",
            description=description,
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"{len(tags)}/{MAX_TAGS} tags usados")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tag_group.command(name="info", description="Muestra información sobre un tag")
    @app_commands.describe(nombre="Nombre del tag")
    @app_commands.autocomplete(nombre=_tag_autocomplete)
    async def tag_info(self, interaction: discord.Interaction, nombre: str):
        tag = self.db.get_tag(interaction.guild_id, nombre.lower())
        if not tag:
            return await interaction.response.send_message(
                f"❌ No existe ningún tag con el nombre **{nombre}**.", ephemeral=True
            )

        creator = interaction.guild.get_member(int(tag["creator_id"]))
        creator_text = creator.mention if creator else f"ID: {tag['creator_id']}"
        created_dt = tag["created_at"]

        embed = discord.Embed(
            title=f"🏷️ Info: {tag['name']}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Creador", value=creator_text, inline=True)
        embed.add_field(name="Usos", value=str(tag["uses"]), inline=True)
        embed.add_field(name="Creado", value=f"`{created_dt[:10]}`", inline=True)
        embed.add_field(
            name="Contenido (preview)",
            value=tag["content"][:500] + ("..." if len(tag["content"]) > 500 else ""),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tags(bot))
