"""
cogs/moderation.py
──────────────────
Cog de moderación completo.

Comandos slash:
  /ban         – Banear usuario
  /tempban     – Banear temporalmente
  /unban       – Desbanear por ID
  /mute        – Silenciar con rol
  /unmute      – Dessilenciar
  /kick        – Expulsar
  /warn        – Advertir (con consecuencias automáticas)
  /warns       – Ver warns de un usuario
  /clearwarns  – Limpiar warns (admin)
  /appeals list – Listar apelaciones

  La configuración se gestiona desde el Dashboard Web.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger("Moderation")


# ── Utilidades de tiempo ──────────────────────────────────────────────────────

def parse_duration(raw: str) -> Optional[int]:
    """
    Convierte un string de tiempo a segundos.
    Acepta: '30s', '5m', '2h', '1d', '1w'
    Sin unidad → se interpreta como minutos.
    """
    if not raw:
        return None
    raw = raw.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    try:
        if raw[-1] in units:
            return int(raw[:-1]) * units[raw[-1]]
        return int(raw) * 60
    except (ValueError, IndexError):
        return None


def fmt_duration(seconds: Optional[int]) -> str:
    """Convierte segundos a texto legible. None → 'Permanente'."""
    if seconds is None:
        return "Permanente ♾️"
    parts = []
    for label, unit in (("sem", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= unit:
            parts.append(f"{seconds // unit}{label}")
            seconds %= unit
    return " ".join(parts) if parts else "0s"


# ── Embed de warn configurable ────────────────────────────────────────────────

def build_warn_embed(
    cfg: dict,
    usuario: discord.Member,
    moderador: discord.Member,
    razon: str,
    warns: int,
) -> discord.Embed:
    """
    Construye el embed de warn.
    Si guild_config.warn_embed_config tiene un JSON válido lo usa;
    de lo contrario aplica el embed por defecto.

    Placeholders disponibles en el JSON:
      {user}       → mención del usuario
      {username}   → nombre del usuario
      {reason}     → razón
      {warns}      → warns actuales
      {moderator}  → nombre del moderador
      {server}     → nombre del servidor
    """
    embed_cfg: Optional[dict] = None
    if cfg.get("warn_embed_config"):
        try:
            embed_cfg = json.loads(cfg["warn_embed_config"])
            if not isinstance(embed_cfg, dict):
                logger.warning("warn_embed_config inválido: no es un objeto JSON")
                embed_cfg = None
        except json.JSONDecodeError:
            logger.warning("warn_embed_config contiene JSON inválido")

    repl = {
        "{user}": usuario.mention,
        "{username}": str(usuario),
        "{reason}": razon,
        "{warns}": str(warns),
        "{moderator}": moderador.display_name,
        "{server}": usuario.guild.name,
    }

    def sub(text: str) -> str:
        for k, v in repl.items():
            text = text.replace(k, v)
        return text

    if embed_cfg:
        raw_color = embed_cfg.get("color", "FFA500").strip("#")
        try:
            color = discord.Color(int(raw_color, 16))
        except ValueError:
            color = discord.Color.orange()

        embed = discord.Embed(
            title=sub(embed_cfg.get("title", "⚠️ Advertencia")),
            description=sub(embed_cfg.get("description", "{user} recibió una advertencia.")),
            color=color,
        )
        for field in embed_cfg.get("fields", []):
            embed.add_field(
                name=sub(field.get("name", "")),
                value=sub(field.get("value", "")),
                inline=field.get("inline", False),
            )
        if embed_cfg.get("footer"):
            embed.set_footer(text=sub(embed_cfg["footer"]))
    else:
        # Embed por defecto
        embed = discord.Embed(
            title="⚠️ Advertencia emitida",
            description=f"{usuario.mention} ha recibido una advertencia.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=moderador.mention, inline=True)
        embed.add_field(name="⚠️ Warns", value=f"`{warns}`", inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.set_footer(text=f"ID usuario: {usuario.id}")

    return embed


# ── Modal para personalizar el embed de warn ──────────────────────────────────

class WarnEmbedModal(discord.ui.Modal, title="Personalizar embed de warn"):
    emb_title = discord.ui.TextInput(
        label="Título",
        default="⚠️ Advertencia",
        max_length=256,
    )
    description = discord.ui.TextInput(
        label="Descripción  →  placeholders disponibles abajo",
        placeholder="{user} {username} {reason} {warns} {moderator} {server}",
        default="{user} recibió una advertencia en **{server}**.",
        style=discord.TextStyle.paragraph,
        max_length=1800,
    )
    color = discord.ui.TextInput(
        label="Color hex (sin #)",
        default="FFA500",
        max_length=8,
        required=False,
    )
    footer = discord.ui.TextInput(
        label="Pie de página",
        default="Moderador: {moderator}  |  Warns totales: {warns}",
        max_length=512,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        cfg_json = json.dumps({
            "title": self.emb_title.value,
            "description": self.description.value,
            "color": self.color.value or "FFA500",
            "footer": self.footer.value,
            "fields": [],
        }, ensure_ascii=False)

        # Guardar en DB
        interaction.client.db.set_config(
            interaction.guild_id, warn_embed_config=cfg_json
        )

        # Vista previa
        guild_cfg = interaction.client.db.get_config(interaction.guild_id)
        preview = build_warn_embed(
            guild_cfg,
            interaction.user,   # type: ignore
            interaction.user,   # type: ignore
            "Esta es una advertencia de ejemplo",
            1,
        )
        await interaction.response.send_message(
            "✅ Embed configurado. **Vista previa:**",
            embed=preview,
            ephemeral=True,
        )


# ── Cog principal ─────────────────────────────────────────────────────────────

class Moderation(commands.Cog):
    """Comandos de moderación: ban, mute, warn, kick y configuración."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore  # inyectado desde main.py
        self._check_mutes.start()

    def cog_unload(self):
        self._check_mutes.cancel()

    # ── Helpers privados ──────────────────────────────────────────────────────

    async def _send_log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        srv_cfg = self.db.get_server_config(guild.id)
        if not srv_cfg.get("modlog_enabled", 1):
            return

        ch_id = srv_cfg.get("modlog_channel")
        if not ch_id:
            return

        channel = guild.get_channel(ch_id)
        if not isinstance(channel, discord.TextChannel):
            logger.warning("Canal de modlog inválido o no accesible en %s (%s)", guild.name, ch_id)
            return

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Sin permisos para enviar logs en %s", guild.name)
        except discord.HTTPException as exc:
            logger.warning("No se pudo enviar modlog en %s: %s", guild.name, exc)

    async def _dm(self, user: discord.Member, embed: discord.Embed, view: Optional[discord.ui.View] = None) -> None:
        try:
            if view:
                await user.send(embed=embed, view=view)
            else:
                await user.send(embed=embed)
        except discord.Forbidden:
            logger.info("No se pudo enviar DM a %s (%s): DMs cerrados o bloqueados", user, user.id)
        except discord.HTTPException as exc:
            logger.warning("Error enviando DM a %s (%s): %s", user, user.id, exc)

    def _has_mod_perms(self, interaction: discord.Interaction, perm_name: str) -> bool:
        user = interaction.user
        if not interaction.guild_id or not isinstance(user, discord.Member):
            return False

        if getattr(user.guild_permissions, "administrator", False):
            return True
        if getattr(user.guild_permissions, perm_name, False):
            return True

        srv = self.db.get_server_config(interaction.guild_id)
        r_ids = [r.id for r in user.roles]
        if srv.get("mod_role_id") in r_ids or srv.get("staff_role_id") in r_ids:
            return True
        return False

    def _can_moderate(
        self, actor: discord.Member, target: discord.Member
    ) -> Optional[str]:
        """
        Verifica jerarquía de roles.
        Retorna None si la acción es válida, o un string de error si no.
        """
        if target.bot:
            return "No puedes moderar a un bot."
        if actor.id == target.id:
            return "No puedes moderarte a ti mismo."
        if target.id == actor.guild.owner_id:
            return "No puedes moderar al dueño del servidor."
        if actor.id != actor.guild.owner_id and actor.top_role <= target.top_role:
            return "Tu rol no es suficientemente alto para moderar a este usuario."
        bot_member = actor.guild.get_member(self.bot.user.id)
        if bot_member and bot_member.top_role <= target.top_role:
            return "Mi rol no es suficiente para moderar a este usuario."
        return None

    # ── Tarea: expiración de mutes ────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def _check_mutes(self):
        """Revisa cada minuto si algún mute temporal ha expirado."""
        try:
            for record in self.db.get_active_mutes():
                try:
                    guild = self.bot.get_guild(record["guild_id"])
                    if not guild:
                        continue

                    member = guild.get_member(record["user_id"])
                    if not member:
                        self.db.clear_mute(record["user_id"], record["guild_id"])
                        continue

                    cfg = self.db.get_config(guild.id)
                    mute_role = guild.get_role(cfg.get("mute_role_id") or 0)
                    if not mute_role or mute_role not in member.roles:
                        self.db.clear_mute(record["user_id"], guild.id)
                        continue

                    try:
                        start = datetime.fromisoformat(record["mute_start"])
                    except (TypeError, ValueError):
                        logger.warning(
                            "Registro de mute inválido para user_id=%s guild_id=%s",
                            record.get("user_id"),
                            record.get("guild_id"),
                        )
                        self.db.clear_mute(record["user_id"], guild.id)
                        continue

                    expiry = start + timedelta(seconds=record["mute_duration"])

                    if datetime.now(timezone.utc) >= expiry:
                        try:
                            await member.remove_roles(
                                mute_role, reason="Mute expirado automáticamente"
                            )
                        except discord.Forbidden:
                            logger.warning("Sin permisos para quitar mute a %s en %s", member, guild.name)
                            continue
                        except discord.HTTPException as exc:
                            logger.warning("Error quitando mute expirado a %s en %s: %s", member, guild.name, exc)
                            continue

                        self.db.clear_mute(record["user_id"], guild.id)
                        self.db.log_action(
                            guild.id, member.id, self.bot.user.id,
                            "AUTO_UNMUTE", "Mute temporal expirado",
                        )

                        log_embed = discord.Embed(
                            title="Mute expirado",
                            description=f"{member.mention} fue desmuteado automáticamente.",
                            color=discord.Color.green(),
                            timestamp=datetime.now(timezone.utc),
                        )
                        log_embed.set_footer(text=f"ID: {member.id}")
                        await self._send_log(guild, log_embed)
                        logger.info("Mute expirado: %s en %s", member, guild.name)

                except Exception as exc:
                    logger.error("Error al expirar mute individual: %s", exc, exc_info=True)
        except Exception as exc:
            logger.error("Error en _check_mutes: %s", exc, exc_info=True)

    @_check_mutes.before_loop
    async def _before_check_mutes(self):
        await self.bot.wait_until_ready()

    # ── Tarea: expiración de tempbans ──────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def _check_tempbans(self):
        """Revisa cada minuto si algún tempban ha expirado."""
        try:
            for record in self.db.get_active_tempbans():
                try:
                    guild = self.bot.get_guild(record["guild_id"])
                    if not guild:
                        self.db.clear_tempban(record["id"])
                        continue

                    start = datetime.fromisoformat(record["ban_start"])
                    expiry = start + timedelta(seconds=record["ban_duration"])

                    if datetime.now(timezone.utc) >= expiry:
                        try:
                            await guild.unban(
                                discord.Object(id=record["user_id"]),
                                reason="Tempban expirado automáticamente",
                            )
                        except discord.NotFound:
                            pass
                        except discord.Forbidden:
                            logger.warning("Sin permisos para desbanear tempban expirado de %s en %s", record["user_id"], guild.name)
                            continue
                        except discord.HTTPException as exc:
                            logger.warning("Error desbaneando tempban expirado %s en %s: %s", record["user_id"], guild.name, exc)
                            continue

                        self.db.clear_tempban(record["id"])
                        self.db.log_action(
                            guild.id, record["user_id"], self.bot.user.id,
                            "AUTO_UNBAN", "Tempban expirado",
                        )

                        log_embed = discord.Embed(
                            title="Tempban expirado",
                            description=f"<@{record['user_id']}> fue desbaneado automáticamente.",
                            color=discord.Color.green(),
                            timestamp=datetime.now(timezone.utc),
                        )
                        log_embed.set_footer(text=f"ID: {record['user_id']}")
                        await self._send_log(guild, log_embed)
                        logger.info("Tempban expirado: %s en %s", record["user_id"], guild.name)

                except Exception as exc:
                    logger.error("Error al expirar tempban individual: %s", exc, exc_info=True)
        except Exception as exc:
            logger.error("Error en _check_tempbans: %s", exc, exc_info=True)

    @_check_tempbans.before_loop
    async def _before_check_tempbans(self):
        await self.bot.wait_until_ready()

    # ─────────────────────────────────────────────────────────────────────────
    # /ban
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Banea a un usuario del servidor")
    @app_commands.describe(
        usuario="Usuario a banear",
        razon="Razón del ban",
        eliminar_mensajes="Días de mensajes a eliminar (0-7, por defecto 0)",
    )
    async def ban(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Sin razón especificada",
        eliminar_mensajes: app_commands.Range[int, 0, 7] = 0,
    ):
        if not self._has_mod_perms(interaction, "ban_members"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)

        err = self._can_moderate(interaction.user, usuario)  # type: ignore
        if err:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)

        await interaction.response.defer()

        # Enviar DM con opción de apelación
        view = AppealUserView(self.bot, interaction.guild_id, "BAN", razon)
        await self._dm(
            usuario,
            discord.Embed(
                title="Has sido baneado",
                description=f"Has sido baneado de **{interaction.guild.name}**.",
                color=discord.Color.dark_red(),
            ).add_field(name="Razón", value=razon)
             .add_field(name="Moderador", value=interaction.user.display_name),
            view=view
        )

        try:
            await usuario.ban(
                reason=f"{razon} | Mod: {interaction.user}",
                delete_message_days=eliminar_mensajes,
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para banear a %s en %s", usuario, interaction.guild)
            return await interaction.followup.send(
                "❌ No tengo permisos suficientes para banear a ese usuario.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error baneando a %s en %s: %s", usuario, interaction.guild, exc)
            return await interaction.followup.send(
                "❌ No se pudo completar el ban. Inténtalo de nuevo.",
                ephemeral=True,
            )

        self.db.log_action(
            interaction.guild_id, usuario.id, interaction.user.id,
            "BAN", razon, {"delete_days": eliminar_mensajes},
        )

        embed = discord.Embed(
            title="Usuario baneado",
            description=f"**{usuario}** ha sido baneado permanentemente.",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Msgs eliminados", value=f"{eliminar_mensajes} día(s)", inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    @ban.error
    async def ban_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /tempban
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="tempban", description="Banea temporalmente a un usuario del servidor")
    @app_commands.describe(
        usuario="Usuario a banear temporalmente",
        duracion="Duración: 30m, 2h, 1d, 1w",
        razon="Razón del tempban",
        eliminar_mensajes="Días de mensajes a eliminar (0-7, por defecto 0)",
    )
    async def tempban(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        duracion: str,
        razon: str = "Sin razón especificada",
        eliminar_mensajes: app_commands.Range[int, 0, 7] = 0,
    ):
        if not self._has_mod_perms(interaction, "ban_members"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)

        err = self._can_moderate(interaction.user, usuario)
        if err:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)

        secs = parse_duration(duracion)
        if secs is None:
            return await interaction.response.send_message(
                "❌ Formato inválido. Ejemplos: `30m` · `2h` · `1d` · `1w`",
                ephemeral=True,
            )

        await interaction.response.defer()

        self.db.set_tempban(
            interaction.guild_id, usuario.id, interaction.user.id,
            razon, secs,
        )

        view = AppealUserView(self.bot, interaction.guild_id, "TEMPBAN", razon)
        await self._dm(
            usuario,
            discord.Embed(
                title="Has sido baneado temporalmente",
                description=f"Has sido baneado temporalmente de **{interaction.guild.name}**.",
                color=discord.Color.dark_red(),
            ).add_field(name="Duración", value=fmt_duration(secs))
             .add_field(name="Razón", value=razon)
             .add_field(name="Moderador", value=interaction.user.display_name),
            view=view
        )

        try:
            await usuario.ban(
                reason=f"Tempban {fmt_duration(secs)} | {razon} | Mod: {interaction.user}",
                delete_message_days=eliminar_mensajes,
            )
        except discord.Forbidden:
            logger.warning("Sin permisos para tempbanear a %s en %s", usuario, interaction.guild)
            return await interaction.followup.send(
                "❌ No tengo permisos suficientes para banear a ese usuario.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error tempbaneando a %s en %s: %s", usuario, interaction.guild, exc)
            return await interaction.followup.send(
                "❌ No se pudo completar el tempban. Inténtalo de nuevo.",
                ephemeral=True,
            )

        self.db.log_action(
            interaction.guild_id, usuario.id, interaction.user.id,
            "TEMPBAN", razon, {"duration_secs": secs, "delete_days": eliminar_mensajes},
        )

        embed = discord.Embed(
            title="Usuario baneado temporalmente",
            description=f"**{usuario}** ha sido baneado por **{fmt_duration(secs)}**.",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="⏱️ Duración", value=fmt_duration(secs), inline=True)
        embed.add_field(name="Msgs eliminados", value=f"{eliminar_mensajes} día(s)", inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=secs)
        embed.add_field(name="Expira", value=f"<t:{int(expiry.timestamp())}:R>", inline=False)

        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    @tempban.error
    async def tempban_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /unban
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="unban", description="Desbanea un usuario usando su ID")
    @app_commands.describe(
        user_id="ID numérica del usuario a desbanear",
        razon="Razón del desbaneo",
    )
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "ban_members"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)

        await interaction.response.defer()

        try:
            uid = int(user_id.strip())
        except ValueError:
            return await interaction.followup.send("❌ ID inválida.", ephemeral=True)

        try:
            entry = await interaction.guild.fetch_ban(discord.Object(id=uid))
        except discord.NotFound:
            return await interaction.followup.send(
                f"❌ No existe un ban activo con ID `{uid}`.", ephemeral=True
            )

        try:
            await interaction.guild.unban(entry.user, reason=f"{razon} | Mod: {interaction.user}")
        except discord.Forbidden:
            logger.warning("Sin permisos para desbanear a %s en %s", entry.user, interaction.guild)
            return await interaction.followup.send(
                "❌ No tengo permisos suficientes para desbanear a ese usuario.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error desbaneando a %s en %s: %s", entry.user, interaction.guild, exc)
            return await interaction.followup.send(
                "❌ No se pudo completar el desbaneo. Inténtalo de nuevo.",
                ephemeral=True,
            )

        self.db.log_action(interaction.guild_id, uid, interaction.user.id, "UNBAN", razon)

        embed = discord.Embed(
            title="✅ Usuario desbaneado",
            description=f"**{entry.user}** fue desbaneado.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=entry.user.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{entry.user.mention}\n`{uid}`", inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    @unban.error
    async def unban_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /kick
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="kick", description="Expulsa a un usuario del servidor")
    @app_commands.describe(usuario="Usuario a expulsar", razon="Razón de la expulsión")
    async def kick(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "kick_members"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)

        err = self._can_moderate(interaction.user, usuario)  # type: ignore
        if err:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)

        await interaction.response.defer()

        view = AppealUserView(self.bot, interaction.guild_id, "KICK", razon)
        await self._dm(
            usuario,
            discord.Embed(
                title="Has sido expulsado",
                description=f"Has sido expulsado de **{interaction.guild.name}**.",
                color=discord.Color.orange(),
            ).add_field(name="Razón", value=razon)
             .add_field(name="Moderador", value=interaction.user.display_name),
            view=view
        )

        try:
            await usuario.kick(reason=f"{razon} | Mod: {interaction.user}")
        except discord.Forbidden:
            logger.warning("Sin permisos para expulsar a %s en %s", usuario, interaction.guild)
            return await interaction.followup.send(
                "❌ No tengo permisos suficientes para expulsar a ese usuario.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error expulsando a %s en %s: %s", usuario, interaction.guild, exc)
            return await interaction.followup.send(
                "❌ No se pudo completar la expulsión. Inténtalo de nuevo.",
                ephemeral=True,
            )

        self.db.log_action(interaction.guild_id, usuario.id, interaction.user.id, "KICK", razon)

        embed = discord.Embed(
            title="Usuario expulsado",
            description=f"**{usuario}** fue expulsado del servidor.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=usuario.display_avatar.url)
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        await interaction.followup.send(embed=embed)
        await self._send_log(interaction.guild, embed)

    @kick.error
    async def kick_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /mute
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="mute", description="Silencia a un usuario con el rol de mute configurado")
    @app_commands.describe(
        usuario="Usuario a silenciar",
        duracion="Duración: 30m, 2h, 1d, 1w — omitir para permanente",
        razon="Razón del mute",
    )
    async def mute(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        duracion: Optional[str] = None,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "manage_roles"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)
        cfg = self.db.get_config(interaction.guild_id)
        mute_role = interaction.guild.get_role(cfg.get("mute_role_id") or 0)

        if not mute_role:
            return await interaction.response.send_message(
                "❌ No hay rol de mute configurado.\n"
                "Usa `/modconfig mute_role` para asignarlo.",
                ephemeral=True,
            )

        err = self._can_moderate(interaction.user, usuario)  # type: ignore
        if err:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)

        if mute_role in usuario.roles:
            return await interaction.response.send_message(
                f"⚠️ {usuario.mention} ya está silenciado.", ephemeral=True
            )

        secs: Optional[int] = None
        if duracion:
            secs = parse_duration(duracion)
            if secs is None:
                return await interaction.response.send_message(
                    "❌ Formato inválido. Ejemplos: `30m` · `2h` · `1d` · `1w`",
                    ephemeral=True,
                )

        try:
            await usuario.add_roles(mute_role, reason=f"Mute: {razon} | Mod: {interaction.user}")
        except discord.Forbidden:
            logger.warning("Sin permisos para mutear a %s en %s", usuario, interaction.guild)
            return await interaction.response.send_message(
                "❌ No tengo permisos suficientes para aplicar el rol de mute.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error muteando a %s en %s: %s", usuario, interaction.guild, exc)
            return await interaction.response.send_message(
                "❌ No se pudo completar el mute. Inténtalo de nuevo.",
                ephemeral=True,
            )

        self.db.set_mute(usuario.id, interaction.guild_id, secs)
        self.db.log_action(
            interaction.guild_id, usuario.id, interaction.user.id,
            "MUTE", razon, {"duration_secs": secs},
        )

        embed = discord.Embed(
            title="Usuario silenciado",
            description=f"{usuario.mention} ha sido silenciado.",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=f"{usuario.mention}\n`{usuario.id}`", inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="⏱️ Duración", value=fmt_duration(secs), inline=True)
        if secs:
            expiry = datetime.now(timezone.utc) + timedelta(seconds=secs)
            embed.add_field(name="Expira", value=f"<t:{int(expiry.timestamp())}:R>", inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        await interaction.response.send_message(embed=embed)
        await self._send_log(interaction.guild, embed)

        view = AppealUserView(self.bot, interaction.guild_id, "MUTE", razon)
        await self._dm(
            usuario,
            discord.Embed(
                title="Has sido silenciado",
                description=f"Has sido silenciado en **{interaction.guild.name}**.",
                color=discord.Color.red(),
            ).add_field(name="Duración", value=fmt_duration(secs))
             .add_field(name="Razón", value=razon),
            view=view
        )

    @mute.error
    async def mute_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /unmute
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="unmute", description="Quita el silencio a un usuario")
    @app_commands.describe(usuario="Usuario a desilenciar", razon="Razón del unmute")
    async def unmute(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "manage_roles"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)
        cfg = self.db.get_config(interaction.guild_id)
        mute_role = interaction.guild.get_role(cfg.get("mute_role_id") or 0)

        if not mute_role:
            return await interaction.response.send_message(
                "❌ No hay rol de mute configurado.", ephemeral=True
            )

        if mute_role not in usuario.roles:
            return await interaction.response.send_message(
                f"⚠️ {usuario.mention} no está silenciado.", ephemeral=True
            )

        try:
            await usuario.remove_roles(mute_role, reason=f"Unmute: {razon} | Mod: {interaction.user}")
        except discord.Forbidden:
            logger.warning("Sin permisos para quitar mute a %s en %s", usuario, interaction.guild)
            return await interaction.response.send_message(
                "❌ No tengo permisos suficientes para quitar el rol de mute.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.warning("Error quitando mute a %s en %s: %s", usuario, interaction.guild, exc)
            return await interaction.response.send_message(
                "❌ No se pudo completar el unmute. Inténtalo de nuevo.",
                ephemeral=True,
            )

        self.db.clear_mute(usuario.id, interaction.guild_id)
        self.db.log_action(interaction.guild_id, usuario.id, interaction.user.id, "UNMUTE", razon)

        embed = discord.Embed(
            title="Usuario desilenciado",
            description=f"{usuario.mention} fue desilenciado.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=usuario.mention, inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        await interaction.response.send_message(embed=embed)
        await self._send_log(interaction.guild, embed)

        await self._dm(
            usuario,
            discord.Embed(
                title="Fuiste desilenciado",
                description=f"Tu silencio en **{interaction.guild.name}** fue levantado.",
                color=discord.Color.green(),
            ).add_field(name="Razón", value=razon),
        )

    @unmute.error
    async def unmute_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /warn
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="Advierte a un usuario (con consecuencias configurables)")
    @app_commands.describe(usuario="Usuario a advertir", razon="Razón de la advertencia")
    async def warn(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "moderate_members"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)
        err = self._can_moderate(interaction.user, usuario)  # type: ignore
        if err:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)

        await interaction.response.defer()

        cfg = self.db.get_config(interaction.guild_id)
        warns = self.db.add_warn(usuario.id, interaction.guild_id)
        self.db.log_action(
            interaction.guild_id, usuario.id, interaction.user.id, "WARN", razon
        )

        # Embed de warn (configurable)
        warn_embed = build_warn_embed(cfg, usuario, interaction.user, razon, warns)  # type: ignore
        await interaction.followup.send(embed=warn_embed)
        await self._send_log(interaction.guild, warn_embed)
        
        view = AppealUserView(self.bot, interaction.guild_id, "WARN", razon)
        await self._dm(usuario, warn_embed, view=view)

        # ── Consecuencias automáticas (de mayor a menor severidad) ────────────

        ban_thr   = cfg.get("warn_ban_threshold", 7)
        kick_thr  = cfg.get("warn_kick_threshold", 5)
        mute_thr  = cfg.get("warn_mute_threshold", 3)
        ban_on    = bool(cfg.get("warn_ban_enabled", 0))
        kick_on   = bool(cfg.get("warn_kick_enabled", 0))
        mute_on   = bool(cfg.get("warn_mute_enabled", 1))

        consequence_embed: Optional[discord.Embed] = None

        # Ban automático
        if ban_on and warns >= ban_thr:
            try:
                await usuario.ban(reason=f"Auto-ban: alcanzó {warns} warns")
                self.db.log_action(
                    interaction.guild_id, usuario.id, self.bot.user.id,
                    "AUTO_BAN", f"Alcanzó {warns} warns",
                )
                consequence_embed = discord.Embed(
                    title="Ban automático",
                    description=f"{usuario.mention} fue baneado por alcanzar **{warns} warns**.",
                    color=discord.Color.dark_red(),
                    timestamp=datetime.now(timezone.utc),
                )
            except discord.Forbidden:
                logger.warning("Sin permisos para auto-ban de %s", usuario)

        # Kick automático (solo si no se baneó)
        elif kick_on and warns >= kick_thr:
            try:
                await usuario.kick(reason=f"Auto-kick: alcanzó {warns} warns")
                self.db.log_action(
                    interaction.guild_id, usuario.id, self.bot.user.id,
                    "AUTO_KICK", f"Alcanzó {warns} warns",
                )
                consequence_embed = discord.Embed(
                    title="Kick automático",
                    description=f"{usuario.mention} fue expulsado por alcanzar **{warns} warns**.",
                    color=discord.Color.dark_orange(),
                    timestamp=datetime.now(timezone.utc),
                )
            except discord.Forbidden:
                logger.warning("Sin permisos para auto-kick de %s", usuario)

        # Mute automático (solo si no se baneó ni kickeó)
        elif mute_on and warns >= mute_thr:
            mute_role = interaction.guild.get_role(cfg.get("mute_role_id") or 0)
            if mute_role and mute_role not in usuario.roles:
                dur = cfg.get("warn_mute_duration", 3600)
                try:
                    await usuario.add_roles(
                        mute_role, reason=f"Auto-mute: alcanzó {warns} warns"
                    )
                    self.db.set_mute(usuario.id, interaction.guild_id, dur)
                    self.db.log_action(
                        interaction.guild_id, usuario.id, self.bot.user.id,
                        "AUTO_MUTE", f"Alcanzó {warns} warns", {"duration_secs": dur},
                    )
                    consequence_embed = discord.Embed(
                        title="Mute automático",
                        description=(
                            f"{usuario.mention} fue silenciado por alcanzar **{warns} warns**.\n"
                            f"Duración: **{fmt_duration(dur)}**"
                        ),
                        color=discord.Color.red(),
                        timestamp=datetime.now(timezone.utc),
                    )
                except discord.Forbidden:
                    logger.warning("Sin permisos para auto-mute de %s", usuario)
            elif not mute_role:
                logger.warning("Auto-mute ignorado: no hay rol de mute configurado")

        if consequence_embed:
            await interaction.followup.send(embed=consequence_embed)
            await self._send_log(interaction.guild, consequence_embed)

    @warn.error
    async def warn_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /warns
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="warns", description="Consulta los warns de un usuario")
    @app_commands.describe(usuario="Usuario a consultar (por defecto tú mismo)")
    async def warns_cmd(
        self,
        interaction: discord.Interaction,
        usuario: Optional[discord.Member] = None,
    ):
        target = usuario or interaction.user
        record = self.db.get_user(target.id, interaction.guild_id)  # type: ignore
        cfg = self.db.get_config(interaction.guild_id)

        w = record["warns"]
        thresholds = {
            "Mute": (cfg.get("warn_mute_threshold", 3), bool(cfg.get("warn_mute_enabled", 1))),
            "Kick": (cfg.get("warn_kick_threshold", 5), bool(cfg.get("warn_kick_enabled", 0))),
            "Ban":  (cfg.get("warn_ban_threshold", 7),  bool(cfg.get("warn_ban_enabled", 0))),
        }
        max_t = max(v[0] for v in thresholds.values())
        ratio = w / max_t if max_t else 0
        color = (
            discord.Color.green() if ratio == 0
            else discord.Color.yellow() if ratio < 0.5
            else discord.Color.orange() if ratio < 0.8
            else discord.Color.red()
        )

        embed = discord.Embed(
            title=f"Warns de {target.display_name}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="⚠️ Warns actuales", value=f"**{w}**", inline=True)

        next_enabled_thresholds = [t for t, en in thresholds.values() if en and t > w]
        next_threshold = min(next_enabled_thresholds) if next_enabled_thresholds else None

        lines = []
        for name, (thr, enabled) in thresholds.items():
            icon = "✅" if enabled else "❌"
            marker = " ← próximo" if enabled and next_threshold is not None and thr == next_threshold else ""
            lines.append(f"{icon} **{name}** a los {thr} warns{marker}")

        embed.add_field(name="Consecuencias configuradas", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"ID: {target.id}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────────
    # /clearwarns
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="clearwarns", description="Limpia todos los warns de un usuario")
    @app_commands.describe(usuario="Usuario al que limpiar los warns", razon="Razón del reseteo")
    async def clearwarns(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str = "Sin razón especificada",
    ):
        if not self._has_mod_perms(interaction, "administrator"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)
        record = self.db.get_user(usuario.id, interaction.guild_id)
        old = record["warns"]

        if old == 0:
            return await interaction.response.send_message(
                f"ℹ️ {usuario.mention} no tiene warns.", ephemeral=True
            )

        self.db.clear_warns(usuario.id, interaction.guild_id)
        self.db.log_action(
            interaction.guild_id, usuario.id, interaction.user.id,
            "CLEAR_WARNS", razon, {"removed": old},
        )

        embed = discord.Embed(
            title="Warns limpiados",
            description=f"Se eliminaron **{old}** warn(s) de {usuario.mention}.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Usuario", value=usuario.mention, inline=True)
        embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)

        await interaction.response.send_message(embed=embed)
        await self._send_log(interaction.guild, embed)

    @clearwarns.error
    async def clearwarns_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_perm_error(interaction, error)

    # ─────────────────────────────────────────────────────────────────────────
    # /purge
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="purge", description="Elimina mensajes en masa del canal actual")
    @app_commands.describe(
        cantidad="Número de mensajes a eliminar (1-1000)",
        usuario="Eliminar solo mensajes de este usuario (opcional)",
    )
    async def purge(
        self,
        interaction: discord.Interaction,
        cantidad: app_commands.Range[int, 1, 1000],
        usuario: Optional[discord.Member] = None,
    ):
        if not self._has_mod_perms(interaction, "manage_messages"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        try:
            if usuario:
                def check(msg):
                    return msg.author.id == usuario.id
                deleted = await interaction.channel.purge(limit=cantidad, check=check, bulk=True)
            else:
                deleted = await interaction.channel.purge(limit=cantidad, bulk=True)
        except discord.Forbidden:
            return await interaction.followup.send("❌ No tengo permisos para eliminar mensajes.", ephemeral=True)
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"❌ Error al purgar: {exc}", ephemeral=True)

        await interaction.followup.send(
            f"✅ Eliminados **{len(deleted)}** mensajes.", ephemeral=True
        )

    # ─────────────────────────────────────────────────────────────────────────
    # /appeals
    # ─────────────────────────────────────────────────────────────────────────

    appeals_group = app_commands.Group(name="appeals", description="Gestión de apelaciones")

    @appeals_group.command(name="list", description="Lista las apelaciones pendientes del servidor")
    @app_commands.describe(
        estado="Filtrar por estado: PENDING (por defecto), ACCEPTED, DENIED",
    )
    async def appeals_list(
        self,
        interaction: discord.Interaction,
        estado: Optional[str] = None,
    ):
        if not self._has_mod_perms(interaction, "moderate_members"):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)

        status_filter = (estado or "PENDING").upper()
        if status_filter not in ("PENDING", "ACCEPTED", "DENIED"):
            return await interaction.response.send_message(
                "❌ Estado inválido. Usa: `PENDING`, `ACCEPTED` o `DENIED`.",
                ephemeral=True,
            )

        appeals = self.db.get_appeals_by_guild(interaction.guild_id, status_filter)

        if not appeals:
            return await interaction.response.send_message(
                f"📭 No hay apelaciones con estado **{status_filter}**.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title=f"Apelaciones • {status_filter}",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Total: {len(appeals)}")

        for a in appeals[:10]:
            user = self.bot.get_user(a["user_id"])
            user_name = f"{user}" if user else f"`{a['user_id']}`"
            embed.add_field(
                name=f"#{a['id']} — {user_name}",
                value=(
                    f"**Sanción:** {a['action_type']}\n"
                    f"**Estado:** {a['status']}\n"
                    f"**Razón:** {a['reason'][:100]}\n"
                    f"**Creada:** <t:{int(datetime.fromisoformat(a['created_at']).timestamp())}:R>"
                ),
                inline=False,
            )

        if len(appeals) > 10:
            embed.description = f"Mostrando las 10 más recientes de {len(appeals)} totales."

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────────
    # /modconfig  — ELIMINADO
    # La configuración de moderación se gestiona desde el Dashboard Web.
    # ─────────────────────────────────────────────────────────────────────────

    # ── Manejador de errores de permisos ──────────────────────────────────────

    async def _handle_perm_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            msg = f"❌ Te faltan permisos: `{', '.join(error.missing_permissions)}`"
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = f"❌ Al bot le faltan permisos: `{', '.join(error.missing_permissions)}`"
        else:
            logger.error("Error en comando de moderación: %s", error, exc_info=True)
            msg = "❌ Error inesperado. Revisa los logs del bot."

        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


