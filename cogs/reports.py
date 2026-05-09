"""
cogs/reports.py
───────────────
Sistema de reportes de usuarios integrado con tickets.

Comandos:
  /report @usuario razon   — Reporta a un usuario (cualquier miembro)
  /reports list            — Lista reportes pendientes [staff/admin]
  /reports view id         — Ver un reporte específico [staff/admin]

Flujo:
  1. Usuario reporta con /report
  2. Se crea registro en DB
  3. Si el servidor tiene tickets → crea ticket automático
  4. Si no → envía embed al modlog_channel
  5. Staff puede marcar RESOLVED / DISMISSED desde los botones
"""

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


# ── Views ─────────────────────────────────────────────────────────────────────

class ReportActionView(discord.ui.View):
    """
    Vista persistente para gestionar reportes desde el modlog.
    El report_id se resuelve siempre desde el footer del embed
    (formato `ID: <n>`) — una sola instancia sirve para todos los reportes.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Resolver", style=discord.ButtonStyle.success, emoji="✅",
                       custom_id="report_resolve")
    async def resolve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        report_id = self._get_report_id(interaction)
        if report_id is None:
            return await interaction.response.send_message("❌ No se pudo determinar el ID del reporte.", ephemeral=True)
        interaction.client.db.update_report(report_id, status="RESOLVED")
        await self._mark_done(interaction, "RESUELTO", discord.Color.green())

    @discord.ui.button(label="Desestimar", style=discord.ButtonStyle.secondary, emoji="🚫",
                       custom_id="report_dismiss")
    async def dismiss_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        report_id = self._get_report_id(interaction)
        if report_id is None:
            return await interaction.response.send_message("❌ No se pudo determinar el ID del reporte.", ephemeral=True)
        interaction.client.db.update_report(report_id, status="DISMISSED")
        await self._mark_done(interaction, "DESESTIMADO", discord.Color.greyple())

    def _get_report_id(self, interaction: discord.Interaction) -> int | None:
        """Extrae el ID del reporte del footer del embed (`ID: <n>`)."""
        try:
            if interaction.message and interaction.message.embeds:
                footer = interaction.message.embeds[0].footer.text or ""
                return int(footer.split("ID:")[-1].split("·")[0].strip())
        except (ValueError, IndexError, AttributeError):
            pass
        return None

    async def _mark_done(self, interaction: discord.Interaction, label: str, color: discord.Color):
        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = color
            embed.set_footer(text=f"Estado: {label} · {embed.footer.text}")
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message(f"✅ Reporte marcado como {label}.", ephemeral=True)
        self.stop()


# ── Cog ───────────────────────────────────────────────────────────────────────

class Reports(commands.Cog):
    """Sistema de reportes integrado con tickets."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    def _is_staff(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        srv_cfg = self.db.get_server_config(member.guild.id)
        mod_role = srv_cfg.get("mod_role_id")
        staff_role = srv_cfg.get("staff_role_id")
        check_ids = {rid for rid in (mod_role, staff_role) if rid}
        if not check_ids:
            return False
        return any(r.id in check_ids for r in member.roles)

    async def _send_to_modlog(self, guild: discord.Guild, embed: discord.Embed, report_id: int) -> None:
        """Envía el embed al canal de modlog si está configurado."""
        srv_cfg = self.db.get_server_config(guild.id)
        modlog_id = srv_cfg.get("modlog_channel")
        if not modlog_id:
            return
        channel = guild.get_channel(int(modlog_id))
        if channel and isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=embed, view=ReportActionView())
            except discord.Forbidden:
                logger.warning(f"Sin permisos para enviar reporte al modlog en {guild.name}")

    async def _create_ticket_for_report(self, interaction: discord.Interaction,
                                         reported: discord.Member, reason: str, report_id: int) -> bool:
        """Intenta crear un ticket automático para el reporte. Devuelve True si lo logró."""
        tickets_cog = self.bot.get_cog("Tickets")
        if not tickets_cog:
            return False

        config = self.db.get_ticket_config(interaction.guild_id)
        if not config or not config.get("category_id"):
            return False

        # Usar primera categoría disponible o crear un ticket genérico
        categories = self.db.get_ticket_categories(interaction.guild_id)
        if not categories:
            return False

        cat = categories[0]  # primera categoría disponible
        answers = [
            f"Usuario reportado: {reported.mention} (`{reported.id}`)",
            f"Motivo: {reason}",
            f"ID del reporte: #{report_id}",
        ]
        try:
            await tickets_cog.create_ticket_channel(interaction, cat, answers)
            return True
        except Exception as e:
            logger.warning(f"Error creando ticket para reporte: {e}")
            return False

    # ── Comandos ──────────────────────────────────────────────────────────────

    @app_commands.command(name="report", description="Reporta a un usuario del servidor al staff")
    @app_commands.describe(
        usuario="Usuario a reportar",
        razon="Motivo del reporte (sé específico)",
    )
    async def report_user(self, interaction: discord.Interaction,
                          usuario: discord.Member, razon: str):
        if usuario.id == interaction.user.id:
            return await interaction.response.send_message(
                "❌ No puedes reportarte a ti mismo.", ephemeral=True
            )
        if usuario.bot:
            return await interaction.response.send_message(
                "❌ No puedes reportar a un bot.", ephemeral=True
            )
        if usuario.guild_permissions.administrator:
            return await interaction.response.send_message(
                "❌ No puedes reportar a un administrador.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        # Crear registro en DB
        report_id = self.db.create_report(
            interaction.guild_id,
            interaction.user.id,
            usuario.id,
            razon,
        )

        # Embed del reporte
        embed = discord.Embed(
            title="🚨 Nuevo Reporte",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Reportado por", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Usuario", value=f"{usuario.mention} (`{usuario.id}`)", inline=True)
        embed.add_field(name="Sanción", value="Reporte", inline=True)
        embed.add_field(name="Motivo", value=razon, inline=False)
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.set_footer(text=f"ID: {report_id}")

        # Intentar crear ticket primero
        ticket_created = await self._create_ticket_for_report(interaction, usuario, razon, report_id)

        if not ticket_created:
            # Fallback: enviar al modlog
            await self._send_to_modlog(interaction.guild, embed, report_id)

        await interaction.followup.send(
            f"✅ Tu reporte contra **{usuario.display_name}** ha sido enviado al staff (Reporte #{report_id}).\n"
            "El equipo de moderación lo revisará pronto.",
            ephemeral=True,
        )

    reports_group = app_commands.Group(
        name="reports",
        description="Gestión de reportes [staff]",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @reports_group.command(name="list", description="Lista reportes del servidor")
    @app_commands.describe(estado="Filtrar por estado")
    @app_commands.choices(estado=[
        app_commands.Choice(name="Pendientes", value="PENDING"),
        app_commands.Choice(name="Resueltos", value="RESOLVED"),
        app_commands.Choice(name="Desestimados", value="DISMISSED"),
        app_commands.Choice(name="Todos", value="ALL"),
    ])
    async def reports_list(self, interaction: discord.Interaction, estado: str = "PENDING"):
        if not self._is_staff(interaction.user):
            return await interaction.response.send_message("❌ Solo el staff puede ver los reportes.", ephemeral=True)

        status_filter = None if estado == "ALL" else estado
        reports = self.db.get_reports(interaction.guild_id, status_filter)

        if not reports:
            return await interaction.response.send_message(
                f"📭 No hay reportes con estado **{estado}**.", ephemeral=True
            )

        embed = discord.Embed(
            title=f"🚨 Reportes — {estado}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )

        status_emoji = {"PENDING": "⏳", "RESOLVED": "✅", "DISMISSED": "🚫"}

        for r in reports[:10]:  # max 10 por embed
            reported = interaction.guild.get_member(int(r["reported_user_id"]))
            reported_text = reported.display_name if reported else f"ID:{r['reported_user_id']}"
            emoji = status_emoji.get(r["status"], "❓")
            embed.add_field(
                name=f"{emoji} #{r['id']} — {reported_text}",
                value=f"Motivo: {r['reason'][:80]}\nFecha: `{str(r['created_at'])[:10]}`",
                inline=False,
            )

        if len(reports) > 10:
            embed.set_footer(text=f"Mostrando 10 de {len(reports)} reportes. Usa /reports view para ver uno específico.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reports_group.command(name="view", description="Ver detalle de un reporte por ID")
    @app_commands.describe(id_reporte="ID del reporte")
    async def reports_view(self, interaction: discord.Interaction, id_reporte: int):
        if not self._is_staff(interaction.user):
            return await interaction.response.send_message("❌ Solo el staff puede ver los reportes.", ephemeral=True)

        reports = self.db.get_reports(interaction.guild_id)
        report = next((r for r in reports if int(r["id"]) == id_reporte), None)
        if not report:
            return await interaction.response.send_message(
                f"❌ No se encontró el reporte #{id_reporte} en este servidor.", ephemeral=True
            )

        reporter = interaction.guild.get_member(int(report["reporter_id"]))
        reported = interaction.guild.get_member(int(report["reported_user_id"]))

        status_emoji = {"PENDING": "⏳ Pendiente", "RESOLVED": "✅ Resuelto", "DISMISSED": "🚫 Desestimado"}

        embed = discord.Embed(
            title=f"🚨 Reporte #{report['id']}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Reportado por", value=reporter.mention if reporter else f"ID:{report['reporter_id']}", inline=True)
        embed.add_field(name="Acusado", value=reported.mention if reported else f"ID:{report['reported_user_id']}", inline=True)
        embed.add_field(name="Estado", value=status_emoji.get(report["status"], report["status"]), inline=True)
        embed.add_field(name="Motivo", value=report["reason"], inline=False)
        embed.add_field(name="Fecha", value=f"`{str(report['created_at'])[:16].replace('T', ' ')}`", inline=True)
        if report.get("ticket_id"):
            embed.add_field(name="Ticket", value=f"#{report['ticket_id']}", inline=True)
        embed.set_footer(text=f"ID: {report['id']}")

        if report["status"] == "PENDING":
            await interaction.response.send_message(embed=embed, view=ReportActionView(), ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = Reports(bot)
    await bot.add_cog(cog)
    bot.add_view(ReportActionView())  # vista persistente: resuelve report_id desde el embed
