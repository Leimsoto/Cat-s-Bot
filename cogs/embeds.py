"""
cogs/embeds.py
──────────────
Sistema avanzado de creación de embeds interactivo.

Comandos slash:
  /embed create – Constructor de embeds con preview en tiempo real
  /embed list   – Lista embeds guardados del servidor
  /embed load   – Carga un embed guardado para editarlo/enviarlo

Solo accesible por el rol configurado (embed_role_id) o administrador.
Cooldown: 1 uso cada 30 segundos por usuario.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("Embeds")


class EmbedBuilder:
    """Estado mutable del embed en construcción."""

    def __init__(self):
        self.title: Optional[str] = None
        self.description: Optional[str] = None
        self.color: int = 0x5865F2  # Blurple
        self.image_url: Optional[str] = None
        self.thumbnail_url: Optional[str] = None
        self.author_name: Optional[str] = None
        self.author_icon: Optional[str] = None
        self.footer_text: Optional[str] = None
        self.footer_icon: Optional[str] = None
        self.url: Optional[str] = None
        self.timestamp: bool = False
        self.fields: list = []  # [{name, value, inline}]

    def build(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            description=self.description,
            color=discord.Color(self.color),
            url=self.url,
        )
        if self.timestamp:
            embed.timestamp = datetime.now(timezone.utc)
        if self.image_url:
            embed.set_image(url=self.image_url)
        if self.thumbnail_url:
            embed.set_thumbnail(url=self.thumbnail_url)
        if self.author_name:
            embed.set_author(name=self.author_name, icon_url=self.author_icon)
        if self.footer_text:
            embed.set_footer(text=self.footer_text, icon_url=self.footer_icon)
        for f in self.fields:
            embed.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
        return embed

    def to_json(self) -> str:
        return json.dumps({
            "title": self.title, "description": self.description,
            "color": self.color, "image_url": self.image_url,
            "thumbnail_url": self.thumbnail_url,
            "author_name": self.author_name, "author_icon": self.author_icon,
            "footer_text": self.footer_text, "footer_icon": self.footer_icon,
            "url": self.url, "timestamp": self.timestamp, "fields": self.fields,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> "EmbedBuilder":
        d = json.loads(data)
        b = cls()
        for k, v in d.items():
            if hasattr(b, k):
                setattr(b, k, v)
        return b


# ── Grupo de comandos ─────────────────────────────────────────────────────────

class Embeds(commands.Cog):
    """Sistema avanzado de creación de embeds."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    async def _check_embed_perms(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        permissions = getattr(member, "guild_permissions", None)
        if interaction.guild is not None and permissions is not None and permissions.administrator:
            return True
        if interaction.guild is not None and permissions is not None:
            srv_cfg = self.db.get_server_config(interaction.guild_id)
            role_id = srv_cfg.get("embed_role_id")
            if role_id and any(r.id == int(role_id) for r in member.roles):
                return True
            
        msg = "❌ Necesitas el **rol de embeds** configurado o ser administrador."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return False

    embed_group = app_commands.Group(
        name="embed",
        description="Sistema de creación y gestión de embeds",
    )

    @embed_group.command(name="create", description="Abre el constructor de embeds interactivo")
    @app_commands.checks.cooldown(1, 30, key=lambda i: (i.guild_id, i.user.id))
    async def embed_create(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self._check_embed_perms(interaction):
            return

        builder = EmbedBuilder()
        view = EmbedBuilderView(self, builder, interaction.user.id, interaction.guild_id)
        status = view.build_status_embed(builder)
        await interaction.followup.send(embed=status, view=view, ephemeral=True)

    @embed_group.command(name="list", description="Lista los embeds guardados del servidor")
    async def embed_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self._check_embed_perms(interaction):
            return

        embeds_saved = self.db.get_saved_embeds(interaction.guild_id)
        if not embeds_saved:
            return await interaction.followup.send(
                "📭 No hay embeds guardados en este servidor.", ephemeral=True,
            )

        lines = []
        for i, e in enumerate(embeds_saved[:25], 1):
            name = e.get("name", "Sin nombre")
            creator = f"<@{e['creator_id']}>"
            lines.append(f"**{i}.** `{name}` — Creado por {creator}")

        embed = discord.Embed(
            title="📋 Embeds Guardados",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @embed_group.command(name="load", description="Carga un embed guardado para editarlo o enviarlo")
    @app_commands.describe(nombre="Nombre del embed guardado")
    async def embed_load(self, interaction: discord.Interaction, nombre: str):
        await interaction.response.defer(ephemeral=True)
        if not await self._check_embed_perms(interaction):
            return

        saved = self.db.get_saved_embed_by_name(interaction.guild_id, nombre)
        if not saved:
            return await interaction.followup.send(
                f"❌ No se encontró un embed con nombre `{nombre}`.", ephemeral=True,
            )

        builder = EmbedBuilder.from_json(saved["embed_data"])
        view = EmbedBuilderView(self, builder, interaction.user.id, interaction.guild_id)
        status = view.build_status_embed(builder)
        await interaction.followup.send(embed=status, view=view, ephemeral=True)


# ── Vista principal del constructor ───────────────────────────────────────────

class EmbedBuilderView(discord.ui.View):
    def __init__(self, cog: Embeds, builder: EmbedBuilder, author_id: int, guild_id: int):
        super().__init__(timeout=600)  # 10 minutos para configurar
        self.cog = cog
        self.builder = builder
        self.author_id = author_id
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message("❌ Solo quien creó el constructor puede usarlo.", ephemeral=True)
            return False
        return await self.cog._check_embed_perms(interaction)

    def build_status_embed(self, builder: EmbedBuilder) -> discord.Embed:
        """Embed de estado mostrando qué está configurado."""
        e = discord.Embed(
            title="🎨 Constructor de Embeds",
            description="Configura tu embed usando los botones. Usa **Preview** para ver el resultado.",
            color=discord.Color.dark_teal(),
        )
        check = lambda v: "✅" if v else "❌"
        e.add_field(name="📝 Título", value=check(builder.title), inline=True)
        e.add_field(name="📄 Descripción", value=check(builder.description), inline=True)
        e.add_field(name="🎨 Color", value=f"`#{builder.color:06X}`", inline=True)
        e.add_field(name="🖼️ Imagen", value=check(builder.image_url), inline=True)
        e.add_field(name="🔲 Thumbnail", value=check(builder.thumbnail_url), inline=True)
        e.add_field(name="👤 Autor", value=check(builder.author_name), inline=True)
        e.add_field(name="📎 Footer", value=check(builder.footer_text), inline=True)
        e.add_field(name="🔗 URL", value=check(builder.url), inline=True)
        e.add_field(name="📋 Campos", value=f"`{len(builder.fields)}/25`", inline=True)
        e.set_footer(text="Timeout: 10 minutos")
        return e

    async def _refresh(self, interaction: discord.Interaction):
        status = self.build_status_embed(self.builder)
        await interaction.response.edit_message(embed=status, view=self)

    @discord.ui.button(label="Título/Desc", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def title_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TitleDescModal(self))

    @discord.ui.button(label="Color", emoji="🎨", style=discord.ButtonStyle.primary, row=0)
    async def color_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ColorModal(self))

    @discord.ui.button(label="Imágenes", emoji="🖼️", style=discord.ButtonStyle.primary, row=0)
    async def images_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ImagesModal(self))

    @discord.ui.button(label="Autor/Footer", emoji="📎", style=discord.ButtonStyle.secondary, row=1)
    async def author_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuthorFooterModal(self))

    @discord.ui.button(label="Añadir Campo", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def field_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.builder.fields) >= 25:
            return await interaction.response.send_message("❌ Máximo 25 campos.", ephemeral=True)
        await interaction.response.send_modal(FieldModal(self))

    @discord.ui.button(label="URL", emoji="🔗", style=discord.ButtonStyle.secondary, row=1)
    async def url_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(URLModal(self))

    @discord.ui.button(label="Preview", emoji="👁️", style=discord.ButtonStyle.success, row=2)
    async def preview_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            preview = self.builder.build()
            await interaction.response.send_message(
                content="**Vista previa:**", embed=preview, ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error en preview: {e}", ephemeral=True)

    @discord.ui.button(label="Enviar", emoji="📤", style=discord.ButtonStyle.success, row=2)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.builder.title and not self.builder.description:
            return await interaction.response.send_message(
                "❌ El embed necesita al menos un título o descripción.", ephemeral=True,
            )
        view = SendChannelSelectView(self)
        await interaction.response.edit_message(
            content="📤 **Selecciona el canal donde enviar el embed:**", view=view,
        )

    @discord.ui.button(label="Guardar", emoji="💾", style=discord.ButtonStyle.success, row=2)
    async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SaveEmbedModal(self))

    @discord.ui.button(label="Limpiar Campos", emoji="🗑️", style=discord.ButtonStyle.danger, row=3)
    async def clear_fields_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.builder.fields.clear()
        await self._refresh(interaction)

    @discord.ui.button(label="Cancelar", emoji="❌", style=discord.ButtonStyle.danger, row=3)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ Constructor cerrado.", embed=None, view=None)
        self.stop()


