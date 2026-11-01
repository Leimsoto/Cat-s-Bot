# Moderación LLM y endpoints

La moderación con modelo es opcional y está desactivada de forma predeterminada. Aquí se resumen su configuración, contexto, acciones y límites de destino por servidor.

[← Volver al README](../readme.md) · [Chat y recuerdos](./chat-y-memorias.md) · [Investigación web](./investigacion-web.md)

## Qué hace y dónde se configura

En **Automoderación → Moderación IA**, el administrador define las reglas del servidor. La conexión se comparte desde **Endpoints**. La moderación tiene un interruptor propio, comienza apagada y reutiliza exenciones de AutoMod; el propietario y los administradores permanecen protegidos.

| Ajuste | Configuración |
| --- | --- |
| Proveedor y modelo | URL compatible con OpenAI, modelo y protocolo Chat Completions (predeterminado) o Responses. |
| Ruta | URL base (`/v1`) o ruta completa `/v1/chat/completions` o `/v1/responses`. |
| Clave | Opcional; se guarda en la base de datos y la API solo informa si existe. |
| Imágenes | Interruptor por conexión; limita qué imágenes actuales se adjuntan a la revisión. |
| Reglas y alcance | Reglas, canal, roles y bots exentos se configuran en AutoMod por servidor. |

## Protocolos y formato de respuesta

Las URL base `/v1` (con o sin barra final) completan la ruta según el protocolo; un dominio sin ruta usa `/v1/chat/completions` o `/v1/responses`. Las rutas personalizadas se conservan literalmente. Una ruta estándar del protocolo contrario es un error de configuración: no se cambia de protocolo automáticamente. Cambiar solo el tipo de API conserva la clave y las confirmaciones de esa URL; cambiar la URL conserva la clave, pero requiere confirmar otra vez los permisos HTTP o privados del nuevo destino.

| Protocolo | Formato enviado | Controles de salida |
| --- | --- | --- |
| Chat Completions | `response_format: {"type":"json_object"}` | `reasoning_effort: "none"`; no se aplica sanción si el proveedor rechaza el formato o devuelve una respuesta inválida. |
| Responses | `text.format: {"type":"json_object"}`, `input`, `max_output_tokens` | No impone temperatura ni esfuerzo dependiente del modelo; usa `store: false`, sin `previous_response_id`. |

