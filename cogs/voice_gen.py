"""
cogs/voice_gen.py
─────────────────
Generador dinámico de canales de voz (JTC — Join To Create).

Flujo:
  1. El admin configura un canal "hub" desde el dashboard.
  2. Cuando alguien se conecta al hub → se crea un VC nuevo con el nombre
     "{username}'s VC" en la categoría configurada.
  3. El bot mueve al usuario al VC recién creado.
  4. Se envía un panel de control (mensaje con botones) al canal de panel
     configurado (o al propio VC si tiene chat de texto).
  5. El owner puede gestionar su canal con los botones del panel.
  6. Cuando el VC queda vacío → se elimina automáticamente.
"""

import asyncio
import logging
import time

import discord
from discord.ext import commands, tasks
from discord import app_commands

logger = logging.getLogger(__name__)

# ─── Helpers ────────────────────────────────────────────────────────────────

def _channel_owner(db, channel_id: int) -> int | None:
    row = db.get_voice_gen_channel(channel_id)
    return row["owner_id"] if row else None


async def _assert_owner(interaction: discord.Interaction, db) -> bool:
    owner_id = _channel_owner(db, getattr(interaction.user.voice.channel, "id", 0) if interaction.user.voice else 0)
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ Debes estar en tu canal de voz.", ephemeral=True)
        return False
    channel_id = interaction.user.voice.channel.id
    owner_id = _channel_owner(db, channel_id)
    if owner_id != interaction.user.id:
        await interaction.response.send_message("❌ Solo el dueño del canal puede hacer esto.", ephemeral=True)
        return False
    return True


# ─── Panel de control: botones ───────────────────────────────────────────────