# ── Views y Modals para /modconfig ────────────────────────────────────────────
# ELIMINADOS: ModConfigView, MuteRoleSelectView, MuteDurationConfigModal,
# ThresholdsConfigModal, ConsequencesToggleView
# → Configuración migrada al Dashboard Web


# ── Appeals UI ────────────────────────────────────────────────────────────────

class AppealUserModal(discord.ui.Modal, title="Apelar Sanción"):
    appeal_text = discord.ui.TextInput(
        label="¿Por qué deberíamos retirar tu sanción?",
        style=discord.TextStyle.paragraph,
        placeholder="Explica tu situación detalladamente...",
        required=True,
        max_length=1000
    )

    def __init__(self, bot: commands.Bot, guild_id: int, action_type: str, reason: str):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.action_type = action_type
        self.reason = reason

    async def on_submit(self, interaction: discord.Interaction):
        db = getattr(self.bot, 'db')
        appeal_id = db.create_appeal(
            self.guild_id, interaction.user.id, self.action_type, self.reason, self.appeal_text.value
        )
        await interaction.response.send_message("✅ Tu apelación ha sido enviada al equipo de moderación. Recibirás un DM con la respuesta.", ephemeral=True)

        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            logger.warning("No se pudo registrar apelación %s: guild %s no disponible", appeal_id, self.guild_id)
            return

        srv_cfg = db.get_server_config(self.guild_id)
        modlog_id = srv_cfg.get("modlog_channel")
        if not modlog_id:
            logger.warning("No se pudo registrar apelación %s: modlog_channel no configurado", appeal_id)
            return

        modlog = guild.get_channel(modlog_id)
        if not isinstance(modlog, discord.TextChannel):
            logger.warning("No se pudo registrar apelación %s: modlog_channel inválido (%s)", appeal_id, modlog_id)
            return

        embed = discord.Embed(
            title="Nueva Apelación Recibida",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Usuario", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Sanción", value=self.action_type, inline=True)
        embed.add_field(name="Razón Original", value=self.reason, inline=True)
        embed.add_field(name="Defensa del Usuario", value=self.appeal_text.value, inline=False)
        embed.set_footer(text=f"ID Apelación: {appeal_id}")
        
        try:
            await modlog.send(embed=embed, view=AppealModView(self.bot, appeal_id, interaction.user.id, self.action_type))
        except discord.Forbidden:
            logger.warning("Sin permisos para publicar apelación %s en modlog", appeal_id)
        except discord.HTTPException as exc:
            logger.warning("Error enviando apelación %s a modlog: %s", appeal_id, exc)


