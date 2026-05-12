"""
main.py
───────
Punto de entrada del bot. Carga los cogs, sincroniza los comandos slash
e inyecta la instancia de base de datos en el bot.

Variables de entorno requeridas (.env):
  TOKEN   – Token del bot de Discord
  DB_TYPE – 'sqlite' (default) | 'postgresql' | 'mariadb'
  DATABASE_URL – Requerida si DB_TYPE != sqlite
"""

import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from api import iniciar_api
from database import DatabaseManager

# ── Cargar .env antes de cualquier otra inicialización ───────────────────────
load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("Bot")

# ── Intents ───────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True
intents.presences = True


# ── Bot ───────────────────────────────────────────────────────────────────────


class BotES(commands.Bot):
    """
    Bot principal.
    - Usa commands.Bot para soporte nativo de cogs y app_commands.
    - La instancia de DB se inyecta como `bot.db` para que todos los
      cogs la compartan sin crear conexiones redundantes.
    """

    def __init__(self):
        super().__init__(
            command_prefix="!",  # Solo para !help
            intents=intents,
            help_command=None,
        )
        # Instancia única de DB compartida por todos los cogs
        self.db = DatabaseManager()
        self.start_time = discord.utils.utcnow()

    async def setup_hook(self) -> None:
        """
        Llamado automáticamente antes de conectar al WebSocket.
        Carga los cogs y sincroniza los comandos slash.
        """

        # Ignorar errores de ClientConnectionResetError en tareas en background (ej. discord.py voice)
        def custom_exception_handler(loop, context):
            exception = context.get("exception")
            if exception and type(exception).__name__ == "ClientConnectionResetError":
                return
            loop.default_exception_handler(context)

        self.loop.set_exception_handler(custom_exception_handler)

        from discord.ext import tasks

        @tasks.loop(seconds=30)
        async def bot_stats_updater():
            members_online = sum(
                1
                for g in self.guilds
                for m in g.members
                if m.status != discord.Status.offline
            )
            total_members = sum(g.member_count or 0 for g in self.guilds)

            uptime_seconds = int(
                (discord.utils.utcnow() - self.start_time).total_seconds()
            )

            # Count open tickets (método público)
            open_tickets = 0
            if hasattr(self, "db"):
                try:
                    open_tickets = self.db.count_all_open_tickets()
                    self.db.update_bot_stats(
                        members_online, total_members, open_tickets, uptime_seconds
                    )
                except Exception:
                    pass

        @bot_stats_updater.before_loop
        async def before_bot_stats_updater():
            await self.wait_until_ready()

        bot_stats_updater.start()
        self.tree.on_error = self.on_app_command_error

        cogs = [
            "cogs.moderation",
            "cogs.info",
            "cogs.channels",
            "cogs.users",
            "cogs.embeds",
            "cogs.serverutils",
            "cogs.ia",
            "cogs.welcomes",
            "cogs.suggestions",
            "cogs.giveaways",
            "cogs.autoroles",
            "cogs.radio",
            "cogs.tickets",
            "cogs.tags",
            "cogs.reports",
            "cogs.scheduler",
            "cogs.levels",
            "cogs.voice_gen",
            "cogs.help",
            "cogs.automod",
            "cogs.admin",
            "cogs.rolemenu",
            "cogs.translate",
            "cogs.autoresponses",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info("Cog cargado: %s", cog)
            except Exception as exc:
                logger.error("Error cargando %s: %s", cog, exc, exc_info=True)

        synced = await self.tree.sync()
        logger.info("Comandos slash sincronizados: %d", len(synced))

    async def on_ready(self) -> None:
        logger.info("✅ %s conectado | %d servidor(es)", self.user, len(self.guilds))
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Testing With ArielTeen and Yessid",
            )
        )

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        """
        Manejador global de errores de comandos slash.
        Los cogs pueden tener sus propios handlers específicos.
        """
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            msg = f"⏳ Comando en cooldown. Intenta en `{error.retry_after:.1f}s`."
        elif isinstance(error, discord.app_commands.MissingPermissions):
            msg = f"❌ Te faltan permisos: `{', '.join(error.missing_permissions)}`"
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            msg = f"❌ Al bot le faltan permisos: `{', '.join(error.missing_permissions)}`"
        elif isinstance(error, discord.app_commands.CommandInvokeError):
            logger.error("Error invocando comando: %s", error.original, exc_info=True)
            msg = "❌ Error interno al ejecutar el comando. Revisa los logs."
        else:
            logger.error("Error de comando no manejado: %s", error, exc_info=True)
            msg = "❌ Ocurrió un error inesperado."

        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        """Silencia errores de comandos prefix no encontrados (ej. !hug)."""
        if isinstance(error, commands.CommandNotFound):
            return
        logger.debug("Error de prefix command (ignorado): %s", error)


# ── Arranque ──────────────────────────────────────────────────────────────────


def main() -> None:
    token = os.getenv("TOKEN")
    if not token:
        logger.critical("TOKEN no encontrado en el archivo .env")
        raise SystemExit(1)

    bot = BotES()
    iniciar_api(db=bot.db, bot=bot)

    try:
        bot.run(token, log_handler=None)  # log_handler=None para usar nuestro logging
    except discord.LoginFailure:
        logger.critical("Token inválido. Verifica el archivo .env")
    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario")
    except Exception as exc:
        logger.critical("Error crítico al iniciar: %s", exc, exc_info=True)


if __name__ == "__main__":
    main()
