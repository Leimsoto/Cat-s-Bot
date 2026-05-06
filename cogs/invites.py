"""
cogs/invites.py
───────────────
Sistema de rastreo de invitaciones.
- Mantiene un caché de usos de invitaciones por guild.
- Al entrar un miembro, detecta qué invitación usó y quién la creó.
- Loguea el evento en un canal configurable (#invitaciones).
- Responde automáticamente a DMs redirigiendo a tickets.
- Comandos: /invites stats [usuario], /invites leaderboard, /invites setup [canal]
"""

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class Invites(commands.Cog):
    """Sistema de rastreo de invitaciones."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore
        # guild_id → {code: (uses, inviter, url)}
        self.invites_cache: dict = {}

    async def cog_load(self) -> None:
        """Se llama cuando el cog es cargado — espera a que el bot esté listo."""
        self.bot.loop.create_task(self._wait_and_update())

    async def _wait_and_update(self) -> None:
        await self.bot.wait_until_ready()
        await self.update_all_invites()

    # ── Caché de Invitaciones ────────────────────────────────────────────────

    async def update_all_invites(self) -> None:
        """Actualiza el caché de invitaciones de todos los servidores."""
        for guild in self.bot.guilds:
            try:
                invites = await guild.invites()
                self.invites_cache[guild.id] = {
                    inv.code: (inv.uses or 0, inv.inviter, inv.url) for inv in invites
                }
                logger.debug(
                    "Invitaciones cargadas para %s (%d)", guild.name, len(invites)
                )
            except discord.Forbidden:
                logger.warning("Sin permisos para leer invitaciones en %s", guild.name)
            except Exception as exc:
                logger.error(
                    "Error actualizando invitaciones de %s: %s", guild.name, exc
                )

    # ── Listeners de Invitaciones ────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if not invite.guild:
            return
        gid = invite.guild.id
        if gid not in self.invites_cache:
            self.invites_cache[gid] = {}
        self.invites_cache[gid][invite.code] = (
            invite.uses or 0,
            invite.inviter,
            invite.url,
        )
        logger.debug("Invitación creada: %s en guild %d", invite.code, gid)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild and invite.guild.id in self.invites_cache:
            self.invites_cache[invite.guild.id].pop(invite.code, None)
            logger.debug(
                "Invitación eliminada: %s en guild %d", invite.code, invite.guild.id
            )

    # ── Entrada de miembros ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        used_code: str | None = None
        inviter: discord.User | None = None
        invite_url: str | None = None

        # Detectar qué invitación fue usada comparando el caché
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

                # Actualizar caché con los nuevos usos
                self.invites_cache[guild.id] = {
                    inv.code: (inv.uses or 0, inv.inviter, inv.url)
                    for inv in new_invites
                }
            except discord.Forbidden:
                pass
            except Exception as exc:
                logger.error("Error detectando invitación en %s: %s", guild.name, exc)

        # Registrar en la base de datos
        if inviter and used_code:
            try:
                self.db.record_invite(guild.id, inviter.id, member.id, used_code)
            except Exception as exc:
                logger.error("Error registrando invitación en DB: %s", exc)

        # Loguear en el canal configurado
        await self._log_member_join(member, inviter, used_code, invite_url)

    async def _log_member_join(
        self,
        member: discord.Member,
        inviter: discord.User | None,
        used_code: str | None,
        invite_url: str | None,
    ) -> None:
        """Envía el embed de entrada al canal de log de invitaciones."""
        try:
            cfg = self.db.get_invite_config(member.guild.id)
            if not cfg.get("enabled") or not cfg.get("channel_id"):
                return

            channel = member.guild.get_channel(int(cfg["channel_id"]))
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            inviter_count = 0
            if inviter:
                inviter_count = self.db.get_user_invite_count(
                    member.guild.id, inviter.id
                )

            embed = discord.Embed(
                title="📥 Nuevo miembro",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="👤 Miembro", value=member.mention, inline=True)
            embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
            embed.add_field(
                name="📅 Cuenta creada",
                value=discord.utils.format_dt(member.created_at, style="R"),
                inline=True,
            )

            if inviter:
                embed.add_field(
                    name="💌 Invitado por",
                    value=(
                        f"{inviter.mention} (`{inviter}`) — "
                        f"**{inviter_count}** invitación(es) totales"
                    ),
                    inline=False,
                )
                if used_code:
                    embed.add_field(
                        name="🔗 Código", value=f"`{used_code}`", inline=True
                    )
                if invite_url:
                    embed.add_field(name="🌐 URL", value=invite_url, inline=True)
            else:
                embed.add_field(
                    name="💌 Invitado por",
                    value="Desconocido (invite expirada, vanity URL o integración)",
                    inline=False,
                )

            embed.set_footer(text=f"Miembros totales: {member.guild.member_count}")
            await channel.send(embed=embed)
        except Exception as exc:
            logger.error("Error logueando entrada de miembro: %s", exc)

    # ── Salida de miembros ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Loguea la salida de un miembro en el canal de invitaciones si está configurado."""
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
            embed.add_field(
                name="👤 Miembro", value=f"{member} ({member.mention})", inline=True
            )
            embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
            embed.set_footer(text=f"Miembros totales: {member.guild.member_count}")
            await channel.send(embed=embed)
        except Exception as exc:
            logger.error("Error logueando salida de miembro: %s", exc)

    # ── DMs → Redirigir a tickets ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Responde a mensajes privados redirigiendo al sistema de tickets."""
        # Solo mensajes en DM, de usuarios (no bots)
        if message.guild is not None:
            return
        if message.author.bot:
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

    # ── Comandos Slash ───────────────────────────────────────────────────────

    invite_group = app_commands.Group(
        name="invites",
        description="Sistema de invitaciones — estadísticas y configuración",
    )

    @invite_group.command(
        name="stats", description="Ver estadísticas de invitaciones de un usuario"
    )
    @app_commands.describe(usuario="El usuario a consultar (por defecto tú mismo)")
    async def invite_stats(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member = None,  # type: ignore[assignment]
    ) -> None:
        target = usuario or interaction.user
        count = self.db.get_user_invite_count(interaction.guild_id, target.id)

        embed = discord.Embed(
            title="📊 Estadísticas de Invitaciones",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="👤 Usuario", value=target.mention, inline=True)
        embed.add_field(name="📨 Invitaciones totales", value=str(count), inline=True)
        await interaction.response.send_message(embed=embed)

    @invite_group.command(
        name="leaderboard", description="Top 10 de usuarios que más han invitado"
    )
    async def invite_leaderboard(self, interaction: discord.Interaction) -> None:
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

    @invite_group.command(
        name="setup", description="Configurar el canal de log de invitaciones"
    )
    @app_commands.describe(canal="Canal donde se enviarán los logs de invitaciones")
    @app_commands.checks.has_permissions(administrator=True)
    async def invite_setup(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
    ) -> None:
        self.db.set_invite_config(interaction.guild_id, channel_id=canal.id, enabled=1)
        await interaction.response.send_message(
            f"✅ Canal de log de invitaciones configurado en {canal.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Invites(bot))
