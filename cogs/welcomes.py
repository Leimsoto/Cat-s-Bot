"""
cogs/welcomes.py
────────────────
Sistema unificado de Bienvenidas + Boosters + Rastreo de Invitaciones.

Listeners:
  • on_invite_create / on_invite_delete  – mantienen caché de usos por guild
  • on_member_join                       – envía welcome + detecta invitador + log canal
  • on_member_remove                     – log de salida en canal de invitaciones
  • on_member_update                     – agradecimiento a Boosters (premium_since)
  • on_message (DM)                      – redirige a tickets

Comandos slash:
  /configurar bienvenidas <canal> <nombre_embed>
  /configurar boosters    <canal> <nombre_embed> <gif_url>
  /invites stats          [usuario]
  /invites leaderboard
  /invites setup          <canal>

Configuración persistente: panel web → Bienvenidas (tabs Bienvenidas/Boosters/Invitaciones)
"""

import json
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class Welcomes(commands.Cog):
    """Bienvenidas, agradecimiento a boosters y rastreo de invitaciones."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore
        # guild_id → {code: (uses, inviter, url)}
        self.invites_cache: dict = {}

    async def cog_load(self) -> None:
        self.bot.loop.create_task(self._wait_and_update_invites())

    async def _wait_and_update_invites(self) -> None:
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                invites = await guild.invites()
                self.invites_cache[guild.id] = {
                    inv.code: (inv.uses or 0, inv.inviter, inv.url) for inv in invites
                }
            except discord.Forbidden:
                logger.warning("Sin permisos para leer invitaciones en %s", guild.name)
            except Exception as exc:
                logger.error("Error cacheando invitaciones de %s: %s", guild.name, exc)

    # ── Caché de invitaciones ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if not invite.guild:
            return
        gid = invite.guild.id
        self.invites_cache.setdefault(gid, {})
        self.invites_cache[gid][invite.code] = (
            invite.uses or 0,
            invite.inviter,
            invite.url,
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild and invite.guild.id in self.invites_cache:
            self.invites_cache[invite.guild.id].pop(invite.code, None)

    # ── Entrada de miembros ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild

        # Detectar qué invitación fue usada comparando el caché.
        used_code: str | None = None
        inviter: discord.User | None = None
        invite_url: str | None = None

        if guild.id in self.invites_cache:
            try:
                new_invites = await guild.invites()
                cached = self.invites_cache[guild.id]
                for inv in new_invites:
                    old_uses = cached.get(inv.code, (0, None, None))[0]
                    if (inv.uses or 0) > old_uses:
                        used_code = inv.code
                        inviter = inv.inviter
                        invite_url = inv.url
                        break
                self.invites_cache[guild.id] = {
                    inv.code: (inv.uses or 0, inv.inviter, inv.url)
                    for inv in new_invites
                }
            except discord.Forbidden:
                pass
            except Exception as exc:
                logger.error("Error detectando invitación en %s: %s", guild.name, exc)

        # Persistir invitación.
        if inviter and used_code:
            try:
                self.db.record_invite(guild.id, inviter.id, member.id, used_code)
            except Exception as exc:
                logger.error("Error registrando invitación en DB: %s", exc)

        # Log canal de invitaciones.
        await self._log_member_join(member, inviter, used_code, invite_url)

        # Mensaje de bienvenida.
        await self._send_welcome(member, inviter)

    async def _send_welcome(
        self,
        member: discord.Member,
        inviter: discord.User | None,
    ) -> None:
        guild = member.guild
        cfg = self.db.get_welcome_config(guild.id)
        if not cfg.get("enabled") or not cfg.get("channel_id"):
            return

        channel = guild.get_channel(int(cfg["channel_id"]))
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        embed_data = cfg.get("embed_data")
        if not embed_data:
            return

        try:
            data = json.loads(embed_data)
            title = (
                data.get("title", "")
                .replace("{user}", member.display_name)
                .replace("{server}", guild.name)
            )
            desc = (
                data.get("description", "")
                .replace("{user}", member.mention)
                .replace("{server}", guild.name)
                .replace("{count}", str(guild.member_count or 0))
            )
            if inviter:
                desc += f"\n\n💌 Invitado por: {inviter.mention}"

            embed = discord.Embed(
                title=title or None,
                description=desc or None,
                color=discord.Color(int(data.get("color", 0x5865F2))),
                timestamp=datetime.now(timezone.utc) if data.get("timestamp") else None,
            )
            if data.get("image_url"):
                embed.set_image(url=data["image_url"])
            if data.get("thumbnail_url"):
                embed.set_thumbnail(url=member.display_avatar.url)
            if data.get("footer_text"):
                embed.set_footer(
                    text=data["footer_text"], icon_url=data.get("footer_icon")
                )

            await channel.send(content=member.mention, embed=embed)
        except Exception as exc:
            logger.error("Error enviando bienvenida: %s", exc)

    async def _log_member_join(
        self,
        member: discord.Member,
        inviter: discord.User | None,
        used_code: str | None,
        invite_url: str | None,
    ) -> None:
        try:
            cfg = self.db.get_invite_config(member.guild.id)
            if not cfg.get("enabled") or not cfg.get("channel_id"):
                return
            channel = member.guild.get_channel(int(cfg["channel_id"]))
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            inviter_count = (
                self.db.get_user_invite_count(member.guild.id, inviter.id)
                if inviter
                else 0
            )

            embed = discord.Embed(
                title="📥 Nuevo miembro",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Miembro", value=member.mention, inline=True)
            embed.add_field(name="ID", value=str(member.id), inline=True)
            embed.add_field(
                name="Cuenta creada",
                value=discord.utils.format_dt(member.created_at, style="R"),
                inline=True,
            )

            if inviter:
                embed.add_field(
                    name="Invitado por",
                    value=(
                        f"{inviter.mention} (`{inviter}`) — "
                        f"**{inviter_count}** invitación(es) totales"
                    ),
                    inline=False,
                )
                if used_code:
                    embed.add_field(name="Código", value=f"`{used_code}`", inline=True)
                if invite_url:
                    embed.add_field(name="URL", value=invite_url, inline=True)
            else:
                embed.add_field(
                    name="Invitado por",
                    value="Desconocido (vanity URL, integración o invite expirada)",
                    inline=False,
                )

            embed.set_footer(text=f"Miembros totales: {member.guild.member_count}")
            await channel.send(embed=embed)
        except Exception as exc:
            logger.error("Error logueando entrada de miembro: %s", exc)

    # ── Salida de miembros ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        try:
            cfg = self.db.get_invite_config(member.guild.id)
            if not cfg.get("enabled") or not cfg.get("channel_id"):
                return
            channel = member.guild.get_channel(int(cfg["channel_id"]))
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            embed = discord.Embed(
                title="📤 Miembro salió",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Miembro", value=f"{member} ({member.mention})", inline=True)
            embed.add_field(name="ID", value=str(member.id), inline=True)
            embed.set_footer(text=f"Miembros totales: {member.guild.member_count}")
            await channel.send(embed=embed)
        except Exception as exc:
            logger.error("Error logueando salida de miembro: %s", exc)

    # ── Boosters ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.premium_since is None and after.premium_since is not None:
            cfg = self.db.get_boost_config(after.guild.id)
            if not cfg.get("enabled") or not cfg.get("channel_id"):
                return
            channel = after.guild.get_channel(int(cfg["channel_id"]))
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            embed_data = cfg.get("embed_data")
            gif_url = cfg.get("gif_url")
            if not embed_data:
                return
            try:
                data = json.loads(embed_data)
                title = data.get("title", "¡Nuevo Booster!").replace(
                    "{user}", after.display_name
                )
                desc = data.get(
                    "description", "Gracias por mejorar nuestro servidor, te amamos."
                ).replace("{user}", after.mention)

                embed = discord.Embed(
                    title=title,
                    description=desc,
                    color=discord.Color.purple(),
                )
                if gif_url:
                    embed.set_image(url=gif_url)
                await channel.send(content=after.mention, embed=embed)
            except Exception as exc:
                logger.error("Error enviando agradecimiento de boost: %s", exc)

    # ── DMs → redirigir a tickets ────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is not None or message.author.bot:
            return
        try:
            await message.channel.send(
                "⚠️ **Por política del servidor**, no se atienden solicitudes de soporte por DM.\n"
                "Usa el sistema de **tickets** en el servidor para recibir ayuda del staff."
            )
        except discord.Forbidden:
            pass
        except Exception as exc:
            logger.error("Error respondiendo DM de %s: %s", message.author, exc)

    # ── Slash: welcome config ────────────────────────────────────────────────

    welcome_group = app_commands.Group(
        name="welcome", description="Configurar el sistema de bienvenidas"
    )

    @welcome_group.command(name="channel", description="Establece el canal de bienvenidas")
    @app_commands.describe(canal="Canal de texto para las bienvenidas")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_channel(self, interaction: discord.Interaction, canal: discord.TextChannel):
        self.db.set_welcome_config(interaction.guild_id, channel_id=canal.id)
        await interaction.response.send_message(
            f"✅ Canal de bienvenidas establecido a {canal.mention}.", ephemeral=True
        )

    @welcome_group.command(name="toggle", description="Activa o desactiva las bienvenidas")
    @app_commands.describe(activado="True para activar, False para desactivar")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_toggle(self, interaction: discord.Interaction, activado: bool):
        self.db.set_welcome_config(interaction.guild_id, enabled=1 if activado else 0)
        estado = "✅ Activadas" if activado else "❌ Desactivadas"
        await interaction.response.send_message(f"{estado} las bienvenidas.", ephemeral=True)

    @welcome_group.command(name="test", description="Envía un mensaje de prueba de bienvenida")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_test(self, interaction: discord.Interaction):
        await self._send_welcome(interaction.user, None)
        await interaction.response.send_message(
            "✅ Mensaje de bienvenida de prueba enviado.", ephemeral=True
        )

    # ── Slash: boost config ──────────────────────────────────────────────────

    boost_group = app_commands.Group(
        name="boost", description="Configurar el agradecimiento a boosters"
    )

    @boost_group.command(name="channel", description="Establece el canal de agradecimiento a boosters")
    @app_commands.describe(canal="Canal de texto para los boosteos")
    @app_commands.checks.has_permissions(administrator=True)
    async def boost_channel(self, interaction: discord.Interaction, canal: discord.TextChannel):
        self.db.set_boost_config(interaction.guild_id, channel_id=canal.id)
        await interaction.response.send_message(
            f"✅ Canal de boosters establecido a {canal.mention}.", ephemeral=True
        )

    @boost_group.command(name="toggle", description="Activa o desactiva los mensajes de boost")
    @app_commands.describe(activado="True para activar, False para desactivar")
    @app_commands.checks.has_permissions(administrator=True)
    async def boost_toggle(self, interaction: discord.Interaction, activado: bool):
        self.db.set_boost_config(interaction.guild_id, enabled=1 if activado else 0)
        estado = "✅ Activados" if activado else "❌ Desactivados"
        await interaction.response.send_message(f"{estado} los mensajes de boost.", ephemeral=True)

    # ── Slash: invites ───────────────────────────────────────────────────────

    invite_group = app_commands.Group(
        name="invites",
        description="Sistema de invitaciones — estadísticas y configuración",
    )

    @invite_group.command(name="stats", description="Ver estadísticas de invitaciones de un usuario")
    @app_commands.describe(usuario="El usuario a consultar (por defecto tú mismo)")
    async def invite_stats(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member = None,  # type: ignore[assignment]
    ):
        target = usuario or interaction.user
        count = self.db.get_user_invite_count(interaction.guild_id, target.id)
        embed = discord.Embed(
            title="📊 Estadísticas de Invitaciones",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Usuario", value=target.mention, inline=True)
        embed.add_field(name="Invitaciones totales", value=str(count), inline=True)
        await interaction.response.send_message(embed=embed)

    @invite_group.command(name="leaderboard", description="Top 10 de usuarios que más han invitado")
    async def invite_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = self.db.get_invite_leaderboard(interaction.guild_id, limit=10)
        embed = discord.Embed(
            title="🏆 Leaderboard de Invitaciones",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        if not rows:
            embed.description = "No hay datos de invitaciones registrados aún."
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, row in enumerate(rows):
                inviter_id = row["inviter_id"]
                total = row["total"]
                member = (
                    interaction.guild.get_member(inviter_id)
                    if interaction.guild
                    else None
                )
                name = member.display_name if member else f"Usuario `{inviter_id}`"
                prefix = medals[i] if i < 3 else f"**{i + 1}.**"
                lines.append(f"{prefix} {name} — **{total}** invitaciones")
            embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Welcomes(bot))
