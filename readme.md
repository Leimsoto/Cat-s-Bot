<div align="center">

# Cat's Bot

<br/>

![Typing SVG](https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=700&size=18&pause=1000&color=A855F7&center=true&vCenter=true&width=600&height=40&lines=⚡+Bot+Multifuncional+para+Discord;🛡️+Moderación+•+🎵+Radio+•+🎮+Fun;🐱+Las+Tortuguitas+de+Ezku;🌐+Sistema+activo+24%2F7)

<br/>

[![Discord](https://img.shields.io/badge/─────%20UNIRSE%20AL%20SERVIDOR%20─────-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/invite/las-tortuguitas-de-ezku-1214414622111567892)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg?style=for-the-badge)](https://www.gnu.org/licenses/gpl-3.0)

<br/>

![](https://img.shields.io/badge/STATUS-ONLINE-22c55e?style=flat-square&logo=circle&logoColor=white)
![](https://img.shields.io/badge/TIPO-MULTIFUNCIONAL-a855f7?style=flat-square)
![](https://img.shields.io/badge/COMUNIDAD-LAS%20TORTUGUITAS%20DE%20EZKU-ec4899?style=flat-square)
![](https://img.shields.io/badge/LICENCIA-GPLv3-blue?style=flat-square)

</div>

<br/>

<img src="https://capsule-render.vercel.app/api?type=rect&color=7c3aed,ec4899&height=3&width=100%" width="100%"/>

<br/>

## `⚡` Descripción

> **Cat's Bot** es un bot **multifuncional** de código abierto desarrollado exclusivamente para la comunidad de **Las Tortuguitas de Ezku**.
> Integra de forma fluida herramientas de moderación, raido global funcional, entretenimiento y diversas utilidades en un solo sistema altamente estable y disponible las 24 horas del día.

<br/>

<img src="https://capsule-render.vercel.app/api?type=rect&color=7c3aed,ec4899&height=1" width="100%"/>

<br/>

## `🛠️` Arquitectura y Tecnologías

El sistema de **Cat's Bot** está construido con una arquitectura moderna que divide el motor del bot y su panel web de administración:

<div align="center">

| Componente | Tecnología | Descripción |
|:---|:---:|:---|
| **Motor del Bot** | `discord.py` | Core del bot en Python, utilizando `yt-dlp` para audio y `google-genai` para integraciones de IA. |
| **API Backend** | `FastAPI` | API REST asíncrona que conecta la base de datos, el bot en tiempo real y el dashboard web de forma segura (OAuth2/JWT). |
| **Dashboard Web**| `React + Vite` | Interfaz gráfica moderna y reactiva para gestionar las configuraciones del bot directamente desde el navegador. |
| **Base de Datos**| `SQLite` | Almacenamiento local estructurado para las configuraciones de servidores, perfiles de usuarios y auditoría. |

</div>

<br/>


## `🌐` Servidor

<div align="center">

### Las Tortuguitas de Ezku

[![Unirse](https://img.shields.io/badge/💜%20%20UNIRSE%20AL%20SERVIDOR%20%20💜-5865F2?style=for-the-badge&logo=discord&logoColor=white&labelColor=3b0764)](https://discord.com/invite/las-tortuguitas-de-ezku-1214414622111567892)

</div>

<br/>

## `👥` Contribuidores

<div align="center">

**Leimsoto** <br/>
**Arielteen** <br/>
**Claude AI**

</div>

<br/>

<img src="https://capsule-render.vercel.app/api?type=rect&color=7c3aed,ec4899&height=1" width="100%"/>

<br/>

## Moderación LLM con endpoint propio

En **Automoderación → Moderación IA**, un administrador escribe las reglas del
servidor. La conexión compartida se configura en **Endpoints**: URL base de una
API compatible con OpenAI (por ejemplo
`https://modelo.example/v1`) y selección de **Chat Completions** (predeterminado) o
**Responses** (`rules.llm.api_type`: `chat_completions` o `responses`). También
admite la ruta completa de la API seleccionada (`/v1/chat/completions` o
`/v1/responses`), su modelo,
una clave opcional y si admite imágenes. La moderación está desactivada por defecto y tiene su
propio interruptor; comparte los canales, roles y bots exentos de AutoMod. El
propietario y los administradores permanecen protegidos.

Las URL base `/v1` con o sin barra final añaden la ruta de la API seleccionada;
un dominio sin ruta utiliza `/v1/chat/completions` o `/v1/responses`. Las rutas
personalizadas se conservan literalmente. Una ruta estándar de la otra API
devuelve error de configuración; no se cambia de protocolo automáticamente.
Cambiar solo el tipo de API conserva la clave y las confirmaciones de la misma
URL. Cambiar la URL conserva la clave, pero requiere confirmar de nuevo los
permisos HTTP o privados que correspondan al destino nuevo.

Chat Completions conserva `response_format: {"type": "json_object"}` y
`reasoning_effort: "none"`. Responses usa `text.format: {"type": "json_object"}`,
`input` y `max_output_tokens`, sin imponer temperatura ni esfuerzo de razonamiento
dependientes del modelo. Se solicita una
decisión JSON breve, sin respuesta conversacional ni razonamiento, con un máximo
de 512 tokens; las sanciones incluyen una razón corta y una sola evidencia.
Si el proveedor rechaza estas opciones, devuelve prosa o corta la respuesta, se
registra un error y no se aplica una sanción.

Responses utiliza `store: false`, sin `previous_response_id` ni conversaciones
guardadas en el proveedor. Lee el texto de los elementos `message` de `output`,
convierte imágenes a `input_image` y conserva los `call_id` de funciones. Solo
el bucle público de herramientas mantiene temporalmente los elementos de salida
y razonamiento cifrado necesarios para continuar; no se guardan en la memoria
del bot. Respuestas incompletas, fallidas, rechazadas o herramientas no ofrecidas
se descartan. El chat, la moderación y la redacción opcional comparten esta
implementación, basada en la documentación oficial de [migración a Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses),
[funciones](https://developers.openai.com/api/docs/guides/function-calling) e
[imágenes](https://developers.openai.com/api/docs/guides/images-vision).

El contexto incluye el mensaje actual más **0–50 mensajes anteriores del mismo
canal o hilo**, del mismo usuario o de toda la conversación. Para encontrar los
del usuario se revisan como máximo los últimos 500 mensajes; se conservan orden
y fechas. El contexto anterior es solo texto y nunca puede ser el objetivo de
una sanción. Los mensajes nuevos y las ediciones, incluso sin caché, se revisan
mientras el bot esté conectado y tenga acceso al canal y al historial.

Los replies del mensaje actual y del historial conservan el ID del mensaje
respondido y distinguen a sus autores. Si el objetivo ya está en la ventana,
se reutiliza; fuera de ella se consultan hasta tres objetivos directos únicos,
priorizando el reply actual y después los del historial más reciente. Solo se
lee el mismo canal/hilo y servidor, con permisos del bot para ver el canal y
leer el historial, con un máximo de tres segundos por consulta, sin seguir cadenas.
Se incluyen hasta 4000 caracteres por mensaje contextual, indicando los recortes;
los adjuntos y embeds de las referencias no se leen. En modo usuario, el historial
sigue siendo suyo, pero un reply puede aportar el texto de otro autor como contexto.
Con **0 mensajes** se conserva solo el ID de la relación, sin leer ni enviar el
mensaje respondido. Los objetivos borrados, inaccesibles o fuera de estos límites
se indican como desconocidos. El modelo recibe instrucciones de interpretar
flujo, citas, bromas y ambigüedad según las reglas, sin inventar intención ni
usar el contexto como evidencia sancionable; esto no garantiza eliminar todos
los falsos positivos.

El modelo elige ninguna acción, solo eliminar el mensaje (`delete`), warn, mute,
kick o ban. Delete no añade una sanción al usuario. Los warns no caducan y
kick no tiene duración; mute admite 60 segundos a 28 días, y ban puede ser
permanente o temporal hasta 365 días. Se reutilizan los casos, jerarquías,
permisos, bloqueos y tareas de expiración existentes; **mute requiere el rol de
mute configurado y efectivo**. Las decisiones sancionadas eliminan también el
mensaje mediante el ejecutor de AutoMod. Warn registra únicamente el warn
elegido y no añade otra sanción por los umbrales legacy.
Cuando Discord confirma el borrado, se menciona al autor en el mismo canal o
hilo con un aviso breve del motivo y la regla aplicada. El motivo queda en el
historial y el caso conserva la evidencia; el canal de moderación muestra también el
motivo y si se pudo borrar. Si el borrado falla no se publica un aviso de éxito;
si falla el aviso en el canal, se registra sin impedir la sanción ni enviar privados.

Con imágenes activadas se envían hasta cuatro adjuntos/stickers PNG, JPEG o
WebP del mensaje actual, con 8 MiB combinados. No se descargan imágenes de
enlaces del texto. Audio, vídeo, documentos, embeds y medios no leídos se marcan
como cobertura parcial y no pueden aportar evidencia; el texto disponible sigue
revisándose. El contenido y contexto se envían al endpoint elegido por el
administrador. La clave se guarda en la BD: la API solo devuelve si existe;
omitirla, dejarla vacía o enviar `null` significa **Sin cambios**, incluso al
cambiar la URL. Una clave nueva la reemplaza; **Eliminar clave guardada** envía
`api_key_clear: true` y es la única forma de borrarla. Al cambiar de destino sin
reemplazarla, la clave conservada se enviará al nuevo endpoint: revisa el host
antes de guardar.

HTTPS público funciona sin confirmación adicional. El primer **Guardar** de
una URL HTTP muestra un aviso con la URL concreta: el tráfico y la clave viajan
sin cifrar, y el destino puede ser un servicio de la red del bot. El segundo
**Guardar** confirma esa URL para ese servidor, sin editar `.env`. El panel
puede confirmar HTTP y acceso privado en ese mismo segundo clic.

Los endpoints de loopback (`127.0.0.1`, `::1`), LAN RFC1918 y IPv6 ULA requieren
consentimiento privado para la URL exacta en
`rules.llm.private_endpoint_confirmed_url`; HTTP conserva además
`rules.llm.insecure_http_confirmed_url`. La API comprueba DNS al cambiar el
destino, devuelve `409` (`private_confirmation_required` o
`http_confirmation_required`) con `required_confirmations` cuando falta un
consentimiento, y no guarda nada. Un fallo de DNS devuelve un error sin guardar
ni conceder acceso privado. Una resolución pública elimina el consentimiento
privado sobrante. Cambiar esquema, host, puerto o ruta invalida los consentimientos
anteriores; las ediciones ajenas al destino conservan la aprobación guardada.

El acceso privado del panel se limita a la base, `/v1`,
`/v1/chat/completions` o `/v1/responses`, con o sin barra final, y a sus consultas auxiliares
reconocidas de modelos y conteo de tokens. Cada petición utiliza un conector
propio ligado al host y puerto aprobados; las direcciones DNS se revisan también
al conectar. No se permiten redirecciones, proxies de entorno, direcciones de
metadatos/link-local, multicast, reservadas ni sin especificar. El consentimiento
de un servidor no autoriza los destinos de otro ni las descargas de imágenes.
La autorización previa del operador mediante `CATBOT_LLM_ALLOWED_HOSTS` conserva
su comportamiento legado; el flujo del panel no modifica esa lista.

Se rechazan URLs con credenciales, query o fragmento. Moderación, chat y redacción
opcional comparten estas reglas. `GET/PATCH /api/guilds/{id}/endpoints` permite a
administradores leer/editar solo la conexión mediante `{"llm": {...}}`, sin
cambiar reglas, exenciones ni interruptores de moderación. La API nunca devuelve
la clave; publica `api_key_configured`. La configuración sigue guardada en
`automod_config.rules.llm`, sin migrar ni eliminar los datos existentes.

**Endpoints** reúne también proveedor y modelo Gemini, estado de la clave
asignada del pool e identidad del webhook de respuestas. Reutiliza `/ia` y
`/ia/key`; la asignación del pool sigue siendo exclusiva del administrador del
bot. Discord crea y gestiona ese webhook: el panel no solicita su URL ni token.

La cola admite 100 trabajos y dos revisiones simultáneas. Cada petición tiene
45 segundos de límite; los trabajos con más de 120 segundos de espera se
descartan. Los resultados y omisiones aparecen en el historial de AutoMod con
regla `llm`: `none`, acciones confirmadas, `partial_coverage`, cola llena,
trabajos obsoletos, respuestas inválidas, errores o ejecución no confirmada.
Un fallo del endpoint, una respuesta sin JSON válido/evidencia del mensaje
actual, una edición posterior o un cambio de reglas impide la sanción. No hay
revisión retroactiva de mensajes publicados sin conexión ni reintentos de
trabajos descartados; el modelo puede equivocarse aunque su respuesta sea válida.

## Chat Strata y recuerdos persistentes

El módulo **IA** puede conversar mediante el mismo endpoint, clave y modelo
configurados en **Endpoints**. La moderación puede estar
apagada: el chat utiliza una petición independiente de respuesta natural, sin
el contrato JSON de clasificación ni capacidad de ejecutar sanciones.
La conversación se identifica como parte del mismo bot que ejecuta AutoMod.
La herramienta de solo lectura `read_my_moderation_history` consulta hasta ocho
registros recientes cuando se pide explícitamente. Los miembros normales solo
consultan sus propios registros del mismo servidor y canal. El propietario o un
miembro con permiso real **Administrador**, verificado con el propietario, roles
y miembro actuales de Discord, también puede consultar otro usuario del mismo
servidor mediante una mención, ID exacto o un `@nombre` que coincida exactamente
con un único miembro en la caché de ese servidor. No basta llamarse Administrador.
Una mención breve puede continuar una pregunta del bot sobre a quién consultar;
se verifica de nuevo ese mensaje del bot, sin adivinar nombres ni objetivos.

Los motivos privados o de otros canales solo se muestran en un canal de texto
probado exclusivo de administradores: `@everyone` tiene una denegación explícita
de ver el canal y ningún rol sin Administrador ni otro miembro tiene una concesión
individual de verlo. Los hilos nunca se consideran un destino exclusivo de
administradores. En otros destinos se muestran detalles compatibles del canal
actual y resúmenes de acción/estado, sin revelar motivos privados de otros canales.

No se carga historial en saludos. Una validación aislada recibe solo el texto
actual y el objetivo/permisos fijados por el código; los recuerdos, imágenes y
otros participantes no autorizan consultas. Falla cerrada y añade una petición
solo cuando se solicita historial. Se distinguen estados pendientes, fallidos,
revocados y expirados. Propietario, roles, canal y miembros se consultan en paralelo
en cada validación; cambios de permisos, audiencia o registros descartan respuestas
obsoletas antes del modelo o de publicarlas. La ausencia de registros no prueba
que no hubiera una acción. El chat no obtiene herramientas para sancionar.

El proveedor `auto` usa Strata cuando hay endpoint y modelo; conserva Gemini
en los servidores sin esa conexión. `strata` y `gemini` permiten elegir
explícitamente. Las claves y modelos legados se conservan. Las herramientas de historial y web requieren un endpoint/modelo compatible con
herramientas nativas OpenAI. Con web apagada, un rechazo explícito de herramientas
permite un único reintento de chat básico sin ellas ni registros de moderación;
un error HTTP genérico no provoca ese reintento.

El bot contesta cuando lo mencionan o responden a uno de sus mensajes reales,
incluso con la mención de respuesta desactivada y aunque el mensaje del bot sea
anterior al reinicio. El modo **Todos** responde además en el canal IA y sus
hilos; los servidores nuevos usan **Menciones**. Fuera del canal IA se exige el
rol IA cuando está configurado. Siempre se respetan acceso al canal, reglas
locales, rol global y moderación; no se contesta a otros bots o webhooks.

Las respuestas notifican al autor mediante reply solo en el primer fragmento. Las menciones
`<@ID>` o `@nombre` inequívocas se convierten en menciones reales únicamente para
el autor y los miembros seleccionados explícitamente en el mensaje actual;
cada miembro recibe como máximo una notificación por respuesta, en el primer
fragmento donde se lo mencione, aunque sea una continuación. Roles y `@everyone` no
pueden generar notificaciones. Gemini aplica la misma política a respuestas
normales y a su webhook, que menciona al autor al comenzar.

Hay tres ámbitos, separados por servidor:

- **Chat:** cantidad configurable de mensajes recientes con ID, autor y orden por canal o hilo,
  conservados como máximo 30 días, más una nota duradera administrada. En el
  canal IA se observan mensajes autorizados aunque no pidan respuesta; fuera
  de él solo se guardan turnos dirigidos al bot. No hay lectura retroactiva ni
  importación del corpus RAG. `ai_memory_messages` admite de 0 a 5000 mensajes
  por chat, con 40 por defecto; 0 desactiva ese historial, conservando el mensaje
  actual y las notas duraderas. Subir el límite no recupera mensajes descartados.
  La lectura aplica el límite de inmediato; el recorte almacenado se realiza
  en las siguientes escrituras. Cada fragmento enviado por el bot cuenta como
  un mensaje, igual que los turnos de las personas.
- **Persona:** `/ia_memoria accion:guardar ambito:user texto:…` reemplaza tu
  recuerdo del canal actual, hasta 2000 caracteres. Se guardan hasta 20 notas
  por persona y servidor. Solo se aplica el perfil de quien solicita respuesta,
  como preferencias no confiables que nunca sustituyen las reglas.
  Por defecto queda confinado al canal. `compartir_en_servidor:True` permite
  usarlo al responderte en otros chats únicamente si se guardó en un canal de
  texto público que sigue siendo legible para `@everyone`. Canales privados e
  hilos quedan confinados aunque se solicite compartir. El comando confirma
  esa procedencia de forma efímera; el recuerdo puede aparecer en las respuestas
  visibles del bot.
- **Servidor:** una nota deliberadamente compartida por dueño o Administrator,
  disponible en todo el servidor. Se administra desde IA o con `/ia_memoria
  ambito:global`; `ambito:chat` gestiona la nota del chat actual. Ningún mensaje
  normal se convierte automáticamente en memoria global ni en una regla.

`/ia_memoria accion:ver` muestra tus notas de forma efímera. `accion:borrar`
en el perfil, o `/ia_limpiar`, elimina tus notas, tus turnos guardados y las
respuestas del bot dirigidas a ti, incluso si el turno original ya salió del
límite configurado. Conserva los mensajes independientes de otras personas;
no promete borrar sus paráfrasis ni elimina mensajes de Discord. El borrado del
ámbito chat retira su nota e historial completos. Editar o eliminar un mensaje
guardado retira ese turno y las respuestas originadas por él, conservando los
demás; eventos de mensajes no guardados no vacían conversaciones. No se pueden
reconciliar ediciones/borrados ocurridos mientras el bot estaba desconectado.
Las notas permanecen hasta reemplazarlas o borrarlas; los turnos vencidos se
excluyen al leer y se purgan con las siguientes escrituras.

El número guardado es distinto del que cabe en cada petición. El presupuesto
de contexto se configura manualmente en **Endpoints** con
`llm.context_window_tokens`: entre 4096 y 1048576 tokens, predeterminado 262144
(256K), con accesos a 256K y 512K. Es un límite declarado por el administrador,
reducido si Strata informa una ventana menor mediante `/v1/models`; aumentarlo
no amplía la capacidad real del servidor. Reserva 2048 tokens para plantilla,
16384 por imagen como margen estimado y la misma salida que solicita al modelo:
1000 con razonamiento Off, 8192 con Auto/Low/Medium y 16384 con High/Max.
Deep Think reserva al menos 16384. Se cuentan primero
reglas, notas, mensaje actual, referencias y resultados web; solo se recortan
los mensajes recientes más antiguos. Si ese contexto obligatorio no cabe, se
informa del problema sin eliminar silenciosamente las reglas o el mensaje actual.

Cuando existe `/v1/messages/count_tokens` (Chat Completions) o
`/v1/responses/input_tokens` (Responses), se hacen hasta cuatro conteos del
texto renderizado para ajustar el historial, con un límite previo de 2 MiB de
texto por petición. Las rutas auxiliares solo se derivan del mismo origen y
prefijo de un endpoint reconocido `/v1/chat/completions` o `/v1/responses`, sin redirects; la
metadata se conserva cinco minutos, hasta 32 entradas. Las respuestas de
contador 404/405/501 también se recuerdan cinco minutos, hasta 32 conexiones,
para no repetir una ruta ausente en cada turno; cambiar endpoint, modelo o
clave invalida esa asociación. Si esas rutas no están
disponibles se usa un límite conservador de bytes UTF-8, que aprovecha menos
ventana y **no es un conteo exacto de tokens**. El conteo nativo tampoco incluye
el preprocesado visual: su margen es estimado y el proveedor aún puede rechazar
un contexto multimodal grande. No se han comprobado aquí peticiones reales de 256K o 512K.

La API administrativa expone `GET/PUT/DELETE /api/guilds/{id}/ia/memory`, con
`scope=global` o `scope=chat&channel_id=…`. `PUT` acepta `{"content":"…"}`
(máximo 2000 caracteres) y reemplaza solo la nota; `DELETE` de chat elimina
también su historial. Las notas de usuario se gestionan mediante comandos,
no se publican en el dashboard. Los cambios y borrados invalidan las respuestas
en curso del ámbito afectado. Chats distintos pueden procesarse en paralelo;
los turnos de una misma persona y chat mantienen el orden, con cola acotada y
descarte a los 120 segundos. Otras personas del mismo chat pueden recibir
respuesta mientras una investigación lenta sigue en curso, sin superar el
límite global de workers (`AI_CONCURRENCY`, 2 por defecto).

Strata interpreta imágenes del mensaje actual y de referencias explícitas
del mismo canal, incluidas imágenes antiguas fuera del historial guardado.
Las respuestas al bot siguen la cadena de respuestas y su origen persistido,
con un máximo de seis mensajes fuente; también se aceptan enlaces explícitos
a mensajes del mismo servidor y canal. Las imágenes y stickers compatibles
comparten un máximo de cuatro y 8 MiB por petición, solo cuando la conexión
declara soporte. No se conservan archivos ni URLs de adjuntos en la memoria;
se consultan de nuevo en Discord y una fuente editada o eliminada durante la
petición descarta la respuesta. PDF, audio, vídeo y embeds no se leen ni se
inventan. La conexión conserva los límites y protecciones del endpoint de
moderación (respuesta acotada, DNS y URL validados, sin redirects). El chat
permite hasta 180 segundos por petición, o 300 con Deep Think; la moderación
conserva su límite independiente de 45 segundos.
Las tablas se crean de forma aditiva al iniciar el runtime SQLite; esta función
no habilita los motores PostgreSQL/MariaDB todavía no soportados.

### Razonamiento y Deep Think

**Endpoints** separa `llm.chat_reasoning_effort` del razonamiento del planificador
web, `llm.web_reasoning_effort`. Ambos conservan Off (`none`) como valor inicial.
Las opciones son **Off, Auto, Low, Medium, High y Max**. Auto omite el parámetro
para respetar la configuración del servidor; los demás valores se envían
literalmente como `reasoning_effort` en Chat Completions o `reasoning.effort`
en Responses. Max no se sustituye por High: [Strata 0.2.9](https://github.com/Niko1221/Strata/blob/v0.2.9/serve/frontend.py#L134-L169)
lo adapta según la familia del modelo. La reserva incluye tokens de pensamiento
y respuesta, como documenta [Strata](https://github.com/Niko1221/Strata/blob/v0.2.9/docs/DETAILS.md#L469).
Esto no modifica el contrato breve y sin razonamiento de moderación.

**IA → Deep Think** (`ai_deep_think`, desactivado por defecto) amplía el trabajo
para preguntas complejas y, con Internet habilitado, la investigación pública.
No cambia el interruptor independiente `ai_web_enabled` ni autoriza enviar
consultas privadas de permisos/moderación a la web.

### Investigación web opcional

`ai_web_enabled` habilita búsqueda pública con DuckDuckGo y lectura de páginas
con Chrome Headless, exclusivamente en Strata. Está apagado por defecto.
Necesita las dependencias y la instalación de Chrome descritas en
[`deploy/wsl/WEB_BROWSER.md`](deploy/wsl/WEB_BROWSER.md); no utiliza el perfil ni las sesiones del navegador
del usuario. Solo permite lectura pública, sin inicios de sesión, formularios
ni acciones externas.

Con Internet habilitado, la primera petición conversa con el contexto
autorizado y puede devolver directamente una respuesta normal. Si necesita
información pública, solicita `request_public_web_research` con un
`public_brief`: tema público (hasta 200 caracteres) y pregunta autónoma
(hasta 600). Puede resolver seguimientos como «busca sobre eso» a partir de la
conversación autorizada, sin exportar el historial completo. El planificador
separado recibe únicamente ese resumen público, sin perfiles, notas personales,
reglas del servidor ni metadatos de Discord. La validación rechaza identificadores
privados evidentes; no es un clasificador semántico de privacidad. Si el tema es
ambiguo o privado, se pide aclaración. Solo la consulta necesaria se envía a
DuckDuckGo. La respuesta final recibe el contexto autorizado y los resultados
web como datos no confiables; las páginas no pueden convertirse en reglas ni
recuerdos globales.

La investigación no tiene una cuota total de búsquedas, páginas, rondas ni
tiempo conjunto. El modelo decide cuándo la pregunta está cubierta con evidencia
suficiente y ha resuelto sus dudas materiales. Un reporte insuficiente es un
checkpoint para seguir investigando, no una respuesta final. Si falta una precisión
esencial del usuario, puede pedirla de forma concreta. Deep Think exige más
contraste y examina interpretaciones alternativas, sin cambiar cuotas de búsqueda.
Esto puede aumentar la latencia, los tokens y el coste del proveedor. Se mantienen
los límites técnicos de cada petición: ventana de contexto/salida y timeouts del
modelo (180 segundos, 300 con Deep Think), búsqueda y lector web. Los errores
reales y el estancamiento con peticiones y evidencia idénticas se tratan como
fallos, sin presentar una investigación incompleta como terminada. Puede refinar consultas
y seguir enlaces de páginas leídas, priorizando fuentes oficiales y contrastando
fechas de publicación, actualización y del hecho. La antigüedad no excluye por sí
sola documentación oficial relevante. Cada petición al modelo consume su propio turno del límite de uso.
Una charla que no necesita Internet usa una única petición al modelo; una
investigación añade las rondas necesarias del planificador aislado y una
respuesta final con resultados. El reloj UTC real se incorpora después de las
esperas y validaciones, en cada petición al modelo; no se inventa la zona horaria
del usuario. Se solicita investigación para hechos actuales, versiones y estados,
no para saludos ni para consultar ese reloj.

El contexto interno distingue **páginas leídas** de **extractos de búsqueda**; una URL hallada
no acredita haber leído su contenido. Las respuestas no añaden citas ni listas de
fuentes web por defecto; el modelo recibe la instrucción de incluir enlaces o fuentes
solo si el usuario los solicita explícitamente. Las fuentes se conservan como contexto
interno. Se conserva la fecha de consulta y las
fechas declaradas por la página como datos no confiables. Los límites, errores
de herramientas y estados de suficiencia quedan como diagnóstico interno, sin
añadir avisos técnicos automáticos al chat. La respuesta presenta directamente
los hechos respaldados; una laguna no pone en duda toda la respuesta. Si un dato
esencial sigue sin respaldo o tiene un conflicto relevante, se omite o se aclara
solo ese dato de forma natural, sin inventarlo. La investigación termina al cubrir
la pregunta con fuentes adecuadas. Se comprueban
otra vez permisos, cambios de configuración, borrados y fuentes multimedia antes
de publicar; las consultas repetidas no vuelven a ejecutarse.

El planificador entrega un registro compacto de afirmaciones respaldadas,
desconocidas o contradictorias. Solo cuentan como respaldo las citas literales
encontradas en páginas realmente leídas; un extracto del buscador no equivale a
una página leída. Comprobar la procedencia de una cita no garantiza por sí solo
la corrección o actualidad de la conclusión.
Cuando el contexto de trabajo se llena, se consolida ese registro y comienza una
ronda independiente con las citas, URL, fechas y lagunas pendientes validadas;
se descartan el corpus y el replay anterior. Las citas previas solo mantienen su
procedencia mediante la misma pareja URL/cita validada; el resumen no cuenta
como evidencia. Los diagnósticos opcionales se recortan antes que los hechos.

El trabajo temporal se conserva en Markdown dentro del directorio temporal del
sistema, `catsbot-research/<servidor>/<canal>/<usuario>.md`: resumen público,
registro de evidencias, fuentes y referencias a los mensajes de origen; no las
páginas completas ni el historial completo. El archivo tiene un máximo de
64000 bytes, vence a la hora y se conservan hasta 64 archivos, con limpieza al
leer/escribir. Solo se reutiliza en el mismo ámbito tras comprobar configuración,
permisos y mensajes originales. Cambios de ámbito, borrados o ediciones de las
fuentes invalidan el trabajo. Esta nota desechable no es memoria global, ni
sustituye volver a verificar hechos volátiles.

Strata no hereda la cuota predeterminada de Gemini de 10 peticiones por minuto.
Mantiene concurrencia, cola y cooldown. `AI_STRATA_RATE_CAPACITY` y
`AI_STRATA_RATE_PERIOD` permiten imponer una cuota propia; capacidad 0 significa
sin límite RPM adicional. Si el operador define explícitamente
`AI_RATE_CAPACITY`, Strata la respeta salvo un override específico. Gemini
conserva su limitador. Las consultas independientes de permisos se agrupan en
paralelo dentro de cada validación; no se reutilizan permisos antiguos entre
peticiones al proveedor y la publicación de la respuesta.

Los mensajes pasivos del canal IA se capturan con los datos locales de Gateway,
sin consultas REST de permisos; nada se exporta al proveedor en esa captura.
Una respuesta realmente no cacheada puede necesitar una lectura para identificar
al autor del mensaje respondido. Las referencias de Gateway sirven para descubrir
fuentes sin repetir lecturas: todos sus IDs y contenidos se vuelven a verificar
en paralelo antes de cada exportación de contenido al proveedor y antes de publicar. Se conservan
los límites de profundidad, adjuntos y las comprobaciones de cambios de permisos.
La autorización inicial, el descubrimiento de fuentes y los metadatos del modelo
se preparan en paralelo; los permisos no se cachean entre exportaciones o envíos.

Cada trabajo registra solo números: `listen_s` incluye el trabajo previo a encolar;
`first_dispatch_s` mide desde el inicio de `Conversation.listen` hasta invocar el
transporte de la primera generación, incluyendo cola y preparación. `queue_s` conserva la
espera en cola y `end_to_end_s` incluye todo ese recorrido. Si no hubo generación,
`first_dispatch_s` vale -1. Autorización, contexto, web, presupuesto, modelo y envío
mantienen sus tiempos; las fases paralelas pueden solaparse y no deben sumarse
como si fueran una secuencia. El tiempo de modelo incluye conexión y HTTP, no solo
inferencia. El registro no contiene mensajes, claves, consultas web ni URLs.

Los mensajes configurables conservan sus plantillas por defecto. El editor permite
activar **Gestionado por IA** por mensaje (`ai_managed`); los avisos sin editor se
activan por categoría en la configuración de IA (`/api/guilds/{id}/ai-messages`).
Ambas opciones empiezan desactivadas y una plantilla mantiene su propia elección.
La redacción opcional usa el endpoint, modelo y clave de Strata configurados,
con los primeros 4000 caracteres del tono y las reglas completas del servidor
(hasta 12.000 caracteres), independientemente de los interruptores de
conversación y moderación. Conserva menciones, enlaces, datos de embeds y botones;
las sanciones, eliminaciones, timeouts, errores, confirmaciones privadas y citas
de usuarios mantienen su texto. Si falta configuración, la salida no supera la
validación, el proveedor falla o las dos plazas están ocupadas, se envía la
plantilla original; cada generación tiene un máximo de siete segundos, sin cola.

## `📄` Licencia e Información Legal

Este proyecto es de código abierto y está protegido y licenciado bajo la **[GNU General Public License v3.0 (GPL-3.0)](./LICENSE)**.

<details>
<summary><b>Haz clic aquí para leer un resumen de tus derechos y obligaciones</b></summary>

<br>

El bot es software libre. Al usar o modificar este código, aceptas que:

- **✔️ Libertad:** Tienes derecho a usar, modificar y distribuir libremente este software.
- **✔️ Comercialización:** Puedes utilizar el bot y su código para uso privado o comercial.
- **❌ Software privativo:** **No puedes** tomar este código, cerrarlo y distribuirlo como software propietario.
- **⚠️ Copyleft:** Cualquier modificación o trabajo derivado que distribuyas **DEBE** licenciarse bajo la misma **GPL-3.0** y ser de código abierto.
- **⚠️ Atribución:** Debes incluir siempre los avisos de derechos de autor y una copia de la licencia original.

> 📝 **Nota:** Para conocer todos los detalles legales, términos y condiciones, lee el archivo [`LICENSE`](./LICENSE) incluido en este repositorio.

</details>

<br/>

<div align="center">

<br/>

![footer](https://capsule-render.vercel.app/api?type=waving&color=0d001a,7c3aed,ec4899&height=130&section=footer&text=Cat's%20Bot%20©%202025%20|%20GPL-3.0%20Licensed&fontSize=18&fontColor=ffffff&fontAlignY=75)

</div>