class AppealUserView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, action_type: str, reason: str):
        super().__init__(timeout=86400)
        self.bot = bot
        self.guild_id = guild_id
        self.action_type = action_type
        self.reason = reason

    @discord.ui.button(label="Apelar Sanción", style=discord.ButtonStyle.primary, emoji="📝")
    async def appeal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AppealUserModal(self.bot, self.guild_id, self.action_type, self.reason))
        button.disabled = True
        if interaction.message:
            try:
                await interaction.message.edit(view=self)
            except (discord.Forbidden, discord.HTTPException) as exc:
                logger.debug("No se pudo deshabilitar botón de apelación: %s", exc)


class AppealAcceptModal(discord.ui.Modal, title="Aceptar Apelación"):
    mod_reason = discord.ui.TextInput(
        label="Mensaje para el usuario",
        style=discord.TextStyle.paragraph,
        placeholder="Ej: Se retirará tu sanción porque...",
        required=True
    )
    auto_remove = discord.ui.TextInput(
        label="¿Quitar sanción automáticamente? (SI/NO)",
        style=discord.TextStyle.short,
        default="SI",
        required=True
    )

    def __init__(self, bot: commands.Bot, appeal_id: int, user_id: int, action_type: str):
        super().__init__()
        self.bot = bot
        self.appeal_id = appeal_id
        self.user_id = user_id
        self.action_type = action_type

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = getattr(self.bot, 'db')
        db.update_appeal_status(self.appeal_id, "ACCEPTED")
        guild = interaction.guild
        member = guild.get_member(self.user_id) if guild else None
        recipient = member or self.bot.get_user(self.user_id)

        auto_text = self.auto_remove.value.strip().upper()
        if auto_text == "SI" and guild:
            try:
                if self.action_type in ("BAN", "TEMPBAN"):
                    await guild.unban(discord.Object(id=self.user_id), reason=f"Apelación Aceptada por {interaction.user}")
                    db.clear_tempbans_for_user(self.user_id, guild.id)
                elif self.action_type == "MUTE":
                    mem = guild.get_member(self.user_id)
                    cfg = db.get_config(guild.id)
                    mute_role = guild.get_role(cfg.get("mute_role_id") or 0)
                    if mem and mute_role and mute_role in mem.roles:
                        await mem.remove_roles(mute_role, reason=f"Apelación Aceptada por {interaction.user}")
                    db.clear_mute(self.user_id, guild.id)
            except discord.Forbidden:
                logger.warning("Sin permisos para retirar sanción automáticamente en apelación %s", self.appeal_id)
            except discord.HTTPException as exc:
                logger.warning("Error quitando sanción automáticamente en apelación %s: %s", self.appeal_id, exc)

        if recipient and guild:
            embed = discord.Embed(
                title="✅ Apelación Aceptada",
                description=f"Tu apelación en **{guild.name}** ha sido aceptada.",
                color=discord.Color.green()
            )
            embed.add_field(name="Sanción Original", value=self.action_type)
            embed.add_field(name="Mensaje del Moderador", value=self.mod_reason.value, inline=False)
            try:
                await recipient.send(embed=embed)
            except discord.Forbidden:
                logger.info("No se pudo notificar por DM la apelación aceptada a %s", self.user_id)
            except discord.HTTPException as exc:
                logger.warning("Error notificando apelación aceptada a %s: %s", self.user_id, exc)

        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0].copy()
            embed.color = discord.Color.green()
            embed.title = "✅ Apelación Aceptada"
            embed.add_field(name="Moderador", value=interaction.user.mention, inline=False)
            embed.add_field(name="Motivo de Aceptación", value=self.mod_reason.value, inline=False)
            await interaction.message.edit(embed=embed, view=None)

        await interaction.followup.send("Apelación aceptada.", ephemeral=True)