class VCControlView(discord.ui.View):
    """Vista persistente con todos los controles del VC."""

    def __init__(self, cog: "VoiceGen"):
        super().__init__(timeout=None)
        self.cog = cog

    # ── Fila 1: Visibilidad ──────────────────────────────────────────────────

    @discord.ui.button(emoji="🔒", label="Bloquear", style=discord.ButtonStyle.secondary, custom_id="vc:lock", row=0)
    async def lock(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        vc = interaction.user.voice.channel
        await vc.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message("🔒 Canal bloqueado.", ephemeral=True)

    @discord.ui.button(emoji="🔓", label="Desbloquear", style=discord.ButtonStyle.secondary, custom_id="vc:unlock", row=0)
    async def unlock(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        vc = interaction.user.voice.channel
        await vc.set_permissions(interaction.guild.default_role, connect=None)
        await interaction.response.send_message("🔓 Canal desbloqueado.", ephemeral=True)

    @discord.ui.button(emoji="🫥", label="Ocultar", style=discord.ButtonStyle.secondary, custom_id="vc:hide", row=0)
    async def hide(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        vc = interaction.user.voice.channel
        await vc.set_permissions(interaction.guild.default_role, view_channel=False)
        await interaction.response.send_message("🫥 Canal oculto.", ephemeral=True)

    @discord.ui.button(emoji="👁️", label="Mostrar", style=discord.ButtonStyle.secondary, custom_id="vc:unhide", row=0)
    async def unhide(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        vc = interaction.user.voice.channel
        await vc.set_permissions(interaction.guild.default_role, view_channel=None)
        await interaction.response.send_message("👁️ Canal visible.", ephemeral=True)

    # ── Fila 2: Usuarios ────────────────────────────────────────────────────

    @discord.ui.button(emoji="👥", label="Límite", style=discord.ButtonStyle.secondary, custom_id="vc:limit", row=1)
    async def limit(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        await interaction.response.send_modal(LimitModal(self.cog))

    @discord.ui.button(emoji="📩", label="Invitar", style=discord.ButtonStyle.secondary, custom_id="vc:invite", row=1)
    async def invite(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        vc = interaction.user.voice.channel
        inv = await vc.create_invite(max_age=3600, max_uses=10)
        await interaction.response.send_message(f"📩 Enlace de invitación (expira en 1h, máx. 10 usos):\n{inv.url}", ephemeral=True)

    @discord.ui.button(emoji="🚫", label="Banear", style=discord.ButtonStyle.danger, custom_id="vc:ban", row=1)
    async def ban(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        await interaction.response.send_modal(BanModal(self.cog))

    @discord.ui.button(emoji="✅", label="Permitir", style=discord.ButtonStyle.success, custom_id="vc:permit", row=1)
    async def permit(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        await interaction.response.send_modal(PermitModal(self.cog))

    # ── Fila 3: Canal ───────────────────────────────────────────────────────

    @discord.ui.button(emoji="✏️", label="Renombrar", style=discord.ButtonStyle.secondary, custom_id="vc:rename", row=2)
    async def rename(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        await interaction.response.send_modal(RenameModal(self.cog))

    @discord.ui.button(emoji="🎵", label="Bitrate", style=discord.ButtonStyle.secondary, custom_id="vc:bitrate", row=2)
    async def bitrate(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        await interaction.response.send_modal(BitrateModal(self.cog))

    @discord.ui.button(emoji="🌍", label="Región", style=discord.ButtonStyle.secondary, custom_id="vc:region", row=2)
    async def region(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        await interaction.response.send_modal(RegionModal(self.cog))

    # ── Fila 4: Propiedad ────────────────────────────────────────────────────

    @discord.ui.button(emoji="👑", label="Ceder", style=discord.ButtonStyle.primary, custom_id="vc:transfer", row=3)
    async def transfer(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await _assert_owner(interaction, self.cog.db): return
        await interaction.response.send_modal(TransferModal(self.cog))

    @discord.ui.button(emoji="🏴", label="Reclamar", style=discord.ButtonStyle.primary, custom_id="vc:claim", row=3)
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Debes estar en un canal de voz.", ephemeral=True)
            return
        vc = interaction.user.voice.channel
        row = self.cog.db.get_voice_gen_channel(vc.id)
        if not row:
            await interaction.response.send_message("❌ Este canal no es un VC generado.", ephemeral=True)
            return
        # Solo se puede reclamar si el dueño actual NO está en el canal
        current_owner_in_vc = any(m.id == row["owner_id"] for m in vc.members)
        if current_owner_in_vc:
            await interaction.response.send_message("❌ El dueño actual aún está en el canal.", ephemeral=True)
            return
        self.cog.db.update_voice_gen_channel_owner(vc.id, interaction.user.id)
        await vc.edit(name=f"{interaction.user.display_name}'s VC")
        await interaction.response.send_message(f"👑 ¡Ahora eres el dueño de **{vc.name}**!", ephemeral=True)


# ─── Modales ────────────────────────────────────────────────────────────────

class LimitModal(discord.ui.Modal, title="Límite de usuarios"):
    limit = discord.ui.TextInput(label="Máximo de usuarios (0 = ilimitado)", placeholder="0–99", max_length=2)

    def __init__(self, cog): super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = int(self.limit.value)
            if not 0 <= n <= 99: raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Valor inválido (0–99).", ephemeral=True)
        await interaction.user.voice.channel.edit(user_limit=n)
        await interaction.response.send_message(f"👥 Límite establecido: **{n if n else 'ilimitado'}**.", ephemeral=True)


class RenameModal(discord.ui.Modal, title="Renombrar canal"):
    name = discord.ui.TextInput(label="Nuevo nombre", max_length=100)

    def __init__(self, cog): super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.user.voice.channel.edit(name=self.name.value)
        await interaction.response.send_message(f"✏️ Canal renombrado a **{self.name.value}**.", ephemeral=True)


class BitrateModal(discord.ui.Modal, title="Bitrate de audio"):
    bitrate = discord.ui.TextInput(label="Bitrate en kbps (8–384)", placeholder="96", max_length=3)

    def __init__(self, cog): super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = int(self.bitrate.value)
            if not 8 <= n <= 384: raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Valor inválido (8–384).", ephemeral=True)
        await interaction.user.voice.channel.edit(bitrate=n * 1000)
        await interaction.response.send_message(f"🎵 Bitrate: **{n} kbps**.", ephemeral=True)


class RegionModal(discord.ui.Modal, title="Región del servidor de voz"):
    region = discord.ui.TextInput(
        label="Región (auto, us-east, eu-west, brazil…)",
        placeholder="auto",
        max_length=30,
    )

    def __init__(self, cog): super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        val = None if self.region.value.lower() == "auto" else self.region.value.lower()
        try:
            await interaction.user.voice.channel.edit(rtc_region=val)
        except discord.HTTPException as e:
            return await interaction.response.send_message(f"❌ Región inválida: {e}", ephemeral=True)
        await interaction.response.send_message(f"🌍 Región: **{val or 'automática'}**.", ephemeral=True)


class BanModal(discord.ui.Modal, title="Banear usuario del canal"):
    user_id = discord.ui.TextInput(label="ID de Discord del usuario", placeholder="123456789012345678", max_length=20)

    def __init__(self, cog): super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id.value)
            member = interaction.guild.get_member(uid)
            if not member: raise ValueError
        except (ValueError, TypeError):
            return await interaction.response.send_message("❌ ID de usuario inválido.", ephemeral=True)
        vc = interaction.user.voice.channel
        await vc.set_permissions(member, connect=False, view_channel=False)
        if member.voice and member.voice.channel == vc:
            await member.move_to(None)
        await interaction.response.send_message(f"🚫 **{member.display_name}** baneado del canal.", ephemeral=True)


class PermitModal(discord.ui.Modal, title="Permitir usuario en el canal"):
    user_id = discord.ui.TextInput(label="ID de Discord del usuario", placeholder="123456789012345678", max_length=20)

    def __init__(self, cog): super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id.value)
            member = interaction.guild.get_member(uid)
            if not member: raise ValueError
        except (ValueError, TypeError):
            return await interaction.response.send_message("❌ ID de usuario inválido.", ephemeral=True)
        vc = interaction.user.voice.channel
        await vc.set_permissions(member, connect=True, view_channel=True)
        await interaction.response.send_message(f"✅ **{member.display_name}** puede conectarse.", ephemeral=True)


class TransferModal(discord.ui.Modal, title="Transferir propiedad"):
    user_id = discord.ui.TextInput(label="ID del nuevo dueño", placeholder="123456789012345678", max_length=20)

    def __init__(self, cog): super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id.value)
            member = interaction.guild.get_member(uid)
            if not member: raise ValueError
        except (ValueError, TypeError):
            return await interaction.response.send_message("❌ ID de usuario inválido.", ephemeral=True)
        vc = interaction.user.voice.channel
        self.cog.db.update_voice_gen_channel_owner(vc.id, member.id)
        await vc.edit(name=f"{member.display_name}'s VC")
        await interaction.response.send_message(f"👑 Propiedad transferida a **{member.display_name}**.", ephemeral=True)


# ─── Cog principal ───────────────────────────────────────────────────────────

class VoiceGen(commands.Cog):
    """Generador dinámico de canales de voz (Join To Create)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore
        self._cleanup.start()

    def cog_unload(self):
        self._cleanup.cancel()

    # ── Persistir la vista al reiniciar ─────────────────────────────────────
    async def cog_load(self):
        self.bot.add_view(VCControlView(self))

    # ── Cleanup periódico de canales vacíos ──────────────────────────────────
    @tasks.loop(minutes=2)
    async def _cleanup(self):
        """Elimina canales generados que lleven más de 60 s vacíos."""
        for row in self.db.get_all_voice_gen_channels():
            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                continue
            channel = guild.get_channel(row["channel_id"])
            if channel is None:
                self.db.delete_voice_gen_channel(row["channel_id"])
                continue
            if len(channel.members) == 0:
                try:
                    await channel.delete(reason="VoiceGen: canal vacío")
                except discord.NotFound:
                    pass
                self.db.delete_voice_gen_channel(row["channel_id"])

    @_cleanup.before_loop
    async def _before_cleanup(self):
        await self.bot.wait_until_ready()

    # ── Evento principal ─────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        guild = member.guild
        cfg = self.db.get_voice_gen_config(guild.id)

        # ── Si entró a un canal ──────────────────────────────────────────────
        if after.channel and cfg.get("enabled"):
            if after.channel.id == cfg.get("generator_channel_id"):
                await self._create_vc(member, cfg)

        # ── Si salió de un canal generado → limpiar si está vacío ───────────
        if before.channel and before.channel != after.channel:
            if self.db.get_voice_gen_channel(before.channel.id):
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete(reason="VoiceGen: canal vacío")
                    except (discord.NotFound, discord.Forbidden):
                        pass
                    self.db.delete_voice_gen_channel(before.channel.id)

    async def _create_vc(self, member: discord.Member, cfg: dict):
        guild = member.guild

        # Nombre del canal usando la plantilla
        template = cfg.get("name_template") or "{username}'s VC"
        ch_name = template.replace("{username}", member.display_name) \
                          .replace("{user}", str(member)) \
                          .replace("{tag}", member.discriminator or "")

        # Categoría donde crear el VC
        category = None
        if cfg.get("category_id"):
            category = guild.get_channel(cfg["category_id"])

        try:
            # Heredar permisos de la categoría si existe
            vc = await guild.create_voice_channel(
                name=ch_name,
                category=category,
                user_limit=cfg.get("default_limit", 0),
                reason=f"VoiceGen: creado para {member}",
            )
        except discord.Forbidden:
            logger.error("VoiceGen: sin permisos para crear VC en %s", guild.name)
            return
        except Exception:
            logger.exception("VoiceGen: error creando VC en %s", guild.name)
            return

        # Guardar en BD
        self.db.create_voice_gen_channel(vc.id, guild.id, member.id)

        # Mover al usuario al nuevo canal
        try:
            await member.move_to(vc, reason="VoiceGen: movido a canal privado")
        except discord.Forbidden:
            logger.warning("VoiceGen: no se pudo mover a %s", member)

        # Enviar panel de control
        panel_ch_id = cfg.get("panel_channel_id")
        panel_ch = guild.get_channel(panel_ch_id) if panel_ch_id else None

        if panel_ch and isinstance(panel_ch, discord.TextChannel):
            embed = discord.Embed(
                title="🔊 Tu canal de voz está listo",
                description=(
                    f"**{member.mention}** — Bienvenido a **{ch_name}**\n\n"
                    "Usa los botones de abajo para configurar tu canal.\n"
                    "El canal se eliminará automáticamente cuando esté vacío."
                ),
                color=0x7c3aed,
            )
            embed.set_footer(text=f"ID del canal: {vc.id}")
            try:
                await panel_ch.send(embed=embed, view=VCControlView(self))
            except discord.Forbidden:
                logger.warning("VoiceGen: sin permisos para enviar panel en %s", panel_ch)

    # ─── Comandos slash /vc ──────────────────────────────────────────────────

    vc_group = app_commands.Group(
        name="vc",
        description="Gestiona tu canal de voz generado",
    )

    @vc_group.command(name="lock", description="Bloquear el canal a nuevas conexiones")
    async def vc_lock(self, interaction: discord.Interaction):
        if not await _assert_owner(interaction, self.db): return
        await interaction.user.voice.channel.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message("🔒 Canal bloqueado.", ephemeral=True)

    @vc_group.command(name="unlock", description="Permitir que cualquiera se conecte")
    async def vc_unlock(self, interaction: discord.Interaction):
        if not await _assert_owner(interaction, self.db): return
        await interaction.user.voice.channel.set_permissions(interaction.guild.default_role, connect=None)
        await interaction.response.send_message("🔓 Canal desbloqueado.", ephemeral=True)

    @vc_group.command(name="limit", description="Establecer el límite de usuarios")
    @app_commands.describe(n="Número de usuarios máximo (0 = ilimitado)")
    async def vc_limit(self, interaction: discord.Interaction, n: int):
        if not await _assert_owner(interaction, self.db): return
        if not 0 <= n <= 99:
            return await interaction.response.send_message("❌ Valor entre 0 y 99.", ephemeral=True)
        await interaction.user.voice.channel.edit(user_limit=n)
        await interaction.response.send_message(f"👥 Límite: **{n or 'ilimitado'}**.", ephemeral=True)

    @vc_group.command(name="rename", description="Renombrar tu canal de voz")
    @app_commands.describe(nombre="Nuevo nombre del canal")
    async def vc_rename(self, interaction: discord.Interaction, nombre: str):
        if not await _assert_owner(interaction, self.db): return
        await interaction.user.voice.channel.edit(name=nombre)
        await interaction.response.send_message(f"✏️ Renombrado a **{nombre}**.", ephemeral=True)

    @vc_group.command(name="ban", description="Banear a alguien de tu canal")
    @app_commands.describe(usuario="Usuario a banear")
    async def vc_ban(self, interaction: discord.Interaction, usuario: discord.Member):
        if not await _assert_owner(interaction, self.db): return
        vc = interaction.user.voice.channel
        await vc.set_permissions(usuario, connect=False, view_channel=False)
        if usuario.voice and usuario.voice.channel == vc:
            await usuario.move_to(None)
        await interaction.response.send_message(f"🚫 **{usuario.display_name}** baneado.", ephemeral=True)

    @vc_group.command(name="permit", description="Permitir a alguien unirse a tu canal")
    @app_commands.describe(usuario="Usuario a permitir")
    async def vc_permit(self, interaction: discord.Interaction, usuario: discord.Member):
        if not await _assert_owner(interaction, self.db): return
        vc = interaction.user.voice.channel
        await vc.set_permissions(usuario, connect=True, view_channel=True)
        await interaction.response.send_message(f"✅ **{usuario.display_name}** puede conectarse.", ephemeral=True)

    @vc_group.command(name="claim", description="Reclamar la propiedad de un canal abandonado")
    async def vc_claim(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ Debes estar en un VC generado.", ephemeral=True)
        vc = interaction.user.voice.channel
        row = self.db.get_voice_gen_channel(vc.id)
        if not row:
            return await interaction.response.send_message("❌ Este no es un VC generado.", ephemeral=True)
        if any(m.id == row["owner_id"] for m in vc.members):
            return await interaction.response.send_message("❌ El dueño actual aún está en el canal.", ephemeral=True)
        self.db.update_voice_gen_channel_owner(vc.id, interaction.user.id)
        await vc.edit(name=f"{interaction.user.display_name}'s VC")
        await interaction.response.send_message("👑 ¡Canal reclamado!", ephemeral=True)

    @vc_group.command(name="transfer", description="Transferir la propiedad del canal")
    @app_commands.describe(usuario="Nuevo dueño del canal")
    async def vc_transfer(self, interaction: discord.Interaction, usuario: discord.Member):
        if not await _assert_owner(interaction, self.db): return
        vc = interaction.user.voice.channel
        self.db.update_voice_gen_channel_owner(vc.id, usuario.id)
        await vc.edit(name=f"{usuario.display_name}'s VC")
        await interaction.response.send_message(f"👑 Canal transferido a **{usuario.display_name}**.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceGen(bot))