# ── Modals ────────────────────────────────────────────────────────────────────

class TitleDescModal(discord.ui.Modal, title="Título y Descripción"):
    embed_title = discord.ui.TextInput(label="Título", max_length=256, required=False)
    embed_desc = discord.ui.TextInput(
        label="Descripción", style=discord.TextStyle.paragraph,
        max_length=4000, required=False,
    )
    use_timestamp = discord.ui.TextInput(
        label="¿Incluir timestamp? (si/no)", default="no",
        max_length=3, required=False,
    )

    def __init__(self, parent: EmbedBuilderView):
        super().__init__()
        self.parent = parent
        if parent.builder.title:
            self.embed_title.default = parent.builder.title
        if parent.builder.description:
            self.embed_desc.default = parent.builder.description
        self.use_timestamp.default = "si" if parent.builder.timestamp else "no"

    async def on_submit(self, interaction: discord.Interaction):
        self.parent.builder.title = self.embed_title.value or None
        self.parent.builder.description = self.embed_desc.value or None
        self.parent.builder.timestamp = self.use_timestamp.value.lower().startswith("s")
        await self.parent._refresh(interaction)


class ColorModal(discord.ui.Modal, title="Color del Embed"):
    color_input = discord.ui.TextInput(
        label="Color hex (sin #)", placeholder="5865F2",
        default="5865F2", max_length=8,
    )

    def __init__(self, parent: EmbedBuilderView):
        super().__init__()
        self.parent = parent
        self.color_input.default = f"{parent.builder.color:06X}"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color = int(self.color_input.value.strip().lstrip("#"), 16)
            if not 0 <= color <= 0xFFFFFF:
                raise ValueError("Color fuera del rango RGB")
        except ValueError:
            return await interaction.response.send_message("❌ Color hex inválido.", ephemeral=True)
        self.parent.builder.color = color
        await self.parent._refresh(interaction)