class AppealDenyModal(discord.ui.Modal, title="Denegar Apelación"):
    mod_reason = discord.ui.TextInput(
        label="Mensaje para el usuario",
        style=discord.TextStyle.paragraph,
        placeholder="Ej: Tu apelación ha sido denegada porque...",
        required=True
    )

    def __init__(self, bot: commands.Bot, appeal_id: int, user_id: int, action_type: str):
        super().__init__()
        self.bot = bot
        self.appeal_id = appeal_id
        self.user_id = user_id
        self.action_type = action_type

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = getattr(self.bot, 'db')
        db.update_appeal_status(self.appeal_id, "DENIED")
        guild = interaction.guild
        member = guild.get_member(self.user_id) if guild else None
        recipient = member or self.bot.get_user(self.user_id)

        if recipient and guild:
            embed = discord.Embed(
                title="❌ Apelación Denegada",
                description=f"Tu apelación en **{guild.name}** ha sido denegada.",
                color=discord.Color.red()
            )
            embed.add_field(name="Sanción Original", value=self.action_type)
            embed.add_field(name="Mensaje del Moderador", value=self.mod_reason.value, inline=False)
            try:
                await recipient.send(embed=embed)
            except discord.Forbidden:
                logger.info("No se pudo notificar por DM la apelación denegada a %s", self.user_id)
            except discord.HTTPException as exc:
                logger.warning("Error notificando apelación denegada a %s: %s", self.user_id, exc)

        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0].copy()
            embed.color = discord.Color.red()
            embed.title = "❌ Apelación Denegada"
            embed.add_field(name="Moderador", value=interaction.user.mention, inline=False)
            embed.add_field(name="Motivo de Denegación", value=self.mod_reason.value, inline=False)
            await interaction.message.edit(embed=embed, view=None)

        await interaction.followup.send("Apelación denegada.", ephemeral=True)


