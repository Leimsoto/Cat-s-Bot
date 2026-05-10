import logging
import asyncio
import requests

import discord
from discord.ext import commands, tasks
from discord import app_commands

logger = logging.getLogger(__name__)

LOFI_STREAM_URL = "http://lofi.stream.laut.fm/lofi"
RADIO_API_URL = "http://de1.api.radio-browser.info/json/stations/search"

class Radio(commands.Cog):
    """Módulo de Radio Global 24/7 con búsqueda de emisoras."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db # type: ignore
        self._playback_wait = 1.0  # segundos a esperar tras parar una reproducción
        self.radio_manager.start()

    def cog_unload(self):
        self.radio_manager.cancel()

    @tasks.loop(seconds=60)
    async def radio_manager(self):
        for guild in self.bot.guilds:
            cfg = self.db.get_lofi_config(guild.id)
            if not cfg.get("enabled"):
                vc = guild.voice_client
                if vc:
                    try:
                        await vc.disconnect()
                    except Exception:
                        pass
                continue

            channel_id = cfg.get("channel_id")
            if not channel_id:
                continue

            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, discord.VoiceChannel):
                continue

            vc = guild.voice_client

            if not vc or not vc.is_connected():
                try:
                    vc = await channel.connect(reconnect=True)
                except Exception:
                    logger.exception(f"No se pudo conectar al canal de radio en {guild.name}")
                    continue

            if vc.channel.id != channel_id:
                try:
                    await vc.move_to(channel)
                except Exception:
                    continue

            if not vc.is_playing():
                self.start_playing(vc, channel, cfg)

    @radio_manager.before_loop
    async def before_radio_manager(self):
        await self.bot.wait_until_ready()

    def start_playing(self, vc, channel, cfg):
        stream_url = cfg.get("stream_url") or LOFI_STREAM_URL
        station_name = cfg.get("station_name") or "Lofi Radio 24/7"

        try:
            import shutil
            ffmpeg_path = shutil.which("ffmpeg") or "ffmpeg"
            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }
            audio_source = discord.FFmpegPCMAudio(stream_url, executable=ffmpeg_path, **ffmpeg_options)

            vol = cfg.get("volume", 100) / 100.0
            if vol != 1.0:
                audio_source = discord.PCMVolumeTransformer(audio_source, volume=vol)

            def after_playback(error):
                if error:
                    logger.error(f"Error en reproducción de radio: {error}")
                # Re-leer config desde DB para tener el estado más actualizado
                current_cfg = self.db.get_lofi_config(channel.guild.id)
                if current_cfg.get("enabled"):
                    asyncio.run_coroutine_threadsafe(
                        self.reconnect_stream(vc, channel, current_cfg), self.bot.loop
                    )

            vc.play(audio_source, after=after_playback)

            # Actualizar presencia del bot para indicar la estación
            try:
                coro = self.bot.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.listening,
                        name=f"🎶 {station_name} | Chill & Relax",
                    )
                )
                fut = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
                fut.result(timeout=5)
            except Exception:
                pass
        except Exception:
            logger.exception(f"Error reproduciendo radio en el canal {channel.id}")

    def _resolve_stream_sync(self, url: str) -> str:
        """Resuelve playlists (.m3u/.pls) devolviendo la primera URL directa.

        Método síncrono pensado para ejecutarse en executor y no bloquear el loop.
        """
        try:
            with requests.get(url, stream=True, timeout=5) as r:
                content_type = r.headers.get("content-type", "").lower()
                
                is_playlist = url.lower().endswith(('.m3u', '.m3u8', '.pls')) or 'scpls' in content_type or 'mpegurl' in content_type
                
                # Si no parece una playlist, devolver la URL original y que FFmpeg se encargue
                if not is_playlist:
                    return url
                
                # Leemos solo el primer chunk de 4KB para evitar bloquear la memoria
                chunk = next(r.iter_content(chunk_size=4096, decode_unicode=True), "")
                if isinstance(chunk, bytes):
                    chunk = chunk.decode('utf-8', errors='ignore')
                
                lines = [l.strip() for l in chunk.splitlines() if l and not l.strip().startswith('#') and not l.strip().startswith('[')]
                for line in lines:
                    if line.lower().startswith("file1="):
                        return line.split("=", 1)[1].strip()
                    elif line.startswith("http"):
                        return line
        except Exception:
            pass
        return url

    async def reconnect_stream(self, vc, channel, cfg):
        # Respetar la opción auto_reconnect del dashboard. Default 1 (activo).
        if not cfg.get("auto_reconnect", 1):
            return
        await asyncio.sleep(2)
        if vc and vc.is_connected() and not vc.is_playing() and cfg.get("enabled"):
            # Pausar si el canal está vacío y el admin lo configuró así.
            if cfg.get("pause_on_empty"):
                non_bot_members = [m for m in channel.members if not m.bot]
                if not non_bot_members:
                    return
            self.start_playing(vc, channel, cfg)

    radio_group = app_commands.Group(
        name="radio",
        description="Configuración de Radio 24/7",
        default_permissions=discord.Permissions(administrator=True),
    )

    @radio_group.command(name="status", description="Consulta el estado y configuración actual de la radio")
    async def radio_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cfg = self.db.get_lofi_config(interaction.guild_id)
        if not cfg.get("enabled"):
            return await interaction.followup.send("❌ La radio está desactivada en este servidor.", ephemeral=True)

        canal = interaction.guild.get_channel(cfg["channel_id"])
        vc = interaction.guild.voice_client

        status_text = "🟢 Reproduciendo" if (vc and vc.is_playing()) else "🔴 Detenido / Conectando..."
        station = cfg.get("station_name", "Lofi Radio 24/7")

        embed = discord.Embed(title="Estado de la Radio", color=discord.Color.blue())
        embed.add_field(name="Estación", value=f"**{station}**", inline=False)
        embed.add_field(name="Canal", value=canal.mention if canal else "No encontrado", inline=True)
        embed.add_field(name="Estado", value=status_text, inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @radio_group.command(name="restart", description="Fuerza la reconexión y reinicio del stream de radio")
    @app_commands.checks.has_permissions(administrator=True)
    async def radio_restart(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cfg = self.db.get_lofi_config(interaction.guild_id)
        if not cfg.get("enabled"):
            return await interaction.followup.send("❌ La radio no está activada. Actívala desde el panel web.", ephemeral=True)

        channel_id = cfg.get("channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if not channel or not isinstance(channel, discord.VoiceChannel):
            return await interaction.followup.send("❌ Canal de voz no encontrado. Reconfigura desde el panel web.", ephemeral=True)

        vc = interaction.guild.voice_client
        try:
            if vc and vc.is_connected():
                if vc.is_playing():
                    vc.stop()
                if vc.channel.id != channel.id:
                    await vc.move_to(channel)
            else:
                vc = await channel.connect(reconnect=True)

            await asyncio.sleep(self._playback_wait)
            self.start_playing(vc, channel, cfg)
            station = cfg.get("station_name", "Lofi Radio 24/7")
            await interaction.followup.send(f"🔄 Stream reiniciado — **{station}**", ephemeral=True)
        except Exception as e:
            logger.exception(f"Error en /radio restart en {interaction.guild.name}")
            await interaction.followup.send(f"❌ Error al reiniciar el stream: {e}", ephemeral=True)

    @radio_group.command(name="buscar", description="Busca estaciones de radio globales para reproducir")
    @app_commands.describe(nombre="Nombre, género o país a buscar")
    @app_commands.checks.has_permissions(administrator=True)
    async def radio_search(self, interaction: discord.Interaction, nombre: str):
        await interaction.response.defer(ephemeral=True)

        try:
            params = {
                "name": nombre,
                "limit": 10,
                "hidebroken": "true",
                "order": "clickcount",
                "reverse": "true"
            }
            try:
                resp = await asyncio.to_thread(requests.get, RADIO_API_URL, params=params, timeout=5)
                data = resp.json()
            except Exception as e:
                logger.error(f"Error consultando la API de radios: {e}")
                return await interaction.followup.send("❌ Error consultando la API de radios.")

            if not data:
                return await interaction.followup.send("❌ No se encontraron estaciones con ese nombre.")

            options = []
            for idx, station in enumerate(data[:10]):
                name = station.get("name", "Desconocida")[:90]
                options.append(discord.SelectOption(
                    label=name,
                    description=f"{station.get('country', '')} - {station.get('tags', '')[:40]}",
                    value=f"{idx}"
                ))

            class RadioSelect(discord.ui.Select):
                def __init__(self, stations, db, bot, cog):
                    self.stations = stations
                    self.db = db
                    self.bot = bot
                    self.cog = cog
                    super().__init__(placeholder="Selecciona una emisora para reproducirla...", min_values=1, max_values=1, options=options)

                async def callback(self, inter: discord.Interaction):
                    try:
                        await inter.response.defer(ephemeral=True)
                    except Exception:
                        pass

                    idx = int(self.values[0])
                    station = self.stations[idx]
                    url = station.get("url_resolved") or station.get("url")
                    name = station.get("name", "Desconocida")

                    # Resolver playlists fuera del loop
                    try:
                        loop = asyncio.get_running_loop()
                        resolved = await loop.run_in_executor(None, self.cog._resolve_stream_sync, url)
                    except Exception:
                        resolved = url

                    # Asegurar columnas y actualizar configuración
                    try:
                        self.db.ensure_column("lofi_config", "stream_url", "TEXT")
                        self.db.ensure_column("lofi_config", "station_name", "TEXT")
                    except Exception:
                        pass

                    try:
                        self.db._upsert_config(
                            "lofi_config", inter.guild_id,
                            stream_url=resolved, station_name=name, enabled=1
                        )
                    except Exception:
                        logger.exception("Fallo guardando configuración de la emisora")

                    cfg = self.db.get_lofi_config(inter.guild_id)
                    channel = inter.guild.get_channel(cfg.get("channel_id"))
                    vc = inter.guild.voice_client

                    if not channel:
                        await inter.followup.send("❌ Canal configurado no encontrado. Configúralo desde el panel web.", ephemeral=True)
                        try:
                            await inter.message.edit(view=None)
                        except Exception:
                            pass
                        return

                    try:
                        if not vc or not vc.is_connected():
                            vc = await channel.connect(reconnect=True)
                            await asyncio.sleep(self.cog._playback_wait)
                            self.cog.start_playing(vc, channel, cfg)
                        else:
                            is_playing = vc.is_playing()
                            if is_playing:
                                vc.stop()
                            
                            if vc.channel.id != channel.id:
                                try:
                                    await vc.move_to(channel)
                                except Exception:
                                    pass
                                    
                            if not is_playing:
                                await asyncio.sleep(self.cog._playback_wait)
                                self.cog.start_playing(vc, channel, cfg)

                    except Exception as e:
                        logger.exception(f"Error aplicando emisora en {inter.guild.name}: {e}")
                        await inter.followup.send(f"❌ Error al aplicar la emisora: {e}", ephemeral=True)
                        try:
                            await inter.message.edit(view=None)
                        except Exception:
                            pass
                        return

                    try:
                        await inter.followup.send(f"📻 **Radio cambiada a:** {name}\nSe aplicará en unos segundos.", ephemeral=True)
                        try:
                            await inter.message.edit(view=None)
                        except Exception:
                            pass
                    except Exception:
                        pass

            view = discord.ui.View()
            view.add_item(RadioSelect(data, self.db, self.bot, self))

            await interaction.followup.send("Selecciona la estación que deseas sintonizar:", view=view)

        except Exception as e:
            logger.error(f"Error en radio_search: {e}")
            await interaction.followup.send(f"❌ Error consultando la API de radio: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Radio(bot))
