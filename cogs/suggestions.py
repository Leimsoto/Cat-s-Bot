"""
cogs/suggestions.py
───────────────────
Sistema de sugerencias con review opcional, votación per-user, cooldown y
límites configurables. Vistas persistentes registradas en `setup`.

Flujo:
  1. Usuario escribe en submit_channel → bot borra el msg
  2. Si min_length/max_length OK y cooldown respetado:
     a) Si `auto_publish=1` → directo a public_channel con votación
     b) Si no → review_channel para staff
  3. Staff aprueba → public_channel
     o deniega (con razón) → status=DENIED guardado en DB

Configuración (canales, min/max, cooldown, auto_publish): se gestiona desde
el panel web (página "Sugerencias"). Este cog solo expone listeners e
interacciones.
"""

import json
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


# ── Vistas persistentes ──────────────────────────────────────────────────────

class SuggestionPublicView(discord.ui.View):
    """Vista persistente de votación. Resuelve suggestion_id desde el footer."""

    def __init__(self, cog: "Suggestions"):
        super().__init__(timeout=None)
        self.cog = cog

    def _get_id(self, interaction: discord.Interaction) -> int | None:
        try:
            footer = interaction.message.embeds[0].footer.text or ""
            for part in footer.split("·"):
                part = part.strip()
                if part.startswith("ID:"):
                    return int(part.split("ID:")[-1].strip())
        except (IndexError, ValueError, AttributeError):
            pass
        return None

    async def _vote(self, interaction: discord.Interaction, vote: int):
        sid = self._get_id(interaction)
        if sid is None:
            return await interaction.response.send_message(
                "❌ No se pudo identificar la sugerencia.", ephemeral=True
            )
        counts = self.cog.db.cast_vote(sid, interaction.user.id, vote)

        embed = interaction.message.embeds[0]
        for idx, field in enumerate(embed.fields):
            if "Votos" in field.name:
                embed.set_field_at(
                    idx,
                    name="Votos",
                    value=f"A favor: **{counts['upvotes']}**\nEn contra: **{counts['downvotes']}**",
                    inline=False,
                )
                break
        else:
            embed.add_field(
                name="Votos",
                value=f"A favor: **{counts['upvotes']}**\nEn contra: **{counts['downvotes']}**",
                inline=False,
            )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="A favor", emoji="👍", style=discord.ButtonStyle.success, custom_id="sugg_upvote")
    async def upvote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, 1)

    @discord.ui.button(label="En contra", emoji="👎", style=discord.ButtonStyle.danger, custom_id="sugg_downvote")
    async def downvote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, -1)