class AppealModView(discord.ui.View):
    def __init__(self, bot: commands.Bot, appeal_id: int = 0, user_id: int = 0, action_type: str = "UNKNOWN"):
        super().__init__(timeout=None)
        self.bot = bot
        self.appeal_id = appeal_id
        self.user_id = user_id
        self.action_type = action_type

    @staticmethod
    def _parse_embed(interaction: discord.Interaction) -> tuple:
        """Extrae (appeal_id, user_id, action_type) del embed del mensaje."""
        appeal_id, user_id, action_type = 0, 0, "UNKNOWN"
        if not (interaction.message and interaction.message.embeds):
            return appeal_id, user_id, action_type
        embed = interaction.message.embeds[0]
        # Footer: "ID Apelación: N"
        if embed.footer and embed.footer.text:
            try:
                appeal_id = int(embed.footer.text.split("ID Apelación:")[-1].strip())
            except (ValueError, IndexError):
                pass
        for field in embed.fields:
            if field.name == "Sanción":
                action_type = field.value or "UNKNOWN"
            elif field.name == "Usuario" and field.value:
                # Formato: "mención (`ID`)"
                try:
                    user_id = int(field.value.split("`")[1])
                except (IndexError, ValueError):
                    pass
        return appeal_id, user_id, action_type

    @discord.ui.button(label="Aceptar", style=discord.ButtonStyle.success, emoji="✅", custom_id="appeal_accept")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        appeal_id, user_id, action_type = self._parse_embed(interaction)
        if not appeal_id:
            appeal_id, user_id, action_type = self.appeal_id, self.user_id, self.action_type
        await interaction.response.send_modal(AppealAcceptModal(self.bot, appeal_id, user_id, action_type))

    @discord.ui.button(label="Denegar", style=discord.ButtonStyle.danger, emoji="❌", custom_id="appeal_deny")
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        appeal_id, user_id, action_type = self._parse_embed(interaction)
        if not appeal_id:
            appeal_id, user_id, action_type = self.appeal_id, self.user_id, self.action_type
        await interaction.response.send_modal(AppealDenyModal(self.bot, appeal_id, user_id, action_type))



async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
    # Registrar AppealModView como vista persistente (botones con custom_id fijos)
    # Los datos del appeal se extraen del embed al interactuar
    bot.add_view(AppealModView(bot))