class ImagesModal(discord.ui.Modal, title="Imágenes"):
    image_url = discord.ui.TextInput(
        label="URL de imagen principal", required=False, max_length=500,
    )
    thumbnail_url = discord.ui.TextInput(
        label="URL de thumbnail", required=False, max_length=500,
    )

    def __init__(self, parent: EmbedBuilderView):
        super().__init__()
        self.parent = parent
        if parent.builder.image_url:
            self.image_url.default = parent.builder.image_url
        if parent.builder.thumbnail_url:
            self.thumbnail_url.default = parent.builder.thumbnail_url

    async def on_submit(self, interaction: discord.Interaction):
        self.parent.builder.image_url = self.image_url.value or None
        self.parent.builder.thumbnail_url = self.thumbnail_url.value or None
        await self.parent._refresh(interaction)


class AuthorFooterModal(discord.ui.Modal, title="Autor y Footer"):
    author_name = discord.ui.TextInput(label="Nombre del autor", required=False, max_length=256)
    author_icon = discord.ui.TextInput(label="URL icono del autor", required=False, max_length=500)
    footer_text = discord.ui.TextInput(label="Texto del footer", required=False, max_length=2048)
    footer_icon = discord.ui.TextInput(label="URL icono del footer", required=False, max_length=500)

    def __init__(self, parent: EmbedBuilderView):
        super().__init__()
        self.parent = parent
        if parent.builder.author_name:
            self.author_name.default = parent.builder.author_name
        if parent.builder.author_icon:
            self.author_icon.default = parent.builder.author_icon
        if parent.builder.footer_text:
            self.footer_text.default = parent.builder.footer_text
        if parent.builder.footer_icon:
            self.footer_icon.default = parent.builder.footer_icon

    async def on_submit(self, interaction: discord.Interaction):
        self.parent.builder.author_name = self.author_name.value or None
        self.parent.builder.author_icon = self.author_icon.value or None
        self.parent.builder.footer_text = self.footer_text.value or None
        self.parent.builder.footer_icon = self.footer_icon.value or None
        await self.parent._refresh(interaction)


