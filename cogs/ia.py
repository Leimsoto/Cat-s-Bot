"""
cogs/ia.py — Módulo de IA
─────────────────────────
Sistema de IA conversacional con multi-API-key y selección de modelo por guild.

Funcionalidad:
  • Chat con historial por usuario/guild
  • Lectura multimodal (imágenes, PDFs, audio, vídeo)
  • System prompt configurable por guild (DB o .env como fallback)
  • Rate limiting (1 slot por REQUEST, no por token LLM)
  • Workers limpios con cog_load/cog_unload
  • Backoff exponencial frente a 429/quota
  • Métricas en memoria + /ia_estado

Modelos: solo Gemma 4 vía API de Gemini. Cualquier valor distinto en DB
(legados de Gemini 2.5/3, etc.) se migra al default ``gemma-4-26b-it`` en
``_resolve_client``.
  • gemma-4-26b-it           — default · 15 RPM · TPM ilimitado · 1.5K RPD
  • gemma-4-31b-it           — XL razonamiento · 15 RPM · TPM ilimitado · 1.5K RPD

Multimodal y grounding:
  La API de Gemini permite enviar adjuntos (imagen/audio/video/PDF) y
  habilitar Google Search grounding cuando el modelo subyacente es Gemma 4,
  igual que con Gemini. No hay degradación de features al cambiar de Gemini
  a Gemma 4 en esta API.

Multi-API-keys:
  El cog mantiene un pool de clientes (uno por API key registrada en la tabla
  ai_api_keys). El cliente para procesar un mensaje se elige según la key
  asignada al guild en ai_guild_keys. Si el guild no tiene key asignada, se
  intenta el fallback a GEMINI_API_KEY del .env.

Variables de entorno:
  GEMINI_API_KEY          — fallback si el guild no tiene key asignada
  AI_SYSTEM_PROMPT        — prompt base global (guild puede sobreescribir vía DB)
  AI_RATE_CAPACITY        — requests por periodo (default 10)
  AI_RATE_PERIOD          — periodo en segundos  (default 60)
  AI_CONCURRENCY          — llamadas paralelas    (default 2)
  AI_QUEUE_SIZE           — tamaño máx de cola    (default 64)
  AI_MIN_USER_INTERVAL    — cooldown por usuario  (default 4.0 s)
"""

import asyncio
import io
import logging
import os
import random
import re
from time import monotonic
from typing import Dict, List, Optional, Tuple

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types
except ImportError:
    genai = None
    genai_errors = None
    types = None

logger = logging.getLogger(__name__)

# ── Modelos ──────────────────────────────────────────────────────────────────
# UNICAMENTE Gemma 4 vía Google AI Studio. La API de Gemini sirve ambos modelos
# de Gemma con soporte multimodal (imágenes, audio, video, PDF) y grounding de
# búsqueda. Las variantes Gemini se eliminaron por decisión de producto — todo
# el flujo del bot va sobre Gemma 4.
#
# Cuotas del free tier (RPM / TPM / RPD):
#   gemma-4-26b-it    15 / ilimitado / 1.5K   (default)
#   gemma-4-31b-it    15 / ilimitado / 1.5K   (mejor razonamiento)
CHAT_MODELS = [
    "gemma-4-26b-it",             # default — Gemma 4 grande, TPM ilimitado
    "gemma-4-31b-it",             # Gemma 4 XL, TPM ilimitado
]

DEFAULT_MODEL = CHAT_MODELS[0]

# Etiquetas legibles para la UI.
_MODEL_LABELS = {
    "gemma-4-26b-it":         "Gemma 4 (26B)",
    "gemma-4-31b-it":         "Gemma 4 (31B)",
}

# ── MIME types aceptados como adjunto ────────────────────────────────────────
_MIME_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MIME_DOC   = {"application/pdf"}
_MIME_AUDIO = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg",
               "audio/flac", "audio/x-flac"}
_MIME_VIDEO = {"video/mp4", "video/mpeg", "video/mov",
               "video/quicktime", "video/avi", "video/webm"}
_MIME_ALL   = _MIME_IMAGE | _MIME_DOC | _MIME_AUDIO | _MIME_VIDEO

