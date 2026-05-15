import logging
import json
import asyncio
from datetime import datetime, timezone
import io
import re

import discord
from discord.ext import commands
from discord import app_commands
import chat_exporter

logger = logging.getLogger(__name__)


class TicketCloseReasonModal(discord.ui.Modal):
    def __init__(self, cog, ticket, channel):
        super().__init__(title="Motivo de Cierre")
        self.cog = cog
        self.ticket = ticket
        self.ticket_channel = channel
        
        self.reason = discord.ui.TextInput(
            label="Escribe el motivo del cierre",
            style=discord.TextStyle.paragraph,
            required=True,
            placeholder="Ej: Solucionado, Inactivo, etc."
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Cerrando ticket y generando transcripción...", ephemeral=True)
        await self.cog.close_ticket(self.ticket, interaction.user, self.reason.value, self.ticket_channel)


class TicketCloseConfirmView(discord.ui.View):
    def __init__(self, cog, ticket, channel):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket = ticket
        self.ticket_channel = channel

    @discord.ui.button(label="Confirmar Cierre (Staff)", style=discord.ButtonStyle.danger, custom_id="ticket_close_confirm")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verificar permisos
        config = self.cog.db.get_ticket_config(interaction.guild_id)
        immune_roles = json.loads(config.get("immune_roles", "[]"))
        allowed_roles = json.loads(config.get("allowed_roles", "[]"))
        
        user_roles = [r.id for r in interaction.user.roles]
        is_staff = interaction.user.guild_permissions.administrator or \
                   any(r in user_roles for r in immune_roles) or \
                   any(r in user_roles for r in allowed_roles) or \
                   (self.ticket.get("staff_id") == interaction.user.id)
                   
        if not is_staff:
            return await interaction.response.send_message("❌ Solo el staff puede confirmar el cierre.", ephemeral=True)
            
        # Obtener categoría para ver motivos predefinidos
        categories = self.cog.db.get_ticket_categories(interaction.guild_id)
        category = next((c for c in categories if c["name"] == self.ticket["category_name"]), None)
        reasons = json.loads(category.get("close_reasons", "[]")) if category else []
        
        if reasons:
            view = TicketCloseReasonView(self.cog, self.ticket, self.ticket_channel, reasons)
            await interaction.response.send_message("Selecciona el motivo del cierre:", view=view, ephemeral=True)
        else:
            await interaction.response.send_modal(TicketCloseReasonModal(self.cog, self.ticket, self.ticket_channel))


class TicketTakeCloseView(discord.ui.View):
    def __init__(self, cog, ticket_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket_id = ticket_id

    @discord.ui.button(label="Tomar Ticket", emoji="🙋‍♂️", style=discord.ButtonStyle.primary, custom_id="ticket_take")
    async def take_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = self.cog.db.get_ticket_by_channel(interaction.channel.id)
        if not ticket: return await interaction.response.send_message("Ticket no encontrado.", ephemeral=True)
        ticket_id = ticket["id"]
        
        if ticket["staff_id"]:
            return await interaction.response.send_message("❌ Este ticket ya fue tomado por otro staff.", ephemeral=True)
            
        config = self.cog.db.get_ticket_config(interaction.guild_id)
        allowed_roles = json.loads(config.get("allowed_roles", "[]"))
        
        # Verificar que es staff
        user_roles = [r.id for r in interaction.user.roles]
        if not (interaction.user.guild_permissions.administrator or any(r in user_roles for r in allowed_roles) or any(r in user_roles for r in json.loads(config.get("immune_roles", "[]")))):
            return await interaction.response.send_message("❌ No tienes permiso para tomar tickets.", ephemeral=True)

        self.cog.db.update_ticket(ticket_id, staff_id=interaction.user.id)
        
        # Quitar escritura a allowed_roles, dejar a immune_roles y dar a este staff
        channel = interaction.channel
        overwrites = channel.overwrites
        
        for r_id in allowed_roles:
            role = interaction.guild.get_role(r_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
                
        overwrites[interaction.user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        await channel.edit(overwrites=overwrites)
        
        button.disabled = True
        button.label = f"Tomado por {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"🛡️ {interaction.user.mention} se ha hecho cargo de este ticket.")

    @discord.ui.button(label="Cerrar", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = self.cog.db.get_ticket_by_channel(interaction.channel.id)
        if not ticket: return await interaction.response.send_message("Ticket no encontrado.", ephemeral=True)
        ticket_id = ticket["id"]
        
        config = self.cog.db.get_ticket_config(interaction.guild_id)
        immune_roles = json.loads(config.get("immune_roles", "[]"))
        allowed_roles = json.loads(config.get("allowed_roles", "[]"))
        user_roles = [r.id for r in interaction.user.roles]
        
        is_admin_or_immune = interaction.user.guild_permissions.administrator or any(r in user_roles for r in immune_roles)
        is_staff = is_admin_or_immune or any(r in user_roles for r in allowed_roles) or (ticket.get("staff_id") == interaction.user.id)
        
        if is_staff:
            # Obtener categoría para ver motivos predefinidos
            categories = self.cog.db.get_ticket_categories(interaction.guild_id)
            category = next((c for c in categories if c["name"] == ticket["category_name"]), None)
            reasons = json.loads(category.get("close_reasons", "[]")) if category else []
            
            if reasons:
                view = TicketCloseReasonView(self.cog, ticket, interaction.channel, reasons)
                await interaction.response.send_message("Selecciona el motivo del cierre:", view=view, ephemeral=True)
            else:
                await interaction.response.send_modal(TicketCloseReasonModal(self.cog, ticket, interaction.channel))
        else:
            # Usuario pidiendo cierre
            embed = discord.Embed(title="Confirmación de Cierre", description="El usuario ha solicitado cerrar este ticket. Un miembro del staff debe confirmar.", color=discord.Color.orange())
            view = TicketCloseConfirmView(self.cog, ticket, interaction.channel)
            await interaction.response.send_message(embed=embed, view=view)


class TicketCloseReasonView(discord.ui.View):
    def __init__(self, cog, ticket, channel, reasons):
        super().__init__(timeout=60)
        self.cog = cog
        self.ticket = ticket
        self.channel = channel
        
        options = [discord.SelectOption(label=r, value=r) for r in reasons[:24]]
        options.append(discord.SelectOption(label="Otro (Manual)", value="custom", emoji="📝"))
        
        self.select = discord.ui.Select(placeholder="Elige un motivo...", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        reason = self.select.values[0]
        if reason == "custom":
            await interaction.response.send_modal(TicketCloseReasonModal(self.cog, self.ticket, self.channel))
        else:
            await interaction.response.send_message(f"Cerrando ticket por: **{reason}**...", ephemeral=True)
            await self.cog.close_ticket(self.ticket, interaction.user, reason, self.channel)


class TicketModal(discord.ui.Modal):
    def __init__(self, cog, category):
        super().__init__(title=f"Ticket: {category['name']}")
        self.cog = cog
        self.category = category
        self.questions = json.loads(category.get("questions", "[]"))
        self.inputs = []
        
        if not self.questions:
            self.questions = ["¿En qué podemos ayudarte?"]
            
        for idx, q in enumerate(self.questions[:5]): # Max 5 for Discord Modals
            inp = discord.ui.TextInput(
                label=q[:45], 
                style=discord.TextStyle.paragraph if idx == 0 else discord.TextStyle.short,
                required=True
            )
            self.add_item(inp)
            self.inputs.append(inp)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog.create_ticket_channel(interaction, self.category, [i.value for i in self.inputs])


class TicketPanelView(discord.ui.View):
    def __init__(self, cog, categories=None):
        super().__init__(timeout=None)
        self.cog = cog

        # Para el registro persistente, options puede estar vacío (Discord reutiliza los del mensaje)
        opts = []
        if categories:
            for cat in categories:
                opts.append(discord.SelectOption(
                    label=cat["name"],
                    emoji=cat.get("emoji") or "🎫",
                    value=str(cat["id"])
                ))
        else:
            # Placeholder solo para registro; no se muestra al usuario en mensajes existentes
            opts = [discord.SelectOption(label="\u200b", value="0")]

        select = discord.ui.Select(
            placeholder="Selecciona una categoría...",
            options=opts,
            custom_id="ticket_panel_select"
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        cat_id = int(interaction.data["values"][0])
        if cat_id == 0:
            return await interaction.response.send_message("❌ Panel no configurado correctamente.", ephemeral=True)
        # Siempre re-leer desde DB para tener datos frescos
        categories = self.cog.db.get_ticket_categories(interaction.guild_id)
        category = next((c for c in categories if c["id"] == cat_id), None)

        if not category:
            return await interaction.response.send_message("❌ Categoría no encontrada. Regenera el panel con /tickets panel.", ephemeral=True)

        await interaction.response.send_modal(TicketModal(self.cog, category))


class Tickets(commands.Cog):
    """Módulo de Tickets Avanzado con RAG IA y Transcripciones HTML"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db # type: ignore

    def _sanitize_channel_name(self, name: str, max_len: int = 90) -> str:
        """Sanitiza un nombre para canal: lowercase, espacios→guiones, solo a-z0-9-_ y acorta."""
        s = name.lower()
        s = re.sub(r"\s+", "-", s)
        s = re.sub(r"[^a-z0-9-_]", "", s)
        s = re.sub(r"-{2,}", "-", s).strip("-")
        if not s:
            s = f"ticket-{int(datetime.now(timezone.utc).timestamp())}"
        return s[:max_len]

    async def create_ticket_channel(self, interaction: discord.Interaction, category: dict, answers: list):
        guild = interaction.guild
        config = self.db.get_ticket_config(guild.id)

        # ── Validaciones de límite/cooldown ───────────────────────────────────
        max_t = int(config.get("max_tickets_per_user") or 0)
        if max_t > 0:
            open_count = self.db.count_open_tickets_by_user(guild.id, interaction.user.id)
            if open_count >= max_t:
                return await interaction.followup.send(
                    f"❌ Ya tienes **{open_count}** ticket(s) abierto(s). "
                    f"El máximo permitido es **{max_t}**.",
                    ephemeral=True,
                )

        cooldown_secs = int(config.get("ticket_cooldown_seconds") or 0)
        if cooldown_secs > 0:
            last_str = self.db.get_last_ticket_time(guild.id, interaction.user.id)
            if last_str:
                last_dt = datetime.fromisoformat(last_str)
                now_dt = datetime.now(timezone.utc)
                elapsed = (now_dt - last_dt).total_seconds()
                if elapsed < cooldown_secs:
                    remaining = int(cooldown_secs - elapsed)
                    mins, secs = divmod(remaining, 60)
                    hrs, mins = divmod(mins, 60)
                    time_str = (
                        f"{hrs}h {mins}m {secs}s" if hrs > 0
                        else f"{mins}m {secs}s" if mins > 0
                        else f"{secs}s"
                    )
                    return await interaction.followup.send(
                        f"❌ Debes esperar **{time_str}** antes de abrir otro ticket.",
                        ephemeral=True,
                    )

        # Buscar la categoría en discord
        cat_id = config.get("category_id")
        discord_category = guild.get_channel(cat_id) if cat_id else interaction.channel.category
        
        # Generar entrada en BD y obtener número global
        ticket = self.db.create_ticket(guild.id, interaction.user.id, category["name"])
        global_num = ticket["global_number"]
        
        # Generar nombre del canal según plantilla y sanitizarlo
        name_template = config.get("channel_name_template", "⚒️{username}-{number}")
        raw_name = name_template.replace("{username}", interaction.user.name).replace("{number}", str(global_num))
        channel_name = self._sanitize_channel_name(raw_name)

        # Asegurar unicidad añadiendo sufijo si hace falta
        existing_names = {c.name for c in guild.text_channels}
        base_name = channel_name
        suffix = 1
        while channel_name in existing_names:
            channel_name = f"{base_name[:80]}-{suffix}"
            suffix += 1
        
        allowed_roles = json.loads(config.get("allowed_roles", "[]"))
        immune_roles = json.loads(config.get("immune_roles", "[]"))
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        for r_id in allowed_roles + immune_roles:
            role = guild.get_role(r_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                
        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=discord_category,
                overwrites=overwrites,
                topic=f"Ticket {global_num} - {interaction.user.id}"
            )
            
            self.db.update_ticket(ticket["id"], channel_id=channel.id)
            
            # Crear embed de bienvenida.
            # Prioridad: template_key (pool reutilizable) → welcome_embed_data inline.
            welcome_data = self._resolve_welcome_data(guild.id, category)
            if welcome_data:
                try:
                    from cogs.embeds import EmbedBuilder
                    builder = EmbedBuilder.from_json(welcome_data)
                    embed = builder.build()
                    # Reemplazar variables básicas en título/descripción si existen
                    if embed.title: embed.title = embed.title.replace("{username}", interaction.user.name).replace("{number}", str(global_num))
                    if embed.description: embed.description = embed.description.replace("{username}", interaction.user.name).replace("{number}", str(global_num))
                except Exception:
                    embed = discord.Embed(title=f"Ticket #{global_num} - {category['name']}", color=discord.Color.blurple())
            else:
                embed = discord.Embed(title=f"Ticket #{global_num} - {category['name']}", color=discord.Color.blurple())
                embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            
            # Siempre añadir las respuestas como campos
            questions = json.loads(category.get("questions", "[]"))
            if not questions: questions = ["¿En qué podemos ayudarte?"]
            
            for q, a in zip(questions, answers):
                embed.add_field(name=q[:256], value=a[:1024], inline=False)
                
            view = TicketTakeCloseView(self, ticket["id"])
            
            await channel.send(content=f"{interaction.user.mention} " + " ".join([f"<@&{r}>" for r in allowed_roles]), embed=embed, view=view)
            await interaction.followup.send(f"✅ Ticket creado: {channel.mention}", ephemeral=True)
            
            # Enviar log
            log_ch_id = config.get("log_channel_id")
            if log_ch_id:
                log_ch = guild.get_channel(log_ch_id)
                if log_ch:
                    await log_ch.send(f"📥 **Ticket Abierto:** #{global_num} por {interaction.user.mention} en la categoría `{category['name']}`.")
                    
        except Exception as e:
            logger.error(f"Error creando ticket: {e}")
            await interaction.followup.send("❌ Error al crear el canal del ticket.", ephemeral=True)

    async def close_ticket(self, ticket: dict, closer: discord.Member, reason: str, channel: discord.TextChannel):
        guild = channel.guild
        config = self.db.get_ticket_config(guild.id)
        now = datetime.now(timezone.utc).isoformat()
        
        self.db.update_ticket(ticket["id"], status="CLOSED", closed_at=now)
        
        # 1. Export HTML
        try:
            transcript = await chat_exporter.export(channel)
            if transcript:
                file = discord.File(io.BytesIO(transcript.encode()), filename=f"ticket-{ticket['global_number']}.html")
                log_ch_id = config.get("log_channel_id")
                
                if log_ch_id:
                    log_ch = guild.get_channel(log_ch_id)
                    if log_ch:
                        user = guild.get_member(ticket["user_id"])
                        username = user.mention if user else f"ID: {ticket['user_id']}"
                        staff = guild.get_member(ticket["staff_id"]) if ticket.get("staff_id") else None
                        staffname = staff.mention if staff else "Ninguno"
                        
                        embed = discord.Embed(title="Ticket Cerrado: #{ticket['global_number']}", color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
                        embed.add_field(name="Categoría", value=ticket["category_name"], inline=True)
                        embed.add_field(name="Usuario", value=username, inline=True)
                        embed.add_field(name="Atendido por", value=staffname, inline=True)
                        embed.add_field(name="Cerrado por", value=closer.mention, inline=True)
                        embed.add_field(name="Motivo", value=reason, inline=False)
                        
                        await log_ch.send(embed=embed, file=file)
        except Exception as e:
            logger.error(f"Error exportando ticket HTML: {e}")
            
        # 2. Trigger AI Summary - si la IA está disponible
        if hasattr(self.bot, 'get_cog'):
            ia_cog = self.bot.get_cog('IA')
            if ia_cog and hasattr(ia_cog, 'summarize_ticket'):
                asyncio.ensure_future(ia_cog.summarize_ticket(ticket, channel))
                
        # 3. Delete channel
        try:
            await channel.delete(reason=f"Ticket cerrado por {closer.name}")
        except discord.NotFound:
            pass

    @app_commands.command(name="añadir_usuario", description="Añade a un usuario al ticket actual")
    @app_commands.describe(usuario="El usuario a añadir")
    async def add_user(self, interaction: discord.Interaction, usuario: discord.Member):
        ticket = self.db.get_ticket_by_channel(interaction.channel.id)
        if not ticket or ticket["status"] != "OPEN":
            return await interaction.response.send_message("❌ Este comando solo se puede usar en un ticket abierto.", ephemeral=True)
            
        config = self.db.get_ticket_config(interaction.guild_id)
        allowed_roles = json.loads(config.get("allowed_roles", "[]"))
        immune_roles = json.loads(config.get("immune_roles", "[]"))
        user_roles = [r.id for r in interaction.user.roles]
        
        is_auth = interaction.user.id == ticket["user_id"] or interaction.user.guild_permissions.administrator or \
                  any(r in user_roles for r in allowed_roles + immune_roles)
                  
        if not is_auth:
            return await interaction.response.send_message("❌ No tienes permisos.", ephemeral=True)
            
        overwrites = interaction.channel.overwrites
        overwrites[usuario] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        await interaction.channel.edit(overwrites=overwrites)
        
        await interaction.response.send_message(f"✅ {usuario.mention} ha sido añadido al ticket por {interaction.user.mention}.")
        
        log_ch_id = config.get("log_channel_id")
        if log_ch_id:
            log_ch = interaction.guild.get_channel(log_ch_id)
            if log_ch:
                await log_ch.send(f"👥 **Usuario añadido:** {usuario.mention} fue añadido al ticket #{ticket['global_number']} por {interaction.user.mention}.")

    # ── Comandos de configuración eliminados ──────────────────────────────────
    # /tickets setup, /tickets panel_embed, /tickets category_add, /tickets panel
    # → Usa el Dashboard Web → Módulo Tickets para toda la configuración.
    #
    # El comando /tickets panel (spawn) se gestiona desde el dashboard:
    # selecciona el canal y pulsa "Enviar Panel" para enviarlo.

    # ── Resolución de plantillas (pool reutilizable) ──────────────────────────
    def _resolve_welcome_data(self, guild_id: int, category: dict):
        """
        Devuelve el JSON del embed de bienvenida para una categoría.

        Prioridad:
          1. category.welcome_embed_template_key → busca en ticket_template_embeds.
          2. category.welcome_embed_data → JSON inline (legacy).
          3. None — el caller usa un embed por defecto.
        """
        key = category.get("welcome_embed_template_key")
        if key:
            tpl = self.db.get_ticket_template(guild_id, key)
            if tpl and tpl.get("embed_data"):
                return tpl["embed_data"]
        return category.get("welcome_embed_data")

    def _resolve_panel_data(self, guild_id: int, config: dict):
        """
        Resuelve el JSON del embed del panel de selección.

        Prioridad:
          1. config.panel_select_template → ticket_template_embeds.
          2. config.panel_embed_data → JSON inline.
          3. None.
        """
        key = config.get("panel_select_template")
        if key:
            tpl = self.db.get_ticket_template(guild_id, key)
            if tpl and tpl.get("embed_data"):
                return tpl["embed_data"]
        return config.get("panel_embed_data")

    # ── Enviar panel desde dashboard (endpoint en API) ────────────────────────
    async def send_panel_to_channel(self, guild: discord.Guild, channel_id: int):
        """Envía el panel de tickets a un canal. Llamado desde el endpoint API."""
        categories = self.db.get_ticket_categories(guild.id)
        if not categories:
            return False, "No hay categorías configuradas"

        config = self.db.get_ticket_config(guild.id)
        panel_data = self._resolve_panel_data(guild.id, config)

        if panel_data:
            try:
                from cogs.embeds import EmbedBuilder
                embed = EmbedBuilder.from_json(panel_data).build()
            except Exception:
                embed = discord.Embed(
                    title="Soporte y Contacto",
                    description="Selecciona una categoría para abrir un ticket.",
                    color=discord.Color.green()
                )
        else:
            embed = discord.Embed(
                title="Soporte y Contacto",
                description="Selecciona una categoría para abrir un ticket.",
                color=discord.Color.green()
            )

        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return False, "Canal no encontrado"

        view = TicketPanelView(self, categories)
        await channel.send(embed=embed, view=view)
        self.db.set_ticket_config(guild.id, panel_channel_id=channel_id)
        return True, "Panel enviado correctamente"

async def setup(bot: commands.Bot):
    cog = Tickets(bot)
    await bot.add_cog(cog)
    # Registrar vistas persistentes para que sobrevivan reinicios del bot
    bot.add_view(TicketTakeCloseView(cog, 0))   # custom_ids fijos, ticket_id se lee de DB
    bot.add_view(TicketPanelView(cog))          # sin categorías; callback re-lee de DB

