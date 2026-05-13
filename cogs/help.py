import logging
import discord
from discord.ext import commands
from discord import app_commands

logger = logging.getLogger(__name__)

CATEGORIES = {
    "mod": {
        "emoji": "🛡️",
        "name": "Moderación",
        "commands": [
            ("/ban", "Banea un usuario"),
            ("/tempban [duración]", "Banea temporalmente"),
            ("/unban", "Desbanea por ID"),
            ("/kick", "Expulsa un usuario"),
            ("/mute [duración]", "Silencia un usuario"),
            ("/unmute", "Quita el silencio"),
            ("/warn", "Advierte un usuario"),
            ("/warns [usuario]", "Ver warns"),
            ("/clearwarns", "Limpia warns"),
            ("/purge [N]", "Elimina mensajes en masa"),
            ("/appeals list", "Lista apelaciones"),
        ],
    },
    "info": {
        "emoji": "ℹ️",
        "name": "Información",
        "commands": [
            ("/ping", "Latencia del bot"),
            ("/botinfo", "Estado del bot"),
            ("/serverinfo", "Info del servidor"),
            ("/serverlogs", "Logs en tiempo real"),
            ("/userinfo [usuario]", "Info detallada"),
            ("/roleinfo [rol]", "Info de un rol"),
            ("/avatar [usuario]", "Avatar en grande"),
            ("/banner [usuario]", "Banner en grande"),
            ("/servericon", "Icono del servidor"),
        ],
    },
    "channels": {
        "emoji": "📝",
        "name": "Canales",
        "commands": [
            ("/lock", "Bloquea el canal"),
            ("/unlock", "Desbloquea el canal"),
            ("/slowmode [s]", "Modo lento"),
            ("/clear [N]", "Borra N mensajes"),
            ("/clearall", "Borra todo (irreversible)"),
            ("/channelsetup", "Panel multimedia"),
        ],
    },
    "users": {
        "emoji": "👥",
        "name": "Usuarios",
        "commands": [
            ("/addrole", "Añade un rol"),
            ("/removerole", "Quita un rol"),
            ("/nick [usuario]", "Cambia el apodo"),
            ("/usermessage [N]", "Últimos mensajes"),
        ],
    },
    "embeds": {
        "emoji": "🎨",
        "name": "Embeds",
        "commands": [
            ("/embed create", "Constructor interactivo"),
            ("/embed list", "Lista embeds guardados"),
            ("/embed load [nombre]", "Carga un embed"),
        ],
    },
    "ia": {
        "emoji": "🤖",
        "name": "IA / Gemini",
        "commands": [
            ("/ai_status", "Métricas del servicio"),
            ("/iaclear", "Borra tu historial"),
        ],
    },
    "tickets": {
        "emoji": "🎫",
        "name": "Tickets",
        "commands": [
            ("/adduser", "Añade usuario al ticket"),
        ],
    },
    "tags": {
        "emoji": "🏷️",
        "name": "Tags",
        "commands": [
            ("/tag get [nombre]", "Usa un tag"),
            ("/tag create", "Crea un tag"),
            ("/tag edit [nombre]", "Edita un tag"),
            ("/tag delete [nombre]", "Elimina un tag"),
            ("/tag list", "Lista todos"),
            ("/tag info [nombre]", "Info del tag"),
        ],
    },
    "levels": {
        "emoji": "🎮",
        "name": "Niveles / XP",
        "commands": [
            ("/rank [usuario]", "Tu rango o el de otro"),
            ("/leaderboard", "Top 10 del servidor"),
            ("/xp give [@] [N]", "[Admin] Dar XP"),
            ("/xp reset [@]", "[Admin] Resetear XP"),
        ],
    },
    "giveaways": {
        "emoji": "🎁",
        "name": "Sorteos",
        "commands": [
            ("/giveaway", "Crear sorteo interactivo"),
            ("/giveaway_end", "Terminar sorteo"),
            ("/giveaway_cancel", "Cancelar sorteo"),
            ("/giveaway_reroll", "Re-elegir ganador"),
            ("/giveaway_list", "Sorteos activos"),
        ],
    },
    "radio": {
        "emoji": "📻",
        "name": "Radio",
        "commands": [
            ("/radio status", "Estado actual"),
            ("/radio restart", "Reconectar stream"),
            ("/radio buscar [nombre]", "Buscar emisora"),
        ],
    },
    "autoroles": {
        "emoji": "🔐",
        "name": "Autoroles",
        "commands": [
            ("/autorolereact", "Rol por reacción"),
            ("/rolemenu", "Menú de roles dropdown"),
        ],
    },
    "reports": {
        "emoji": "📋",
        "name": "Reportes",
        "commands": [
            ("/report [@] [razón]", "Reportar usuario"),
            ("/reports list [estado]", "[Staff] Listar"),
            ("/reports view [id]", "[Staff] Ver detalle"),
        ],
    },
    "invites": {
        "emoji": "👋",
        "name": "Invitaciones",
        "commands": [
            ("/invites stats [user]", "Tus invitaciones"),
            ("/invites leaderboard", "Top 10 inviters"),
        ],
    },
    "schedule": {
        "emoji": "🗓️",
        "name": "Programador",
        "commands": [
            ("/schedule create [#canal]", "Crear mensaje"),
            ("/schedule list", "Listar schedules"),
            ("/schedule delete [nombre]", "Eliminar"),
            ("/schedule toggle [nombre]", "Activar/desactivar"),
            ("/schedule test [nombre]", "Enviar prueba"),
        ],
    },
    "vc": {
        "emoji": "🔊",
        "name": "Canales de Voz",
        "commands": [
            ("/vc lock", "Bloquear tu VC"),
            ("/vc unlock", "Desbloquear tu VC"),
            ("/vc limit [N]", "Límite de usuarios"),
            ("/vc rename [nombre]", "Renombrar"),
            ("/vc ban [@]", "Banear de tu VC"),
            ("/vc permit [@]", "Permitir acceso"),
            ("/vc claim", "Reclamar propiedad"),
            ("/vc transfer [@]", "Transferir propiedad"),
        ],
    },
    "automod": {
        "emoji": "🤖",
        "name": "Automoderación",
        "commands": [
            ("/automod status", "Estado y últimas acciones"),
            ("/automod toggle", "Activar/desactivar"),
            ("/automod log [N]", "Ver registro de acciones"),
        ],
    },
    "autoresponses": {
        "emoji": "💬",
        "name": "Auto-Respuestas",
        "commands": [
            ("/autoresponse add", "Agregar auto-respuesta"),
            ("/autoresponse remove", "Eliminar auto-respuesta"),
            ("/autoresponse list", "Listar todas"),
        ],
    },
    "config": {
        "emoji": "⚙️",
        "name": "Configuración",
        "commands": [
            ("/welcome channel", "Canal de bienvenidas"),
            ("/welcome toggle", "Activar/desactivar"),
            ("/welcome test", "Probar bienvenida"),
            ("/boost channel", "Canal de boosters"),
            ("/boost toggle", "Activar/desactivar"),
            ("/starboard channel", "Canal de starboard"),
            ("/starboard threshold", "Umbral de estrellas"),
            ("/starboard config", "Ver configuración"),
        ],
    },
}