class FieldModal(discord.ui.Modal, title="Añadir Campo"):
    field_name = discord.ui.TextInput(label="Nombre del campo", max_length=256)
    field_value = discord.ui.TextInput(
        label="Valor del campo", style=discord.TextStyle.paragraph, max_length=1024,
    )
    field_inline = discord.ui.TextInput(
        label="¿En línea? (si/no)", default="no", max_length=3,
    )

    def __init__(self, parent: EmbedBuilderView):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        if len(self.parent.builder.fields) >= 25:
            return await interaction.response.send_message("❌ Máximo 25 campos.", ephemeral=True)
        self.parent.builder.fields.append({
            "name": self.field_name.value,
            "value": self.field_value.value,
            "inline": self.field_inline.value.lower().startswith("s"),
        })
        await self.parent._refresh(interaction)


class URLModal(discord.ui.Modal, title="URL del título"):
    url_input = discord.ui.TextInput(
        label="URL (el título será clickeable)", required=False, max_length=500,
    )

    def __init__(self, parent: EmbedBuilderView):
        super().__init__()
        self.parent = parent
        if parent.builder.url:
            self.url_input.default = parent.builder.url

    async def on_submit(self, interaction: discord.Interaction):
        self.parent.builder.url = self.url_input.value or None
        await self.parent._refresh(interaction)


class SaveEmbedModal(discord.ui.Modal, title="Guardar Embed"):
    embed_name = discord.ui.TextInput(
        label="Nombre para guardar", placeholder="mi-embed-bienvenida",
        max_length=50,
    )

    def __init__(self, parent: EmbedBuilderView):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.parent.interaction_check(interaction):
            return
        name = self.embed_name.value.strip()
        if not name:
            return await interaction.response.send_message("❌ Escribe un nombre para el embed.", ephemeral=True)
        existing = self.parent.cog.db.get_saved_embed_by_name(interaction.guild_id, name)
        if existing:
            return await interaction.response.send_message(
                f"❌ Ya existe un embed con nombre `{name}`.", ephemeral=True,
            )
        self.parent.cog.db.save_embed(
            interaction.guild_id, interaction.user.id,
            name, self.parent.builder.to_json(),
        )
        await interaction.response.send_message(
            f"💾 Embed guardado como `{name}`.", ephemeral=True,
        )


class SendChannelSelectView(discord.ui.View):
    def __init__(self, parent: EmbedBuilderView):
        super().__init__(timeout=60)
        self.parent = parent

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent.interaction_check(interaction)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect, placeholder="Selecciona el canal de destino",
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        min_values=1, max_values=1,
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if not await self.parent.interaction_check(interaction):
            return
        channel = select.values[0]
        resolved = interaction.guild.get_channel(channel.id)
        if not resolved:
            return await interaction.response.send_message("❌ Canal no encontrado.", ephemeral=True)
        actor_perms = resolved.permissions_for(interaction.user)
        if not actor_perms.view_channel or not actor_perms.send_messages:
            return await interaction.response.send_message(
                "❌ No tienes permiso para ver y enviar mensajes en ese canal.", ephemeral=True
            )

        await interaction.response.defer()
        try:
            embed = self.parent.builder.build()
            from cogs._managed_messages import send_managed
            await send_managed(interaction.client, interaction.guild_id, "embeds", resolved.send, embed=embed)
            status = self.parent.build_status_embed(self.parent.builder)
            await interaction.edit_original_response(
                content=f"✅ Embed enviado a {resolved.mention}.",
                embed=status, view=self.parent,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ No tengo permisos para enviar mensajes en {resolved.mention}.", ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Volver", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        status = self.parent.build_status_embed(self.parent.builder)
        await interaction.response.edit_message(content=None, embed=status, view=self.parent)


async def setup(bot: commands.Bot):
    await bot.add_cog(Embeds(bot))