_EXT_MIME: Dict[str, str] = {
    ".jpg":  "image/jpeg",    ".jpeg": "image/jpeg",
    ".png":  "image/png",     ".gif":  "image/gif",
    ".webp": "image/webp",    ".pdf":  "application/pdf",
    ".mp3":  "audio/mpeg",    ".wav":  "audio/wav",
    ".ogg":  "audio/ogg",     ".flac": "audio/flac",
    ".mp4":  "video/mp4",     ".mov":  "video/quicktime",
    ".avi":  "video/avi",     ".webm": "video/webm",
}

_HISTORY_MAX   = 20    # turnos (user + model) a conservar por usuario
_DISCORD_MAX   = 1990  # margen bajo el límite de 2000 chars de Discord
_MAX_ATTACH_MB = 20    # MB máximos por adjunto


# ─────────────────────────────────────────────────────────────────────────────
#  Modal para editar el system prompt por guild
# ─────────────────────────────────────────────────────────────────────────────
class SystemPromptModal(discord.ui.Modal, title="System Prompt de IA"):
    prompt = discord.ui.TextInput(
        label="Prompt del sistema",
        style=discord.TextStyle.long,
        placeholder="Eres un asistente llamado Bot ES...",
        max_length=2000,
        required=False,
    )

    def __init__(self, cog: "IA", guild_id: int, current: str):
        super().__init__()
        self.cog      = cog
        self.guild_id = guild_id
        self.prompt.default = current or ""

    async def on_submit(self, interaction: discord.Interaction):
        value = self.prompt.value.strip() or None
        self.cog.db.set_ai_config(self.guild_id, ai_system_prompt=value)
        label = f"`{value[:60]}…`" if value and len(value) > 60 else (f"`{value}`" if value else "_(usando .env global)_")
        await interaction.response.send_message(
            f"✅ System prompt actualizado: {label}", ephemeral=True
        )


