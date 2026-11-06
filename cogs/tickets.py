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
from cogs._role_safety import ticket_category_role_ids

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
        ticket = self.cog._authorized_open_ticket(interaction, self.ticket["id"])
        if ticket is None:
            return await interaction.response.send_message(
                "❌ El ticket ya no está abierto o tus permisos cambiaron.",
                ephemeral=True,
            )
        await interaction.response.send_message("Cerrando ticket y generando transcripción...", ephemeral=True)
        if not await self.cog.close_ticket(ticket, interaction.user, self.reason.value, interaction.channel):
            await interaction.followup.send(
                "❌ No se pudo cerrar el ticket; vuelve a intentarlo.",
                ephemeral=True,
            )


class TicketCloseConfirmView(discord.ui.View):
    def __init__(self, cog, ticket=None, channel=None):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket = ticket
        self.ticket_channel = channel

    @discord.ui.button(label="Confirmar Cierre (Staff)", style=discord.ButtonStyle.danger, custom_id="ticket_close_confirm")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        record = self.ticket or self.cog.db.get_ticket_by_channel(interaction.channel_id)
        ticket = self.cog._authorized_open_ticket(interaction, record["id"]) if record else None
        if ticket is None:
            return await interaction.response.send_message(
                "❌ El ticket ya no está abierto o tus permisos cambiaron.",
                ephemeral=True,
            )
            
        # Obtener categoría para ver motivos predefinidos
        category = self.cog._category_for_ticket(interaction.guild_id, ticket)
        reasons = json.loads(category.get("close_reasons", "[]")) if category else []
        
        if reasons:
            view = TicketCloseReasonView(self.cog, ticket, interaction.channel, reasons)
            await interaction.response.send_message("Selecciona el motivo del cierre:", view=view, ephemeral=True)
        else:
            await interaction.response.send_modal(TicketCloseReasonModal(self.cog, ticket, interaction.channel))


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
            
        if not self.cog._is_ticket_staff(interaction.user, ticket):
            return await interaction.response.send_message("❌ No tienes permiso para tomar tickets.", ephemeral=True)

        self.cog.db.update_ticket(ticket_id, staff_id=interaction.user.id)

        button.disabled = True
        button.label = f"Tomado por {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)
        from cogs._managed_messages import send_managed
        await send_managed(self.cog.bot, interaction.guild_id, "tickets", interaction.followup.send,
                           f"🛡️ {interaction.user.mention} se ha hecho cargo de este ticket.")

    @discord.ui.button(label="Cerrar", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = self.cog.db.get_ticket_by_channel(interaction.channel.id)
        if not ticket: return await interaction.response.send_message("Ticket no encontrado.", ephemeral=True)
        ticket_id = ticket["id"]
        
        if self.cog._is_ticket_staff(interaction.user, ticket):
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
        ticket = self.cog._authorized_open_ticket(interaction, self.ticket["id"])
        if ticket is None:
            return await interaction.response.send_message(
                "❌ El ticket ya no está abierto o tus permisos cambiaron.",
                ephemeral=True,
            )
        reason = self.select.values[0]
        if reason == "custom":
            await interaction.response.send_modal(TicketCloseReasonModal(self.cog, ticket, interaction.channel))
        else:
            await interaction.response.send_message(f"Cerrando ticket por: **{reason}**...", ephemeral=True)
            if not await self.cog.close_ticket(ticket, interaction.user, reason, interaction.channel):
                await interaction.followup.send(
                    "❌ No se pudo cerrar el ticket; vuelve a intentarlo.",
                    ephemeral=True,
                )


class TicketModal(discord.ui.Modal):
    def __init__(self, cog, category):
        super().__init__(title=f"Ticket: {category['name']}")
        self.cog = cog
        self.category_id = int(category["id"])
        self.questions = json.loads(category.get("questions", "[]"))
        self.inputs = []
        
        if not self.questions:
            self.questions = ["¿En qué podemos ayudarte?"]
            
        for idx, q in enumerate(self.questions[:5]): # Max 5 for Discord Modals
            inp = discord.ui.TextInput(
                label=q[:45], 
                style=discord.TextStyle.paragraph if idx == 0 else discord.TextStyle.short,
                required=True,
                max_length=1024,
            )
            self.add_item(inp)
            self.inputs.append(inp)

    async def on_submit(self, interaction: discord.Interaction):
        category = next(
            (
                current
                for current in self.cog.db.get_ticket_categories(interaction.guild_id)
                if int(current["id"]) == self.category_id
            ),
            None,
        )
        if category is None:
            return await interaction.response.send_message(
                "❌ Esta categoría ya no existe. Abre el panel de nuevo.",
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        await self.cog.create_ticket_channel(
            interaction, category, [i.value for i in self.inputs], questions=self.questions[:5]
        )


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
        self._staff_config_locks = {}

    def _staff_config_lock(self, guild_id):
        return self._staff_config_locks.setdefault(guild_id, asyncio.Lock())

    async def apply_staff_configuration(self, guild, previous_config, next_config, previous_categories, next_categories, save):
        async with self._staff_config_lock(guild.id):
            if (self.db.get_ticket_config(guild.id) != previous_config
                    or self.db.get_ticket_categories(guild.id) != previous_categories):
                raise RuntimeError("La configuración cambió durante el guardado; vuelve a intentarlo")
            await self.sync_staff_permissions(guild, previous_config, next_config, previous_categories, next_categories, grant=False)
            save()
            await self.sync_staff_permissions(guild, previous_config, next_config, previous_categories, next_categories, grant=True)

    def _category_for_ticket(self, guild_id: int, ticket: dict) -> dict | None:
        return next(
            (
                category
                for category in self.db.get_ticket_categories(guild_id)
                if category["name"] == ticket.get("category_name")
            ),
            None,
        )

    def _ticket_staff_role_ids(self, guild_id: int, category: dict | None = None) -> set[int]:
        config = self.db.get_ticket_config(guild_id)
        return self._staff_role_ids(guild_id, config, category)

    @staticmethod
    def _staff_role_ids(guild_id: int, config: dict, category: dict | None = None) -> set[int]:
        raw_ids = [
            *json.loads(config.get("allowed_roles") or "[]"),
            *json.loads(config.get("immune_roles") or "[]"),
        ]
        raw_ids.extend(ticket_category_role_ids(category))
        role_ids: set[int] = set()
        for role_id in raw_ids:
            try:
                if int(role_id) > 0 and int(role_id) != guild_id:
                    role_ids.add(int(role_id))
            except (TypeError, ValueError):
                continue
        return role_ids

    async def sync_staff_permissions(self, guild, previous_config, next_config, previous_categories, next_categories, *, grant=True):
        """Revoke before committing delegated roles; grant only after they are protected."""
        previous_by_name = {category["name"]: category for category in previous_categories}
        next_by_id = {category["id"]: category for category in next_categories}
        next_by_name = {category["name"]: category for category in next_categories}
        # Freeze OPEN tickets before Discord awaits; closes must not shift later pages.
        tickets = self.db.get_all_tickets(
            guild.id, status="OPEN", limit=self.db.count_open_tickets_by_guild(guild.id)
        )
        for ticket in tickets:
            category = previous_by_name.get(ticket.get("category_name"))
            next_category = next_by_name.get(ticket.get("category_name")) if grant else (next_by_id.get(category["id"]) if category else None)
            old_ids = self._staff_role_ids(guild.id, previous_config, category)
            new_ids = self._staff_role_ids(guild.id, next_config, next_category)
            changed_ids = new_ids if grant else old_ids - new_ids
            if not changed_ids:
                continue
            channel = guild.get_channel(ticket["channel_id"])
            if channel is None:
                try:
                    channel = await guild.fetch_channel(ticket["channel_id"])
                except discord.NotFound:
                    continue
            if channel.guild.id != guild.id:
                raise ValueError("El canal del ticket no pertenece al servidor")
            overwrites = channel.overwrites
            changed = False
            for role_id in changed_ids:
                role = guild.get_role(role_id)
                if role is None:
                    continue
                overwrite = channel.overwrites_for(role)
                if overwrite.view_channel is grant and overwrite.send_messages is grant:
                    continue
                overwrite.view_channel = grant
                overwrite.send_messages = grant
                overwrites[role] = overwrite
                changed = True
            if changed:
                await channel.edit(overwrites=overwrites, reason="Actualizar roles de soporte de tickets")


    def _is_ticket_staff(self, member: discord.Member, ticket: dict) -> bool:
        if member.id == member.guild.owner_id or member.guild_permissions.administrator:
            return True
        category = self._category_for_ticket(member.guild.id, ticket)
        allowed_ids = self._ticket_staff_role_ids(member.guild.id, category)
        return any(role.id in allowed_ids for role in member.roles)

    def _authorized_open_ticket(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
    ) -> dict | None:
        guild_id = interaction.guild_id
        channel = interaction.channel
        if guild_id is None or channel is None:
            return None
        ticket = self.db.get_ticket_by_channel(channel.id)
        if (
            not ticket
            or int(ticket["id"]) != int(ticket_id)
            or int(ticket["guild_id"]) != int(guild_id)
            or ticket.get("status") != "OPEN"
            or not self._is_ticket_staff(interaction.user, ticket)
        ):
            return None
        return ticket

    def _sanitize_channel_name(self, name: str, max_len: int = 90) -> str:
        """Sanitiza un nombre para canal: lowercase, espacios→guiones, solo a-z0-9-_ y acorta."""
        s = name.lower()
        s = re.sub(r"\s+", "-", s)
        s = re.sub(r"[^a-z0-9-_]", "", s)
        s = re.sub(r"-{2,}", "-", s).strip("-")
        if not s:
            s = f"ticket-{int(datetime.now(timezone.utc).timestamp())}"
        return s[:max_len]

    async def create_ticket_channel(
        self, interaction: discord.Interaction, category: dict, answers: list,
        *, questions: list[str] | None = None,
    ) -> discord.TextChannel | None:
        async with self._staff_config_lock(interaction.guild.id):
            current_category = next((current for current in self.db.get_ticket_categories(interaction.guild.id)
                                     if int(current["id"]) == int(category["id"])), None)
            if current_category is None:
                await interaction.followup.send("❌ Esta categoría ya no existe. Abre el panel de nuevo.", ephemeral=True)
                return None
            return await self._create_ticket_channel(interaction, current_category, answers, questions=questions)

    async def _create_ticket_channel(
        self, interaction: discord.Interaction, category: dict, answers: list,
        *, questions: list[str] | None = None,
    ) -> discord.TextChannel | None:
        guild = interaction.guild
        config = self.db.get_ticket_config(guild.id)

        # ── Validaciones de límite/cooldown ───────────────────────────────────
        max_t = int(config.get("max_tickets_per_user") or 0)
        if max_t > 0:
            open_count = self.db.count_open_tickets_by_user(guild.id, interaction.user.id)
            if open_count >= max_t:
                await interaction.followup.send(
                    f"❌ Ya tienes **{open_count}** ticket(s) abierto(s). "
                    f"El máximo permitido es **{max_t}**.",
                    ephemeral=True,
                )
                return None

        cooldown_secs = int(config.get("ticket_cooldown_seconds") or 0)
        if cooldown_secs > 0:
            last_str = self.db.get_last_ticket_time(guild.id, interaction.user.id)
            if last_str:
                last_dt = datetime.fromisoformat(last_str)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
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
                    await interaction.followup.send(
                        f"❌ Debes esperar **{time_str}** antes de abrir otro ticket.",
                        ephemeral=True,
                    )
                    return None

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
        
        staff_role_ids = self._ticket_staff_role_ids(guild.id, category)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        for r_id in staff_role_ids:
            role = guild.get_role(r_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = None
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
            template_content = None
            if welcome_data:
                try:
                    from cogs.embeds import EmbedBuilder
                    from cogs._message_payload import render_message_payload
                    data = json.loads(welcome_data) if isinstance(welcome_data, str) else welcome_data
                    if isinstance(data.get("embed"), dict):
                        rendered = render_message_payload(data, {"username": interaction.user.name, "number": str(global_num)})
                        embed = rendered["embed"] or discord.Embed(title=f"Ticket #{global_num}")
                        template_content = rendered["content"]
                    else:
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
            if questions is None:
                questions = json.loads(category.get("questions", "[]"))
            if not questions:
                questions = ["¿En qué podemos ayudarte?"]
            
            for q, a in zip(questions, answers):
                embed.add_field(name=q[:256], value=a[:1024], inline=False)
                
            view = TicketTakeCloseView(self, ticket["id"])
            
            role_mentions = " ".join(f"<@&{role_id}>" for role_id in sorted(staff_role_ids))
            from cogs._managed_messages import manage_payload
            from cogs._message_payload import parse_message_data
            managed = parse_message_data(welcome_data)
            payload = await manage_payload(self.bot, guild.id,
                {"content": " ".join(filter(None, (f"{interaction.user.mention} {role_mentions}".strip(), template_content))), "embed": embed, "view": view},
                enabled=managed.get("ai_managed") is True if managed else None, category="tickets",
                protected=(interaction.user.name, str(global_num), category["name"]))
            await channel.send(**payload)
            if not self.db.transition_ticket_status(ticket["id"], "CREATING", "OPEN"):
                raise RuntimeError("No se pudo activar el ticket reservado")
        except Exception as e:
            logger.exception("Error creando ticket #%s", global_num)
            if channel is not None:
                try:
                    await channel.delete(reason="Rollback: creación de ticket incompleta")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            if not self.db.transition_ticket_status(
                ticket["id"],
                "CREATING",
                "FAILED",
                closed_at=datetime.now(timezone.utc).isoformat(),
            ):
                self.db.update_ticket(
                    ticket["id"],
                    status="FAILED",
                    closed_at=datetime.now(timezone.utc).isoformat(),
                )
            await interaction.followup.send("❌ Error al crear el canal del ticket.", ephemeral=True)
            return

        try:
            await interaction.followup.send(f"✅ Ticket creado: {channel.mention}", ephemeral=True)
        except discord.HTTPException:
            logger.warning("Ticket #%s abierto; no se pudo enviar la confirmación", global_num)

        # El logging no revierte un ticket ya provisionado.
        log_ch_id = config.get("log_channel_id")
        if log_ch_id:
            log_ch = guild.get_channel(int(log_ch_id))
            if log_ch:
                try:
                    await log_ch.send(
                        f"📥 **Ticket Abierto:** #{global_num} por {interaction.user.mention} "
                        f"en la categoría `{category['name']}`."
                    )
                except (discord.Forbidden, discord.HTTPException) as exc:
                    logger.warning("No se pudo registrar apertura de ticket #%s: %s", global_num, exc)
        return channel

    async def close_ticket(self, ticket: dict, closer: discord.Member, reason: str, channel: discord.TextChannel):
        guild = channel.guild
        config = self.db.get_ticket_config(guild.id)
        current = self.db.get_ticket_by_channel(channel.id)
        if (
            not current
            or int(current["id"]) != int(ticket["id"])
            or int(current["guild_id"]) != int(guild.id)
            or current.get("status") != "OPEN"
            or not self._is_ticket_staff(closer, current)
        ):
            return False
        ticket = current
        if not self.db.transition_ticket_status(ticket["id"], "OPEN", "CLOSING"):
            logger.info("Ticket #%s ya estaba siendo cerrado o no está abierto", ticket.get("global_number"))
            return False
        
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
                        
                        embed = discord.Embed(title=f"Ticket Cerrado: #{ticket['global_number']}", color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
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
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.error("No se pudo borrar el canal del ticket #%s: %s", ticket["global_number"], exc)
            self.db.transition_ticket_status(ticket["id"], "CLOSING", "OPEN")
            try:
                await channel.send("❌ No pude completar el cierre del ticket; el estado fue restaurado.")
            except (discord.Forbidden, discord.HTTPException):
                pass
            return False

        self.db.transition_ticket_status(
            ticket["id"],
            "CLOSING",
            "CLOSED",
            closed_at=datetime.now(timezone.utc).isoformat(),
        )
        return True

    @app_commands.command(name="añadir_usuario", description="Añade a un usuario al ticket actual")
    @app_commands.describe(usuario="El usuario a añadir")
    async def add_user(self, interaction: discord.Interaction, usuario: discord.Member):
        ticket = self.db.get_ticket_by_channel(interaction.channel.id)
        if not ticket or ticket["status"] != "OPEN":
            return await interaction.response.send_message("❌ Este comando solo se puede usar en un ticket abierto.", ephemeral=True)
            
        config = self.db.get_ticket_config(interaction.guild_id)
        is_auth = interaction.user.id == ticket["user_id"] or self._is_ticket_staff(
            interaction.user, ticket
        )
                  
        if not is_auth:
            return await interaction.response.send_message("❌ No tienes permisos.", ephemeral=True)
            
        overwrites = interaction.channel.overwrites
        overwrites[usuario] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        await interaction.channel.edit(overwrites=overwrites)
        
        from cogs._managed_messages import send_managed
        await send_managed(self.bot, interaction.guild_id, "tickets", interaction.response.send_message,
                           f"✅ {usuario.mention} ha sido añadido al ticket por {interaction.user.mention}.")
        
        log_ch_id = config.get("log_channel_id")
        if log_ch_id:
            log_ch = interaction.guild.get_channel(log_ch_id)
            if log_ch:
                await send_managed(self.bot, interaction.guild_id, "tickets", log_ch.send,
                                   f"👥 **Usuario añadido:** {usuario.mention} fue añadido al ticket #{ticket['global_number']} por {interaction.user.mention}.")

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
        content = None

        if panel_data:
            try:
                from cogs.embeds import EmbedBuilder
                from cogs._message_payload import render_message_payload
                data = json.loads(panel_data) if isinstance(panel_data, str) else panel_data
                if isinstance(data.get("embed"), dict):
                    rendered = render_message_payload(data)
                    content, embed = rendered["content"], rendered["embed"]
                else:
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
        from cogs._managed_messages import manage_payload
        from cogs._message_payload import parse_message_data
        managed = parse_message_data(panel_data)
        payload = await manage_payload(self.bot, guild.id, {"content": content, "embed": embed, "view": view},
                                       enabled=managed.get("ai_managed") is True if managed else None, category="tickets")
        await channel.send(**payload)
        self.db.set_ticket_config(guild.id, panel_channel_id=channel_id)
        return True, "Panel enviado correctamente"

async def setup(bot: commands.Bot):
    cog = Tickets(bot)
    await bot.add_cog(cog)
    # Registrar vistas persistentes para que sobrevivan reinicios del bot
    bot.add_view(TicketTakeCloseView(cog, 0))   # custom_ids fijos, ticket_id se lee de DB
    bot.add_view(TicketCloseConfirmView(cog))  # solicitudes de cierre anteriores al reinicio
    bot.add_view(TicketPanelView(cog))          # sin categorías; callback re-lee de DB

