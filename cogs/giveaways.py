import logging
import json
import asyncio
import random
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

logger = logging.getLogger(__name__)

class GiveawayJoinView(discord.ui.View):
    """
    Vista persistente para sorteos.
    El message_id se resuelve por interaction.message.id (no por estado en memoria),
    así una sola instancia registrada con bot.add_view() sirve para todos los sorteos
    activos tras reiniciar el bot.
    """

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🎉 Participar", emoji="🎉", style=discord.ButtonStyle.primary, custom_id="gw_join")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = interaction.message.id if interaction.message else 0
        gw = self.cog.db.get_giveaway(msg_id)
        if not gw or gw.get("ended") or gw.get("cancelled"):
            return await interaction.response.send_message(
                "❌ Este sorteo ya ha finalizado.", ephemeral=True
            )

        try:
            parts = json.loads(gw.get("participants") or "[]")
        except Exception:
            parts = []

        if interaction.user.id in parts:
            parts.remove(interaction.user.id)
            ack = "Has abandonado el sorteo."
        else:
            try:
                req_roles = json.loads(gw.get("req_roles") or "[]")
                deny_roles = json.loads(gw.get("deny_roles") or "[]")
            except Exception:
                req_roles, deny_roles = [], []

            user_roles = [r.id for r in interaction.user.roles]

            if req_roles and not any(r in user_roles for r in req_roles):
                req_mentions = " o ".join([f"<@&{r}>" for r in req_roles])
                return await interaction.response.send_message(
                    f"❌ Necesitas tener al menos uno de estos roles: {req_mentions}",
                    ephemeral=True,
                )

            if deny_roles and any(r in user_roles for r in deny_roles):
                return await interaction.response.send_message(
                    "❌ Tienes un rol que no tiene permitido participar en este sorteo.",
                    ephemeral=True,
                )

            parts.append(interaction.user.id)
            ack = "🎉 ¡Te has unido al sorteo!"

        self.cog.db.update_giveaway(msg_id, participants=json.dumps(parts))

        button.label = f"🎉 Participar ({len(parts)})"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(ack, ephemeral=True)