# ─────────────────────────────────────────────────────────────────────────────
#  UI de configuración del cog
# ─────────────────────────────────────────────────────────────────────────────
class IAConfigView(discord.ui.View):
    def __init__(self, cog: "IA", guild_id: int):
        super().__init__(timeout=180)
        self.cog      = cog
        self.guild_id = guild_id

        cfg     = self.cog.db.get_ai_config(guild_id)
        current = cfg.get("ai_model", CHAT_MODELS[0])
        label   = _MODEL_LABELS.get(current, current)

        # Botón dinámico de modelo (cicla entre los 3)
        self.model_btn = discord.ui.Button(
            label=f"Modelo: {label}",
            style=discord.ButtonStyle.primary,
            emoji="🤖",
            row=0,
        )
        self.model_btn.callback = self.cycle_model
        self.add_item(self.model_btn)

    async def cycle_model(self, interaction: discord.Interaction):
        cfg     = self.cog.db.get_ai_config(self.guild_id)
        current = cfg.get("ai_model", CHAT_MODELS[0])
        idx     = CHAT_MODELS.index(current) if current in CHAT_MODELS else 0
        new     = CHAT_MODELS[(idx + 1) % len(CHAT_MODELS)]
        self.cog.db.set_ai_config(self.guild_id, ai_model=new)
        self.model_btn.label = f"Modelo: {_MODEL_LABELS.get(new, new)}"
        embed = self.cog._build_ia_embed(interaction.guild, self.cog.db.get_ai_config(self.guild_id))
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Canal Chat", style=discord.ButtonStyle.secondary, emoji="💬", row=1)
    async def chat_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Menciona el canal de chat de IA (ej: #chat-ai) o escribe `none` para desactivarlo:", ephemeral=True
        )
        try:
            msg = await self.cog.bot.wait_for(
                "message",
                check=lambda m: m.author == interaction.user and m.channel == interaction.channel,
                timeout=60.0,
            )
            if msg.content.strip().lower() == "none":
                self.cog.db.set_ai_config(self.guild_id, ai_channel_id=None)
                await msg.delete()
                embed = self.cog._build_ia_embed(interaction.guild, self.cog.db.get_ai_config(self.guild_id))
                await interaction.edit_original_response(embed=embed, view=self)
            elif msg.channel_mentions:
                self.cog.db.set_ai_config(self.guild_id, ai_channel_id=msg.channel_mentions[0].id)
                await msg.delete()
                embed = self.cog._build_ia_embed(interaction.guild, self.cog.db.get_ai_config(self.guild_id))
                await interaction.edit_original_response(embed=embed, view=self)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="Rol Ping", style=discord.ButtonStyle.secondary, emoji="👥", row=1)
    async def role_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Menciona el rol permitido para usar @Bot (ej: @Premium):", ephemeral=True
        )
        try:
            msg = await self.cog.bot.wait_for(
                "message",
                check=lambda m: m.author == interaction.user and m.channel == interaction.channel,
                timeout=60.0,
            )
            if msg.role_mentions:
                self.cog.db.set_ai_config(self.guild_id, ai_role_id=msg.role_mentions[0].id)
                await msg.delete()
                embed = self.cog._build_ia_embed(interaction.guild, self.cog.db.get_ai_config(self.guild_id))
                await interaction.edit_original_response(embed=embed, view=self)
        except asyncio.TimeoutError:
            pass

    @discord.ui.button(label="System Prompt", style=discord.ButtonStyle.secondary, emoji="📝", row=1)
    async def prompt_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg     = self.cog.db.get_ai_config(self.guild_id)
        current = cfg.get("ai_system_prompt") or ""
        await interaction.response.send_modal(
            SystemPromptModal(self.cog, self.guild_id, current)
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Cog principal
# ─────────────────────────────────────────────────────────────────────────────
class IA(commands.Cog):
    """Módulo de Inteligencia Artificial – Gemini multimodal"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db  = bot.db  # type: ignore

        self._server_contexts: Dict[int, str]  = {}   # guild_id → contexto sincronizado
        self._chat_histories:  Dict[str, List] = {}   # "guild_user" → List[Content]

        # ── Pool de clientes ──────────────────────────────────────────────────
        # Cada API key tiene su propio Client. Se cachean por valor de la key
        # para evitar re-crear conexiones. El cliente fallback (env) se usa
        # cuando un guild no tiene key asignada.
        #
        # `client` se mantiene como alias del fallback para compatibilidad con
        # checks existentes (`if self.client: ...`); las llamadas reales pasan
        # por _get_client_for_guild().
        self._clients: Dict[str, "genai.Client"] = {}
        self._fallback_key: Optional[str] = os.getenv("GEMINI_API_KEY") or None

        if not genai:
            logger.warning("google-genai no instalado — el cog está cargado pero las llamadas fallarán.")
            self.client = None
        elif not self._fallback_key:
            logger.warning(
                "GEMINI_API_KEY no encontrada en .env. Los guilds sin key asignada "
                "en ai_api_keys no podrán usar IA."
            )
            self.client = None
        else:
            self.client = self._build_client(self._fallback_key)

        # ── Rate limiting: TOKEN BUCKET = 1 slot por REQUEST ─────────────────
        # (No tokens del LLM — eso causaba el bug de "excede")
        self._rate_cap    = int(os.getenv("AI_RATE_CAPACITY", "10"))
        self._rate_period = float(os.getenv("AI_RATE_PERIOD", "60"))
        self._rate_tokens = float(self._rate_cap)
        self._rate_last   = monotonic()
        self._rate_lock   = asyncio.Lock()

        # ── Concurrencia / cola ───────────────────────────────────────────────
        self._concurrency = int(os.getenv("AI_CONCURRENCY", "2"))
        self._semaphore   = asyncio.Semaphore(self._concurrency)
        self._queue: asyncio.Queue = asyncio.Queue(
            maxsize=int(os.getenv("AI_QUEUE_SIZE", "64"))
        )
        self._workers: List[asyncio.Task] = []

        # ── Per-user cooldown ─────────────────────────────────────────────────
        self._last_req:      Dict[int, float] = {}
        self._user_interval: float = float(os.getenv("AI_MIN_USER_INTERVAL", "4.0"))

        # ── Backoff por modelo ────────────────────────────────────────────────
        self._model_backoff:  Dict[str, float] = {}
        self._global_backoff: float = 0.0

        # ── Métricas ──────────────────────────────────────────────────────────
        self._metrics: Dict[str, float] = {
            "requests": 0, "success": 0, "retries": 0,
            "errors_429": 0, "errors_503": 0,
            "multimodal": 0,
            "queue_max": 0, "total_latency": 0.0, "latency_count": 0,
        }

        self._http: Optional[aiohttp.ClientSession] = None

    def _build_client(self, api_key: str) -> Optional["genai.Client"]:
        """Crea (o reutiliza del cache) un Client de google-genai por api_key."""
        if not genai or not api_key:
            return None
        if api_key not in self._clients:
            try:
                self._clients[api_key] = genai.Client(api_key=api_key)
            except Exception as e:
                logger.error(f"No se pudo crear cliente IA: {e}")
                return None
        return self._clients[api_key]

    def _get_client_for_guild(self, guild_id: int) -> Optional["genai.Client"]:
        """
        Devuelve el Client a usar para un guild concreto.

        Prioridad:
          1. Key asignada al guild en ai_guild_keys (si existe y está active).
          2. Fallback GEMINI_API_KEY del .env.
          3. None — el caller debe avisar al usuario.
        """
        try:
            assigned = self.db.get_ai_key_for_guild(guild_id)
        except Exception as e:
            logger.error(f"Error consultando ai_key_for_guild({guild_id}): {e}")
            assigned = None

        if assigned and int(assigned.get("active", 0)) and assigned.get("api_key"):
            return self._build_client(assigned["api_key"])

        if self._fallback_key:
            return self._build_client(self._fallback_key)

        return None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def cog_load(self):
        self._http = aiohttp.ClientSession()
        for i in range(self._concurrency):
            task = asyncio.create_task(
                self._worker_loop(i), name=f"ia_worker_{i}"
            )
            self._workers.append(task)

        # Migración: cualquier guild con un ai_model fuera del catálogo actual
        # (e.g. "gemini-3.1-flash" antiguo) se reasigna al default. Logs lo
        # reportan para auditoría. No bloquea el arranque si la query falla.
        try:
            self._migrate_invalid_models()
        except Exception as e:
            logger.warning(f"Migración de modelos IA omitida: {e}")

        logger.info(f"IA cog cargado – {self._concurrency} workers. "
                    f"Modelo primario: {DEFAULT_MODEL}")

    def _migrate_invalid_models(self) -> None:
        """Resetea ai_config.ai_model al default si el actual no está en CHAT_MODELS."""
        rows = self.db._fetchall(
            "SELECT guild_id, ai_model FROM ai_config WHERE ai_model IS NOT NULL", ()
        )
        valid = set(CHAT_MODELS)
        migrated = 0
        for r in rows:
            current = (r.get("ai_model") or "").strip()
            if current and current not in valid:
                self.db.set_ai_config(int(r["guild_id"]), ai_model=DEFAULT_MODEL)
                logger.info(
                    "Migración IA guild=%s: '%s' → '%s'",
                    r["guild_id"], current, DEFAULT_MODEL,
                )
                migrated += 1
        if migrated:
            logger.info("Migración IA: %d guilds actualizados al modelo default.", migrated)

    async def cog_unload(self):
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        if self._http and not self._http.closed:
            await self._http.close()
        logger.info("IA cog descargado limpiamente.")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _inc(self, key: str, v: float = 1.0) -> None:
        self._metrics[key] = self._metrics.get(key, 0.0) + v

    def _build_ia_embed(self, guild: discord.Guild, cfg: dict) -> discord.Embed:
        embed = discord.Embed(
            title="Configuración de Inteligencia Artificial",
            description="Controla cómo interactúa el bot con Gemini API.",
            color=discord.Color.purple(),
        )
        ch_id = cfg.get("ai_channel_id")
        embed.add_field(
            name="Canal Chat",
            value=f"<#{ch_id}>" if ch_id else "❌ No configurado",
            inline=True,
        )
        r_id = cfg.get("ai_role_id")
        embed.add_field(
            name="Rol Ping",
            value=f"<@&{r_id}>" if r_id else "❌ No configurado",
            inline=True,
        )
        model = cfg.get("ai_model", CHAT_MODELS[0])
        embed.add_field(
            name="Modelo primario",
            value=f"`{model}`\n_{_MODEL_LABELS.get(model, '')}_",
            inline=True,
        )
        sys_prompt = cfg.get("ai_system_prompt")
        embed.add_field(
            name="System Prompt",
            value=(f"_{sys_prompt[:80]}…_" if sys_prompt and len(sys_prompt) > 80
                   else (f"_{sys_prompt}_" if sys_prompt else "_Global (.env)_")),
            inline=False,
        )
        embed.set_footer(text="Multimedia: img/pdf/audio/video")
        return embed

    def _get_system_prompt(self, guild: discord.Guild) -> str:
        """
        Prioridad: 1) prompt por guild (DB)  2) .env  3) default hardcoded
        """
        cfg        = self.db.get_ai_config(guild.id)
        guild_prompt = cfg.get("ai_system_prompt")
        if guild_prompt and guild_prompt.strip():
            base = guild_prompt.strip()
        else:
            base = os.getenv(
                "AI_SYSTEM_PROMPT",
                "Eres un asistente amigable y útil llamado Bot ES. "
                "Puedes analizar imágenes, documentos PDF, audio y vídeo que te compartan. "
                "Si necesitas información actual usa Google Search.",
            )
        
        ctx = self._server_contexts.get(guild.id)
        if not ctx:
            ctx = self._generate_server_context(guild)
            self._server_contexts[guild.id] = ctx
            
        if ctx:
            base += f"\n\n{ctx}"
        return base

    def _generate_server_context(self, g: discord.Guild) -> str:
        owner = g.owner
        roles_list = [r for r in reversed(g.roles) if r.name != "@everyone"][:20]
        
        def is_public(channel) -> bool:
            # Evalúa si el canal es visible para el rol @everyone
            default_role = g.default_role
            overwrite = channel.overwrites_for(default_role)
            if overwrite.view_channel is False:
                return False
            if overwrite.view_channel is True:
                return True
            return default_role.permissions.view_channel

        public_text_channels = [c for c in g.text_channels if is_public(c)]
        public_voice_channels = [c for c in g.voice_channels if is_public(c)]
        
        parts = [
            "=== INFORMACIÓN DEL SERVIDOR (CONTEXTO) ===",
            f"Nombre del servidor: {g.name}",
            f"Descripción: {g.description or 'Ninguna'}",
            f"Cantidad de miembros: {g.member_count}",
            f"Dueño del servidor: {owner.display_name if owner else 'Desconocido'} " + (f"(Mención: <@{owner.id}>)" if owner else ""),
            
            "\n--- Canales de Texto ---",
            "IMPORTANTE: Para referirte a un canal de forma clickeable, DEBES usar su Mención exacta, ej: <#123456789>.",
            *[
                f"• #{c.name} -> Mención: <#{c.id}>" + (f" | Tema: {c.topic}" if c.topic else "")
                for c in public_text_channels[:30]
            ],
            
            "\n--- Canales de Voz ---",
            *[
                f"• 🔊 {c.name} -> Mención: <#{c.id}>"
                for c in public_voice_channels[:10]
            ],
            
            "\n--- Roles Principales ---",
            "IMPORTANTE: Para mencionar a un rol, DEBES usar el formato <@&ID>.",
            *[f"• {r.name} -> Mención: <@&{r.id}>" for r in roles_list],
            
            "\n--- Emojis del Servidor ---",
            "Puedes adornar tus respuestas usando estos emojis exactamente con el formato mostrado:",
            " ".join([f"{str(e)}" for e in g.emojis[:40]]) if g.emojis else "Ninguno",
            "==========================================="
        ]
        return "\n".join(parts)

    # ── Rate limiter (1 slot por request) ─────────────────────────────────────

    async def _acquire_slot(self, max_wait: float = 30.0) -> bool:
        start = monotonic()
        while True:
            async with self._rate_lock:
                now     = monotonic()
                elapsed = now - self._rate_last
                refill  = (elapsed / self._rate_period) * self._rate_cap
                self._rate_tokens = min(float(self._rate_cap), self._rate_tokens + refill)
                self._rate_last   = now
                if self._rate_tokens >= 1.0:
                    self._rate_tokens -= 1.0
                    return True
            if monotonic() - start > max_wait:
                return False
            await asyncio.sleep(0.5)

    # ── Descarga de adjuntos ──────────────────────────────────────────────────

    async def _fetch_attachment(
        self, attachment: discord.Attachment
    ) -> Optional[Tuple[bytes, str]]:
        mime = (attachment.content_type or "").split(";")[0].strip().lower()
        if not mime or mime in ("application/octet-stream", "binary/octet-stream"):
            ext  = os.path.splitext(attachment.filename)[1].lower()
            mime = _EXT_MIME.get(ext, "")
        if mime not in _MIME_ALL:
            return None
        if attachment.size > _MAX_ATTACH_MB * 1024 * 1024:
            logger.warning(f"Adjunto omitido (>20 MB): {attachment.filename}")
            return None
        try:
            async with self._http.get(
                attachment.url,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status != 200:
                    return None
                data = await r.read()
            return data, mime
        except Exception as e:
            logger.warning(f"No se pudo descargar adjunto '{attachment.filename}': {e}")
            return None

    # ── Construcción de partes Gemini ─────────────────────────────────────────

    async def _build_user_parts(
        self, message: discord.Message, user_text: str
    ) -> list:
        """
        Construye parts para el turno usuario: texto + adjuntos resueltos.
        Los adjuntos se descargan ANTES de encolar para evitar races.
        """
        parts = []
        if user_text:
            parts.append(types.Part.from_text(text=user_text))

        for att in message.attachments:
            result = await self._fetch_attachment(att)
            if result:
                data, mime = result
                parts.append(types.Part.from_bytes(data=data, mime_type=mime))
                self._inc("multimodal")
            else:
                parts.append(types.Part.from_text(
                    text=f"[Adjunto no procesable: {att.filename}]"
                ))

        if not parts:
            parts.append(types.Part.from_text(text="[Mensaje sin contenido]"))
        return parts

    # ── Generación con reintentos ─────────────────────────────────────────────

    async def _generate_with_retries(
        self,
        model: str,
        contents: list,
        config,
        retries: int = 3,
        backoff_base: float = 1.5,
        client: Optional["genai.Client"] = None,
    ):
        """
        Llama a Gemini con reintentos exponenciales por modelo.

        `client` permite pasar un Client específico (per-guild). Si no se
        proporciona, se usa self.client (fallback compartido).
        """
        active_client = client or self.client
        if active_client is None:
            raise RuntimeError("No hay cliente Gemini disponible para esta llamada.")
        last_exc: Optional[BaseException] = None

        def _extract_retry_delay(err) -> Optional[float]:
            try:
                msg = str(err)
                m = re.search(r'retry[\s_-](?:in|after)[:\s]+(\d+\.?\d*)\s*s', msg, re.I)
                if m:
                    return float(m.group(1))
                m2 = re.search(r'"retryDelay":\s*"(\d+\.?\d*)s"',
                               str(getattr(err, "details", "")))
                if m2:
                    return float(m2.group(1))
            except Exception:
                pass
            return None

        models_to_try = [model]

        for current_model in models_to_try:
            # Respetar backoff del modelo
            if self._model_backoff.get(current_model, 0.0) > monotonic():
                remain = int(self._model_backoff[current_model] - monotonic())
                logger.debug(f"Modelo {current_model} en backoff ({remain}s), saltando.")
                continue

            for retry in range(1, retries + 1):
                if not await self._acquire_slot():
                    last_exc = RuntimeError("Timeout esperando slot de rate limit local.")
                    break

                async with self._semaphore:
                    try:
                        resp = await asyncio.to_thread(
                            active_client.models.generate_content,
                            model=current_model,
                            contents=contents,
                            config=config,
                        )
                        self._inc("success")
                        return resp

                    except Exception as e:
                        last_exc = e
                        is_429 = is_503 = False
                        if genai_errors:
                            is_429 = isinstance(e, genai_errors.ClientError)
                            is_503 = isinstance(e, genai_errors.ServerError)
                        else:
                            msg_l = str(e).lower()
                            is_429 = "429" in msg_l or "quota" in msg_l or "resource_exhausted" in msg_l
                            is_503 = "503" in msg_l or "unavailable" in msg_l

                        if is_429:
                            self._inc("errors_429")
                            delay = _extract_retry_delay(e) or (backoff_base ** retry * 10)
                            self._model_backoff[current_model] = monotonic() + delay
                            logger.warning(
                                f"429 en {current_model} – backoff {delay:.0f}s."
                            )
                            break

                        if is_503:
                            self._inc("errors_503")
                            if retry < retries:
                                wait = (backoff_base ** retry) + random.uniform(0.0, 0.5)
                                self._inc("retries")
                                await asyncio.sleep(wait)
                                continue
                            break

                        # Error no retriable
                        logger.error(f"Error no retriable en {current_model}: {e}")
                        break

        raise last_exc or RuntimeError("La generación falló.")

    # ── Envío de respuesta ────────────────────────────────────────────────────

    async def _send_via_webhook(self, channel: discord.TextChannel, text: str):
        try:
            cfg = self.db.get_ai_config(channel.guild.id)
            webhook_name = cfg.get("ai_webhook_name") or "Bot ES IA"
            webhook_icon_url = cfg.get("ai_webhook_icon") or self.bot.user.display_avatar.url

            webhooks = await channel.webhooks()
            wh = discord.utils.get(webhooks, name="Bot_ES_IA")
            if not wh:
                wh = await channel.create_webhook(name="Bot_ES_IA")
            for chunk in [text[i : i + 1900] for i in range(0, len(text), 1900)]:
                await wh.send(
                    content=chunk,
                    username=webhook_name,
                    avatar_url=webhook_icon_url,
                )
        except Exception as e:
            logger.error(f"Error enviando por webhook: {e}")

    async def _send_reply(
        self, message: discord.Message, text: str, is_ai_channel: bool
    ):
        if is_ai_channel and isinstance(message.channel, discord.TextChannel):
            await self._send_via_webhook(message.channel, text)
        else:
            for chunk in [text[i : i + _DISCORD_MAX] for i in range(0, len(text), _DISCORD_MAX)]:
                await message.reply(chunk, mention_author=False)

    # ── Worker ────────────────────────────────────────────────────────────────

    async def _worker_loop(self, worker_id: int):
        logger.info(f"IA worker {worker_id} iniciado.")
        while True:
            job = await self._queue.get()
            try:
                await self._process_job(job)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
            finally:
                self._queue.task_done()

    async def _process_job(self, job: dict):
        message:       discord.Message = job["message"]
        ctx_id:        str             = job["ctx_id"]
        config                         = job["config"]
        is_ai_channel: bool            = job["is_ai_channel"]
        user_parts:    list            = job["user_parts"]

        # Global backoff
        if self._global_backoff > monotonic():
            wait = int(self._global_backoff - monotonic())
            try:
                await message.channel.send(
                    f"❌ IA en mantenimiento temporal, intenta en {wait}s."
                )
            except Exception:
                pass
            return

        # Cliente per-guild (key asignada en ai_guild_keys, o fallback env).
        guild_client = self._get_client_for_guild(message.guild.id)
        if guild_client is None:
            try:
                await message.channel.send(
                    "❌ No hay API key de IA disponible para este servidor. "
                    "Contacta con el administrador del bot."
                )
            except Exception:
                pass
            return

        # Elegir modelo disponible (respetando backoff individual). Si el guild
        # tiene un valor desconocido, caer al default en lugar de fallar.
        model_pref = self.db.get_ai_config(message.guild.id).get("ai_model") or DEFAULT_MODEL
        if model_pref not in CHAT_MODELS:
            logger.warning(
                "Guild %s usa modelo '%s' fuera del catálogo. Forzando default.",
                message.guild.id, model_pref,
            )
            model_pref = DEFAULT_MODEL

        chosen = model_pref if self._model_backoff.get(model_pref, 0.0) < monotonic() else None

        if not chosen:
            try:
                await message.channel.send(
                    "❌ Modelo temporalmente limitado. Intenta más tarde."
                )
            except Exception:
                pass
            return

        # Actualizar historial con el turno del usuario
        if ctx_id not in self._chat_histories:
            self._chat_histories[ctx_id] = []
        self._chat_histories[ctx_id].append(
            types.Content(role="user", parts=user_parts)
        )
        if len(self._chat_histories[ctx_id]) > _HISTORY_MAX:
            self._chat_histories[ctx_id] = self._chat_histories[ctx_id][-_HISTORY_MAX:]

        contents = list(self._chat_histories[ctx_id])

        try:
            async with message.channel.typing():
                t0 = monotonic()
                response = await self._generate_with_retries(
                    model=chosen,
                    contents=contents,
                    config=config,
                    client=guild_client,
                )
                self._inc("total_latency", monotonic() - t0)
                self._inc("latency_count")

            reply_text = getattr(response, "text", None) or "No pude generar una respuesta."

            # Guardar turno del modelo
            self._chat_histories[ctx_id].append(
                types.Content(role="model", parts=[types.Part.from_text(text=reply_text)])
            )
            if len(self._chat_histories[ctx_id]) > _HISTORY_MAX:
                self._chat_histories[ctx_id] = self._chat_histories[ctx_id][-_HISTORY_MAX:]

            await self._send_reply(message, reply_text, is_ai_channel)

        except Exception as e:
            logger.error(f"Error procesando job IA: {e}", exc_info=True)
            try:
                await message.channel.send("❌ Error al procesar la petición de IA.")
            except Exception:
                pass

    # ── Listener de mensajes ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            message.author.bot
            or getattr(message, "webhook_id", None)
            or not self.client
            or not message.guild
        ):
            return

        cfg           = self.db.get_ai_config(message.guild.id)
        ai_channel_id = cfg.get("ai_channel_id")
        ai_role_id    = cfg.get("ai_role_id")
        is_ai_channel = message.channel.id == ai_channel_id
        has_role      = (
            any(r.id == ai_role_id for r in message.author.roles) if ai_role_id else False
        )
        is_bot_ping = self.bot.user in message.mentions

        if not (is_ai_channel or (is_bot_ping and has_role)):
            return

        # Per-user cooldown
        now  = monotonic()
        last = self._last_req.get(message.author.id, 0.0)
        if now - last < self._user_interval:
            wait = int(self._user_interval - (now - last))
            try:
                await message.reply(
                    f"⏳ Espera {wait}s antes de otra consulta.", mention_author=False
                )
            except Exception:
                pass
            return

        # Texto limpio
        user_text = message.content.replace(f"<@{self.bot.user.id}>", "").strip()

        # Contexto de mensaje referenciado
        if message.reference and message.reference.message_id:
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)
                user_text = (
                    f"[Respondiendo a {ref.author.display_name}: «{ref.content[:200]}»]\n"
                    + user_text
                )
            except Exception:
                pass

        # Construir parts ANTES de encolar (descargas resueltas, sin races)
        try:
            user_parts = await self._build_user_parts(message, user_text)
        except Exception as e:
            logger.error(f"Error construyendo parts: {e}")
            user_parts = [types.Part.from_text(text=user_text or "[mensaje vacío]")]

        ctx_id = f"{message.guild.id}_{message.author.id}"

        config = types.GenerateContentConfig(
            system_instruction=self._get_system_prompt(message.guild),
            temperature=0.7,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        job = {
            "message":       message,
            "ctx_id":        ctx_id,
            "config":        config,
            "is_ai_channel": is_ai_channel,
            "user_parts":    user_parts,
        }

        try:
            self._queue.put_nowait(job)
            self._last_req[message.author.id] = now
            self._inc("requests")
            qsz = self._queue.qsize()
            if qsz > self._metrics.get("queue_max", 0):
                self._metrics["queue_max"] = qsz
        except asyncio.QueueFull:
            try:
                await message.reply(
                    "❌ Servidor de IA ocupado, intenta en unos segundos.", mention_author=False
                )
            except Exception:
                pass

    # ── Slash commands ─────────────────────────────────────────────────────────
    # Nota: /iaconfig e /iasync han sido eliminados.
    # La configuración de IA se realiza desde el Dashboard Web → Módulo IA.

    @app_commands.command(name="ia_estado", description="Métricas y estado del servicio IA")
    @app_commands.checks.has_permissions(administrator=True)
    async def ai_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        m       = self._metrics
        avg_lat = m["total_latency"] / max(1.0, m["latency_count"])

        embed = discord.Embed(title="📊 Estado del Servicio IA", color=discord.Color.blue())
        fields = [
            ("Cola actual",          str(self._queue.qsize())),
            ("Cola máx registrada",  str(int(m["queue_max"]))),
            ("Requests totales",     str(int(m["requests"]))),
            ("Respuestas OK",        str(int(m["success"]))),
            ("Reintentos (503)",     str(int(m["retries"]))),
            ("Errores 429",          str(int(m["errors_429"]))),
            ("Errores 503",          str(int(m["errors_503"]))),
            ("Adjuntos procesados",  str(int(m["multimodal"]))),
            ("Latency avg",          f"{avg_lat:.2f}s"),
            ("Concurrencia",         str(self._concurrency)),
            ("Rate (req/periodo)",   f"{self._rate_cap}/{self._rate_period:.0f}s"),
        ]
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)

        # Backoffs activos
        now = monotonic()
        backoffs = [
            f"`{mdl}`: {int(u - now)}s"
            for mdl, u in self._model_backoff.items()
            if u > now
        ]
        if self._global_backoff > now:
            backoffs.append(f"`GLOBAL`: {int(self._global_backoff - now)}s")
        embed.add_field(
            name="🚦 Backoffs activos",
            value="\n".join(backoffs) if backoffs else "✅ Ninguno",
            inline=False,
        )
        # Historial en memoria
        embed.add_field(
            name="🗃️ Historiales en RAM",
            value=f"{len(self._chat_histories)} usuarios",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)



    @app_commands.command(name="ia_limpiar", description="Borra tu historial de conversación con la IA")
    async def iaclear(self, interaction: discord.Interaction):
        ctx_id = f"{interaction.guild_id}_{interaction.user.id}"
        removed = ctx_id in self._chat_histories
        self._chat_histories.pop(ctx_id, None)
        msg = "✅ Historial de conversación borrado." if removed else "ℹ️ No tenías historial activo."
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(IA(bot))