class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=data["name"],
                emoji=data["emoji"],
                value=key,
                description=f"{len(data['commands'])} comandos",
            )
            for key, data in CATEGORIES.items()
        ]
        super().__init__(
            placeholder="Selecciona una categoría...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        data = CATEGORIES[key]
        embed = discord.Embed(
            title=f"{data['emoji']} {data['name']}",
            description="",
            color=discord.Color.blurple(),
        )
        for cmd, desc in data["commands"]:
            embed.add_field(name=f"`{cmd}`", value=desc, inline=False)
        embed.set_footer(text="Usa /help para ver este menú otra vez")
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(HelpSelect())

    @discord.ui.button(label="General", emoji="📖", style=discord.ButtonStyle.secondary, row=1)
    async def general_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📖 Ayuda General",
            description=(
                "**Cat's Bot** — Bot multifuncional para Discord.\n\n"
                "Usa el menú desplegable de arriba para ver comandos por categoría.\n\n"
                "También puedes usar **`!help`** con mensajes de texto para obtener la misma ayuda.\n\n"
                "📌 La mayoría de comandos se configuran desde el **Dashboard Web**."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="🔗 Dashboard",
            value="Accede al panel de control web para configurar módulos como:\n"
            "Tickets · Bienvenidas · Sugerencias · Niveles · Radio · IA · Autoroles · y más.",
            inline=False,
        )
        total_cmds = sum(len(c["commands"]) for c in CATEGORIES.values())
        embed.set_footer(text=f"{len(CATEGORIES)} categorías · {total_cmds} comandos slash")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cerrar", emoji="❌", style=discord.ButtonStyle.danger, row=1)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Menú cerrado.", embed=None, view=None)
        self.stop()


class Help(commands.Cog):
    """Sistema de ayuda interactivo con botones y !help"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Muestra la ayuda interactiva del bot")
    async def help_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="📖 Ayuda de Cat's Bot",
            description=(
                "Selecciona una categoría en el menú desplegable para ver sus comandos.\n\n"
                "También puedes escribir **`!help`** en el chat para ver esta misma ayuda."
            ),
            color=discord.Color.blurple(),
        )
        total_cmds = sum(len(c["commands"]) for c in CATEGORIES.values())
        embed.set_footer(text=f"{len(CATEGORIES)} categorías · {total_cmds} comandos")
        await interaction.followup.send(embed=embed, view=HelpView(), ephemeral=True)

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context):
        await ctx.send("Usa **`/help`** para ver la ayuda interactiva.", delete_after=10)
        try:
            await ctx.message.delete()
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
