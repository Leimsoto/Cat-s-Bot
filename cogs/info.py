"""
cogs/info.py
────────────
Comandos de información general del bot.

  /ping       – Latencia del bot
  /botinfo    – Información del bot: uptime, CPU, RAM, servidores
  /serverinfo – Información detallada del servidor
  /serverlogs – Acciones de moderación recientes
"""

import platform
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

try:
    import psutil  # type: ignore
    if not hasattr(psutil, "cpu_percent"):
        psutil = None  # broken namespace package
except Exception:
    psutil = None


class LogPages(discord.ui.View):
    """Paginador para /serverlogs."""

    def __init__(self, pages: list, author_id: int):
        super().__init__(timeout=120)
        self.pages = pages
        self.author_id = author_id
        self.current = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_page.disabled = self.current == 0
        self.next_page.disabled = self.current == len(self.pages) - 1
        self.page_counter.label = f"{self.current + 1}/{len(self.pages)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Solo quien ejecutó el comando puede paginar.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="0/0", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)


class Info(commands.Cog):
    """Comandos informativos: ping, estado del sistema e información del servidor."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._start_time = datetime.now(timezone.utc)
        self.db = bot.db  # type: ignore

    # ─────────────────────────────────────────────────────────────────────────
    # /ping
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="ping", description="Muestra la latencia del bot con el servidor de Discord")
    async def ping(self, interaction: discord.Interaction):
        ms = round(self.bot.latency * 1000)

        if ms < 100:
            color, label = discord.Color.green(), "Excelente"
        elif ms < 200:
            color, label = discord.Color.yellow(), "Normal"
        else:
            color, label = discord.Color.red(), "Alta"

        embed = discord.Embed(title="Pong", color=color)
        embed.add_field(name="Latencia API", value=f"`{ms} ms`", inline=True)
        embed.add_field(name="Estado", value=label, inline=True)

        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /botinfo
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="botinfo",
        description="Información del bot: latencia, uptime, uso de CPU y RAM",
    )
    async def botinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Uptime
        delta = datetime.now(timezone.utc) - self._start_time
        total_sec = int(delta.total_seconds())
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h}h {m}m {s}s"

        # Sistema (sin bloquear el event loop con interval breve)
        if psutil is not None:
            try:
                cpu_pct = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory()
                ram_used = ram.used // 1024 ** 2
                ram_total = ram.total // 1024 ** 2
                ram_pct = ram.percent
            except Exception:
                cpu_pct = None
                ram_used = ram_total = ram_pct = None
        else:
            cpu_pct = None
            ram_used = ram_total = ram_pct = None

        embed = discord.Embed(
            title=self.bot.user.name,
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.add_field(
            name="Latencia",
            value=f"`{round(self.bot.latency * 1000)} ms`",
            inline=True,
        )
        embed.add_field(name="Uptime", value=f"`{uptime_str}`", inline=True)
        embed.add_field(
            name="Servidores",
            value=f"`{len(self.bot.guilds)}`",
            inline=True,
        )
        embed.add_field(
            name="CPU",
            value=f"`{cpu_pct:.1f}%`" if cpu_pct is not None else "`n/d`",
            inline=True,
        )
        embed.add_field(
            name="RAM",
            value=(
                f"`{ram_used} MB / {ram_total} MB ({ram_pct:.1f}%)`"
                if ram_used is not None
                else "`n/d`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Python",
            value=f"`{platform.python_version()}`",
            inline=True,
        )

        # Info del servidor donde se ejecutó el comando
        guild = interaction.guild
        embed.add_field(name="Servidor", value=guild.name, inline=True)
        embed.add_field(
            name="Miembros",
            value=f"`{guild.member_count}`",
            inline=True,
        )

        embed.set_footer(text=f"Bot ID: {self.bot.user.id}")

        await interaction.followup.send(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /serverinfo
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="serverinfo",
        description="Información detallada del servidor",
    )
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild

        humans = sum(1 for m in guild.members if not m.bot)
        bots = guild.member_count - humans

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)

        created = guild.created_at.strftime("%d/%m/%Y %H:%M UTC")

        embed = discord.Embed(
            title=guild.name,
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="Dueño", value=guild.owner.mention, inline=True)
        embed.add_field(name="ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="Creación", value=created, inline=True)

        embed.add_field(
            name="Miembros",
            value=f"Total: `{guild.member_count}`\nHumanos: `{humans}`\nBots: `{bots}`",
            inline=True,
        )
        embed.add_field(
            name="Canales",
            value=f"Texto: `{text_channels}`\nVoz: `{voice_channels}`\nCategorías: `{categories}`",
            inline=True,
        )
        embed.add_field(
            name="Roles",
            value=f"`{len(guild.roles)}`",
            inline=True,
        )

        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count
        embed.add_field(
            name="Boost",
            value=f"Nivel: `{boost_level}`\nImpulsos: `{boost_count}`",
            inline=True,
        )
        embed.add_field(
            name="Verificación",
            value=f"`{guild.verification_level.name.title()}`",
            inline=True,
        )
        embed.add_field(
            name="Emojis",
            value=f"`{len(guild.emojis)}`",
            inline=True,
        )

        embed.set_footer(text=f"Solicitado por {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

        # ─────────────────────────────────────────────────────────────────────────
    # /avatar
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="avatar", description="Muestra el avatar de un usuario en grande")
    @app_commands.describe(usuario="Usuario del que ver el avatar")
    async def avatar(self, interaction: discord.Interaction, usuario: discord.User = None):
        target = usuario or interaction.user
        embed = discord.Embed(
            title=f"Avatar de {target.display_name}",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=target.display_avatar.url)
        embed.set_footer(text=f"ID: {target.id}")
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /banner
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="banner", description="Muestra el banner de un usuario en grande")
    @app_commands.describe(usuario="Usuario del que ver el banner")
    async def banner(self, interaction: discord.Interaction, usuario: discord.User = None):
        target = usuario or interaction.user
        try:
            user = await self.bot.fetch_user(target.id)
        except discord.HTTPException:
            user = target

        if not user.banner:
            return await interaction.response.send_message(
                f"❌ {target.mention} no tiene banner.", ephemeral=True
            )

        embed = discord.Embed(
            title=f"Banner de {target.display_name}",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=user.banner.url)
        embed.set_footer(text=f"ID: {target.id}")
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /servericon
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="servericon", description="Muestra el icono del servidor en grande")
    async def servericon(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not guild.icon:
            return await interaction.response.send_message(
                "❌ Este servidor no tiene icono.", ephemeral=True
            )

        embed = discord.Embed(
            title=f"Icono de {guild.name}",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # /serverlogs
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="serverlogs",
        description="Acciones de moderación recientes en el servidor",
    )
    async def serverlogs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        rows = self.db._fetchall(
            "SELECT * FROM mod_actions WHERE guild_id = ? ORDER BY created_at DESC LIMIT 15",
            (interaction.guild_id,),
        )

        if not rows:
            embed = discord.Embed(
                title="Registros de Moderación",
                color=discord.Color.red(),
                description="No hay acciones de moderación registradas en este servidor.",
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        pages = []
        for i in range(0, len(rows), 5):
            chunk = rows[i:i + 5]
            embed = discord.Embed(
                title="Registros de Moderación",
                color=discord.Color.blurple(),
                timestamp=datetime.now(timezone.utc),
            )
            for r in chunk:
                target = interaction.guild.get_member(r["target_id"])
                mod = interaction.guild.get_member(r["moderator_id"])
                target_str = target.mention if target else f"`{r['target_id']}`"
                mod_str = mod.mention if mod else f"`{r['moderator_id']}`"
                embed.add_field(
                    name=f"{r['action_type']} | {r['created_at'][:10]}",
                    value=(
                        f"Usuario: {target_str}\n"
                        f"Mod: {mod_str}\n"
                        f"Razón: {r['reason'][:200]}"
                    ),
                    inline=False,
                )
            pages.append(embed)

        await interaction.followup.send(
            embed=pages[0],
            view=LogPages(pages, interaction.user.id),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