Ambos solicitan una decisión JSON breve, sin conversación ni razonamiento, de hasta 512 tokens; una sanción incluye una razón corta y una evidencia. Responses lee elementos `message` de `output`, convierte imágenes a `input_image` y conserva `call_id` de funciones. El bucle público de herramientas mantiene temporalmente la salida y el razonamiento cifrado necesario para continuar; no lo guarda en la memoria del bot. Las respuestas incompletas, fallidas, rechazadas o con herramientas no ofrecidas se descartan. El chat, la moderación y la redacción opcional comparten esta implementación. Consulta la [migración a Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses), [funciones](https://developers.openai.com/api/docs/guides/function-calling) e [imágenes](https://developers.openai.com/api/docs/guides/images-vision).

## Contexto que recibe el modelo

El historial contextual no es objetivo de sanción. Se mantienen orden y fechas; mensajes nuevos y ediciones se revisan mientras el bot está conectado y tiene acceso al canal e historial.

| Límite | Comportamiento |
| --- | --- |
| Historial previo | De 0 a 50 mensajes del mismo canal/hilo; puede ser del mismo usuario o de toda la conversación. |
| Búsqueda por usuario | Examina como máximo los últimos 500 mensajes. |
| Replies | Reutiliza objetivos ya presentes; fuera de la ventana consulta hasta 3 referencias directas únicas, priorizando el reply actual y luego los más recientes. No sigue cadenas. |
| Consulta de referencia | Mismo canal/hilo y servidor, con permisos de lectura; máximo 3 segundos por objetivo. |
| Texto contextual | Hasta 4000 caracteres por mensaje; los recortes se indican. Adjuntos y embeds de las referencias no se leen. |
| Cero mensajes | Conserva solo el ID de relación; no lee ni envía el mensaje respondido. |
| Fuera de alcance | Objetivos borrados, inaccesibles o fuera de límite se indican como desconocidos. |

En modo usuario, el historial anterior sigue siendo suyo, aunque un reply pueda aportar el texto de otra persona como contexto. El modelo debe interpretar citas, bromas y ambigüedad según las reglas, sin inventar intención ni tratar contexto como evidencia. Esto no elimina todos los falsos positivos.

## Decisiones y acciones

| Resultado | Efecto |
| --- | --- |
| Ninguna acción | No aplica una sanción. |
| `delete` | Elimina el mensaje, sin añadir sanción al usuario. |
| `warn` | Registra solo el warn elegido; no caduca ni activa otra sanción por umbrales legacy. |
| `mute` | De 60 segundos a 28 días; requiere un rol de mute configurado y efectivo. |
| `kick` | Sin duración. |
| `ban` | Permanente o temporal, hasta 365 días. |

Se reutilizan casos, jerarquías, permisos, bloqueos y tareas de expiración existentes. Las decisiones sancionadas también eliminan el mensaje mediante el ejecutor de AutoMod. Solo tras confirmar el borrado, el bot avisa en el mismo canal/hilo con una mención breve del motivo y la regla; el caso conserva evidencia y el canal de moderación indica el resultado. Si falla el borrado no anuncia éxito; si falla el aviso, lo registra sin deshacer la sanción ni enviar mensajes privados.

## Imágenes y credenciales

| Entrada | Límite o tratamiento |
| --- | --- |
| Imágenes del mensaje actual | Hasta 4 adjuntos/stickers PNG, JPEG o WebP, 8 MiB combinados, si se activa soporte. |
| Imágenes enlazadas | No se descargan desde enlaces del texto. |
| Otros medios | Audio, vídeo, documentos, embeds y medios no leídos se marcan como cobertura parcial y no aportan evidencia; el texto disponible sigue revisándose. |

El contenido y contexto se envían al endpoint que el administrador eligió. La clave se guarda en la base de datos y la API solo devuelve si está configurada. Omitirla, dejarla vacía o enviar `null` significa **Sin cambios**, incluso al cambiar URL. Una clave nueva la reemplaza; `api_key_clear: true` (acción **Eliminar clave guardada**) es la única forma de borrarla. Si cambia el destino sin reemplazar la clave, esta se enviará al nuevo host: revísalo antes de guardar.

## Confirmaciones HTTP y destinos privados

HTTPS público funciona sin confirmación adicional. El primer **Guardar** de
una URL HTTP muestra un aviso con la URL concreta: el tráfico y la clave viajan
sin cifrar, y el destino puede ser un servicio de la red del bot. El segundo
**Guardar** confirma esa URL para ese servidor, sin editar `.env`. El panel
puede confirmar HTTP y acceso privado en ese mismo segundo clic.

## Validación de red

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

## Alcance de las peticiones permitidas

El acceso privado del panel se limita a la base, `/v1`,
`/v1/chat/completions` o `/v1/responses`, con o sin barra final, y a sus consultas auxiliares
reconocidas de modelos y conteo de tokens. Cada petición utiliza un conector
propio ligado al host y puerto aprobados; las direcciones DNS se revisan también
al conectar. No se permiten redirecciones, proxies de entorno, direcciones de
metadatos/link-local, multicast, reservadas ni sin especificar. El consentimiento
de un servidor no autoriza los destinos de otro ni las descargas de imágenes.
La autorización previa del operador mediante `CATBOT_LLM_ALLOWED_HOSTS` conserva
su comportamiento legado; el flujo del panel no modifica esa lista.

## API y persistencia

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

## Cola, errores y límites

La cola admite 100 trabajos y dos revisiones simultáneas. Cada petición tiene 45 segundos de límite; los trabajos con más de 120 segundos de espera se descartan.

Las revisiones sin acción (`none`), cobertura parcial, cola llena, trabajos obsoletos, respuestas inválidas, errores y acciones no confirmadas quedan en el registro operativo del módulo; no son casos ni entradas del historial de moderación. Ese historial conserva las acciones de AutoMod ejecutadas: `delete`, `warn`, `mute`, `kick` y `ban`.

Un fallo del endpoint, una respuesta sin JSON válido/evidencia del mensaje actual, una edición posterior o un cambio de reglas impide sancionar. No hay revisión retroactiva de mensajes publicados mientras el bot está desconectado ni reintentos de trabajos descartados; el modelo puede equivocarse incluso con una respuesta válida.