class DenyReasonModal(discord.ui.Modal, title="Razón de denegación"):
    reason = discord.ui.TextInput(
        label="Razón (visible para el autor)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    def __init__(self, cog: "Suggestions", suggestion_id: int):
        super().__init__()
        self.cog = cog
        self.suggestion_id = suggestion_id

    async def on_submit(self, interaction: discord.Interaction):
        text = (self.reason.value or "").strip() or None
        self.cog.db.update_suggestion(self.suggestion_id, status="DENIED", denial_reason=text)
        old_embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        old_embed.color = discord.Color.red()
        old_embed.title = "Sugerencia DENEGADA"
        if text:
            old_embed.add_field(name="Razón", value=text, inline=False)
        await interaction.response.edit_message(embed=old_embed, view=None)


class SuggestionReviewView(discord.ui.View):
    """Vista persistente para staff. Resuelve suggestion_id desde el footer."""

    def __init__(self, cog: "Suggestions"):
        super().__init__(timeout=None)
        self.cog = cog

    def _get_id(self, interaction: discord.Interaction) -> int | None:
        try:
            footer = interaction.message.embeds[0].footer.text or ""
            for part in footer.split("·"):
                part = part.strip()
                if part.startswith("ID:"):
                    return int(part.split("ID:")[-1].strip())
        except (IndexError, ValueError, AttributeError):
            pass
        return None

    @discord.ui.button(label="Aprobar", style=discord.ButtonStyle.success, custom_id="sugg_approve")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        sid = self._get_id(interaction)
        if sid is None:
            return await interaction.response.send_message("❌ ID no resuelto.", ephemeral=True)
        await self.cog.publish_suggestion(interaction, sid)

    @discord.ui.button(label="Denegar", style=discord.ButtonStyle.danger, custom_id="sugg_deny")
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        sid = self._get_id(interaction)
        if sid is None:
            return await interaction.response.send_message("❌ ID no resuelto.", ephemeral=True)
        await interaction.response.send_modal(DenyReasonModal(self.cog, sid))


# ── Cog ───────────────────────────────────────────────────────────────────────

class Suggestions(commands.Cog):
    """Sistema de sugerencias con review opcional + votación per-user."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def publish_suggestion(self, interaction: discord.Interaction, suggestion_id: int):
        """Publica una sugerencia en el canal público (desde aprobación o auto-publish)."""
        row = self.db.get_suggestion(suggestion_id)
        if not row:
            return await interaction.response.send_message("❌ Sugerencia no encontrada.", ephemeral=True)

        cfg = self.db.get_suggestions_config(interaction.guild_id) or {}
        public_ch = interaction.guild.get_channel(int(cfg.get("public_channel_id") or 0))
        if not public_ch:
            return await interaction.response.send_message(
                "❌ Canal público no configurado o no encontrado.", ephemeral=True
            )

        user = interaction.guild.get_member(int(row["user_id"]))
        username = user.display_name if user else f"Usuario {row['user_id']}"
        avatar_url = user.display_avatar.url if user else None

        embed = discord.Embed(
            title="Nueva sugerencia",
            description=row["content"],
            color=discord.Color.teal(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=f"Sugerencia de {username}", icon_url=avatar_url)
        embed.add_field(name="Votos", value="A favor: **0**\nEn contra: **0**", inline=False)
        embed.set_footer(text=f"Sugerencia para {interaction.guild.name} · ID: {suggestion_id}")

        try:
            msg = await public_ch.send(embed=embed, view=SuggestionPublicView(self))
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Sin permisos en el canal público.", ephemeral=True)

        self.db.update_suggestion(suggestion_id, status="ACCEPTED", message_id=msg.id)

        if interaction.message and interaction.message.embeds:
            old = interaction.message.embeds[0]
            old.color = discord.Color.green()
            old.title = "Sugerencia APROBADA"
            await interaction.response.edit_message(embed=old, view=None)
        else:
            await interaction.response.send_message("✅ Sugerencia publicada.", ephemeral=True)

    # ── Listener: capta sugerencias del canal de envío ───────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        cfg = self.db.get_suggestions_config(message.guild.id)
        if not cfg or not int(cfg.get("enabled", 1) or 0):
            return
        if message.channel.id != int(cfg.get("submit_channel_id") or 0):
            return

        content = (message.content or "").strip()
        min_len = int(cfg.get("min_length") or 10)
        max_len = int(cfg.get("max_length") or 2000)
        cooldown = int(cfg.get("cooldown_seconds") or 300)

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        if len(content) < min_len:
            await self._dm_or_reply(
                message, f"❌ Tu sugerencia es muy corta. Mínimo {min_len} caracteres."
            )
            return
        if len(content) > max_len:
            await self._dm_or_reply(
                message, f"❌ Tu sugerencia es muy larga. Máximo {max_len} caracteres."
            )
            return

        # Cooldown
        if cooldown > 0:
            last_iso = self.db.get_last_user_suggestion_ts(message.guild.id, message.author.id)
            if last_iso:
                try:
                    last_dt = datetime.fromisoformat(last_iso)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                    if elapsed < cooldown:
                        remain = int(cooldown - elapsed)
                        await self._dm_or_reply(
                            message,
                            f"⏳ Espera **{remain}s** antes de enviar otra sugerencia.",
                        )
                        return
                except Exception:
                    pass

        sugg_id = self.db.create_suggestion(message.guild.id, message.author.id, content)

        if int(cfg.get("auto_publish") or 0):
            await self._auto_publish_from_listener(message, cfg, sugg_id, content)
        else:
            await self._send_to_review(message, cfg, sugg_id, content)

    async def _dm_or_reply(self, source: discord.Message, text: str):
        try:
            await source.author.send(text)
        except discord.HTTPException:
            try:
                await source.channel.send(f"{source.author.mention} {text}", delete_after=10)
            except discord.HTTPException:
                pass

    async def _auto_publish_from_listener(self, message, cfg, sugg_id, content):
        public_ch = message.guild.get_channel(int(cfg.get("public_channel_id") or 0))
        if not public_ch:
            return
        embed = discord.Embed(
            title="Nueva sugerencia",
            description=content,
            color=discord.Color.teal(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name=f"Sugerencia de {message.author.display_name}",
            icon_url=message.author.display_avatar.url,
        )
        embed.add_field(name="Votos", value="A favor: **0**\nEn contra: **0**", inline=False)
        embed.set_footer(text=f"Sugerencia para {message.guild.name} · ID: {sugg_id}")
        try:
            msg = await public_ch.send(embed=embed, view=SuggestionPublicView(self))
            self.db.update_suggestion(sugg_id, status="ACCEPTED", message_id=msg.id)
        except discord.Forbidden:
            logger.warning("Sin permisos para publicar sugerencia en %s", public_ch.name)

    async def _send_to_review(self, message, cfg, sugg_id, content):
        review_ch = message.guild.get_channel(int(cfg.get("review_channel_id") or 0))
        if not review_ch:
            return
        embed = discord.Embed(
            title="Sugerencia PENDIENTE",
            description=content,
            color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name=f"Sugerencia de {message.author.display_name}",
            icon_url=message.author.display_avatar.url,
        )
        embed.set_footer(text=f"ID: {sugg_id}")
        try:
            await review_ch.send(embed=embed, view=SuggestionReviewView(self))
        except discord.Forbidden:
            logger.warning("Sin permisos en review_channel de %s", message.guild.name)


async def setup(bot: commands.Bot):
    cog = Suggestions(bot)
    await bot.add_cog(cog)
    # Vistas persistentes (resuelven suggestion_id desde el footer)
    bot.add_view(SuggestionPublicView(cog))
    bot.add_view(SuggestionReviewView(cog))