class Giveaways(commands.Cog):
    """Módulo de Sorteos Avanzados"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db # type: ignore
        self.giveaway_checker.start()

    def cog_unload(self):
        self.giveaway_checker.cancel()

    @tasks.loop(seconds=30)
    async def giveaway_checker(self):
        active = self.db.get_active_giveaways()
        now = int(datetime.now(timezone.utc).timestamp())
        
        for gw in active:
            if now >= gw["end_time"]:
                await self.end_giveaway(gw)

    @giveaway_checker.before_loop
    async def before_giveaway_checker(self):
        await self.bot.wait_until_ready()

    async def end_giveaway(self, gw: dict):
        try:
            parts = json.loads(gw.get("participants") or "[]")
        except Exception:
            parts = []
        winners_count = int(gw.get("winners_count") or 1)
        winners_ids = random.sample(parts, min(len(parts), winners_count)) if parts else []

        self.db.update_giveaway(
            gw["message_id"],
            ended=1,
            winners=json.dumps(winners_ids),
        )

        guild = self.bot.get_guild(gw["guild_id"])
        if not guild:
            return
        channel = guild.get_channel(gw["channel_id"])
        if not channel:
            return

        try:
            msg = await channel.fetch_message(gw["message_id"])
            embed = msg.embeds[0] if msg.embeds else discord.Embed(title=gw.get("prize", "Sorteo"))
            embed.color = discord.Color.dark_grey()

            disabled_view = GiveawayJoinView(self)
            disabled_view.children[0].disabled = True
            disabled_view.children[0].label = f"Finalizado ({len(parts)})"

            if not winners_ids:
                await channel.send(f"Tristemente nadie participó en el sorteo de **{gw['prize']}**. 😢")
                embed.set_footer(text="Sorteo finalizado · Sin participantes")
            else:
                winners_mentions = ", ".join(f"<@{w}>" for w in winners_ids)
                verb = "Han" if len(winners_ids) > 1 else "Has"
                await channel.send(f"🎉 ¡Felicidades {winners_mentions}! ¡{verb} ganado **{gw['prize']}**!")
                embed.set_footer(text=f"Finalizado · Ganadores: {len(winners_ids)}")
                if embed.description:
                    embed.description = f"{embed.description}\n\n🏆 **Ganadores:** {winners_mentions}"
                else:
                    embed.description = f"🏆 **Ganadores:** {winners_mentions}"

            await msg.edit(embed=embed, view=disabled_view)

        except discord.NotFound:
            logger.warning("Mensaje del sorteo %s no encontrado al finalizar", gw["message_id"])
        except Exception as e:
            logger.error(f"Error terminando sorteo: {e}")

    @app_commands.command(name="sorteo", description="Crea un sorteo interactivo")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        premio="Qué se va a sortear", 
        duracion_horas="Duración en horas", 
        ganadores="Cantidad de ganadores",
        rol_requerido="Rol necesario para participar (Opcional)",
        rol_denegado="Rol que NO puede participar (Opcional)",
        imagen_url="URL de imagen para el sorteo (Opcional)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def create_giveaway(
        self, 
        interaction: discord.Interaction, 
        premio: str, 
        duracion_horas: float,
        ganadores: int = 1,
        rol_requerido: discord.Role = None,
        rol_denegado: discord.Role = None,
        imagen_url: str = None
    ):
        end_time_dt = datetime.now(timezone.utc) + timedelta(hours=duracion_horas)
        end_ts = int(end_time_dt.timestamp())
        
        req_roles = [rol_requerido.id] if rol_requerido else []
        deny_roles = [rol_denegado.id] if rol_denegado else []
        
        embed = discord.Embed(
            title=f"🎁 Sorteo: {premio}",
            description=f"¡Pulsa el botón 🎉 para participar!\n"
                        f"Ganadores: **{ganadores}**\n"
                        f"Finaliza: <t:{end_ts}:R> (<t:{end_ts}:f>)",
            color=discord.Color.purple()
        )
        if rol_requerido:
            embed.add_field(name="Requisitos", value=f"Debes tener el rol {rol_requerido.mention}", inline=False)
        if rol_denegado:
            embed.add_field(name="Denegados", value=f"NO debes tener el rol {rol_denegado.mention}", inline=False)
            
        if imagen_url and imagen_url.startswith("http"):
            embed.set_image(url=imagen_url)
            
        await interaction.response.send_message("Sorteo creado.", ephemeral=True)
        msg = await interaction.channel.send(embed=embed)
        
        self.db.create_giveaway(
            interaction.guild_id, interaction.channel.id, msg.id, 
            premio, end_ts, ganadores, 
            json.dumps(req_roles), json.dumps(deny_roles)
        )
        
        view = GiveawayJoinView(self)
        await msg.edit(view=view)

    # ── Comandos de gestión ──────────────────────────────────────────────────

    @app_commands.command(name="sorteo_terminar", description="Termina un sorteo activo inmediatamente y elige ganadores")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(id_mensaje="ID del mensaje del sorteo")
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway_end(self, interaction: discord.Interaction, id_mensaje: str):
        await interaction.response.defer(ephemeral=True)
        try:
            msg_id = int(id_mensaje)
        except ValueError:
            return await interaction.followup.send("❌ El ID debe ser un número.", ephemeral=True)

        gw = self.db.get_giveaway(msg_id)
        if not gw or int(gw["guild_id"]) != interaction.guild_id:
            return await interaction.followup.send("❌ No se encontró ningún sorteo con ese ID en este servidor.", ephemeral=True)
        if gw["ended"]:
            return await interaction.followup.send("⚠️ Este sorteo ya ha finalizado.", ephemeral=True)

        await self.end_giveaway(gw)
        await interaction.followup.send("✅ Sorteo terminado y ganadores elegidos.", ephemeral=True)

    async def reroll_giveaway(self, gw: dict) -> list[int]:
        """
        Re-elige ganadores de un sorteo terminado y los anuncia.
        Retorna la lista de winner IDs nuevos. No re-edita el embed original.
        """
        try:
            parts = json.loads(gw.get("participants") or "[]")
        except Exception:
            parts = []
        if not parts:
            return []
        winners_count = int(gw.get("winners_count") or 1)
        winners_ids = random.sample(parts, min(len(parts), winners_count))
        self.db.update_giveaway(gw["message_id"], winners=json.dumps(winners_ids))

        guild = self.bot.get_guild(int(gw["guild_id"]))
        if guild:
            channel = guild.get_channel(int(gw["channel_id"]))
            if channel:
                mentions = ", ".join(f"<@{w}>" for w in winners_ids)
                try:
                    await channel.send(
                        f"🎉 **Reroll!** ¡Nuevos ganadores de **{gw['prize']}**: {mentions}!"
                    )
                except discord.HTTPException:
                    pass
        return winners_ids

    @app_commands.command(name="sorteo_cancelar", description="Cancela un sorteo sin elegir ganadores")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(id_mensaje="ID del mensaje del sorteo")
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway_cancel(self, interaction: discord.Interaction, id_mensaje: str):
        await interaction.response.defer(ephemeral=True)
        try:
            msg_id = int(id_mensaje)
        except ValueError:
            return await interaction.followup.send("❌ El ID debe ser un número.", ephemeral=True)

        gw = self.db.get_giveaway(msg_id)
        if not gw or int(gw["guild_id"]) != interaction.guild_id:
            return await interaction.followup.send("❌ No se encontró ningún sorteo con ese ID en este servidor.", ephemeral=True)
        if gw["ended"]:
            return await interaction.followup.send("⚠️ Este sorteo ya ha finalizado o fue cancelado.", ephemeral=True)

        self.db.update_giveaway(msg_id, ended=1, cancelled=1)
        guild = self.bot.get_guild(int(gw["guild_id"]))
        if guild:
            channel = guild.get_channel(int(gw["channel_id"]))
            if channel:
                try:
                    msg = await channel.fetch_message(msg_id)
                    embed = msg.embeds[0]
                    embed.color = discord.Color.dark_grey()
                    embed.set_footer(text="Sorteo Cancelado")
                    embed.description = (embed.description or "") + "\n\n🚫 **Sorteo cancelado por un administrador.**"
                    view = GiveawayJoinView(self)
                    view.children[0].disabled = True
                    await msg.edit(embed=embed, view=view)
                except Exception:
                    pass
        await interaction.followup.send("✅ Sorteo cancelado sin elegir ganadores.", ephemeral=True)

    @app_commands.command(name="sorteo_rerollear", description="Vuelve a elegir ganadores de un sorteo ya terminado")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(id_mensaje="ID del mensaje del sorteo")
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway_reroll(self, interaction: discord.Interaction, id_mensaje: str):
        await interaction.response.defer(ephemeral=True)
        try:
            msg_id = int(id_mensaje)
        except ValueError:
            return await interaction.followup.send("❌ El ID debe ser un número.", ephemeral=True)

        gw = self.db.get_giveaway(msg_id)
        if not gw or int(gw["guild_id"]) != interaction.guild_id:
            return await interaction.followup.send("❌ No se encontró ningún sorteo con ese ID.", ephemeral=True)
        if not gw["ended"]:
            return await interaction.followup.send("⚠️ El sorteo aún está activo. Términalo primero con `/giveaway_end`.", ephemeral=True)

        winners_ids = await self.reroll_giveaway(gw)
        if not winners_ids:
            return await interaction.followup.send("❌ No hubo participantes en este sorteo.", ephemeral=True)
        await interaction.followup.send("✅ Nuevos ganadores elegidos y anunciados.", ephemeral=True)

    @app_commands.command(name="sorteo_lista", description="Lista los sorteos activos en este servidor")
    async def giveaway_list(self, interaction: discord.Interaction):
        active = self.db.get_active_giveaways()
        guild_gws = [g for g in active if int(g["guild_id"]) == interaction.guild_id]

        if not guild_gws:
            return await interaction.response.send_message("📫 No hay sorteos activos en este servidor.", ephemeral=True)

        embed = discord.Embed(
            title="🎁 Sorteos Activos",
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc),
        )
        for gw in guild_gws:
            parts = json.loads(gw["participants"])
            end_ts = int(gw["end_time"])
            embed.add_field(
                name=f"🎁 {gw['prize']}",
                value=(
                    f"Participantes: **{len(parts)}**\n"
                    f"Ganadores: **{gw['winners_count']}**\n"
                    f"Finaliza: <t:{end_ts}:R>\n"
                    f"ID mensaje: `{gw['message_id']}`"
                ),
                inline=True,
            )
        embed.set_footer(text="Usa /giveaway_end <id> para terminar uno antes de tiempo")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    cog = Giveaways(bot)
    await bot.add_cog(cog)
    # Vista persistente: una sola instancia. El handler resuelve message_id
    # desde interaction.message.id, así que sirve para cualquier sorteo activo.
    bot.add_view(GiveawayJoinView(cog))

