# Evidencia privada de moderación

Los nuevos `/warn`, `/mute`, `/kick` y `/ban` conservan contexto antes de la sanción. Opciones: `mensaje_url` (enlace a un mensaje del mismo servidor) y `archivo` (adjunto multimedia). `evidencia_url` conserva compatibilidad: un enlace a un mensaje de Discord también sirve como origen; otras URLs quedan como referencia, sin descargarlas. Sin origen explícito, se usa el contexto acotado del canal actual. Un origen inválido no se reemplaza silenciosamente por otro canal.

AutoMod normal y de IA capturan antes de borrar el mensaje cuando la acción tiene caso: warn, mute, kick o ban; DELETE de IA conserva su caso existente. DELETE normal sin caso no genera capturas. El registro incluye hasta cinco mensajes reales (cuatro anteriores y el mensaje origen), texto, autores/IDs, fechas, canal, lista de adjuntos y fecha de captura. El canal actual sin mensaje origen aporta los últimos cuatro mensajes. `context.json` conserva esos datos y `context.png` es una representación offline escapada, rotulada **Registro del bot**: no inicia sesión en Discord, no genera imágenes con IA ni simula una captura de su interfaz. Los archivos multimedia originales se guardan aparte; el PNG muestra sus nombres. Los mensajes/adjuntos no disponibles se identifican mediante estados de fallo; nunca se inventa su contenido.

Se verifican permisos actuales de lectura e historial del bot y del moderador en el canal origen; los hilos privados requieren pertenencia o permiso de gestión. La captura vuelve a comprobar el acceso antes de devolver los bytes, también ante capturas parciales. La sanción revalida su autorización después de capturar. El presupuesto de captura es de 10 segundos, hasta 3 segundos para la comprobación final y hasta 5 segundos para el adjunto opcional aportado por el moderador. Un fallo de evidencia no convierte una sanción válida en un éxito falso ni elimina su registro.

## Añadir después

`/case evidence case_id:<número> archivo:<adjunto> mensaje_url:<enlace opcional>` agrega evidencia sin sobrescribir la original ni cambiar el estado de la sanción. Usa los permisos correspondientes a la acción del caso y responde de forma privada. Sin enlace explícito también puede guardar contexto del canal actual.

El dashboard permite añadir archivos después en casos activos o históricos. Sólo el dueño o un Administrador real puede consultar/listar/descargar/subir evidencia por API. Se conserva el bypass master de la política existente. **Gestionar servidor** por sí solo no concede acceso a archivos ni metadatos privados. Los comandos slash de aportación siguen usando la autorización de moderación y del canal origen.

## Formatos, límites y conservación

- Imágenes PNG, JPEG, GIF, WebP; audio MP3, WAV, Ogg, FLAC; contenedores MP4 y WebM. Se comprueban firmas mínimas del contenedor, no sólo extensión o MIME suministrado; no se garantiza que un archivo multimedia sea reproducible ni se analiza malware.
- SVG, HTML y formatos desconocidos se rechazan. El contenido siempre se descarga como adjunto con `nosniff`, CSP restrictiva y caché privada desactivada.
- Máximo 8 MiB por archivo; 24 MiB entre JSON, PNG y multimedia de una captura; hasta seis adjuntos multimedia, contando el adjunto opcional. Si hay demasiados, se priorizan los del mensaje origen y se registra la omisión.
- El panel selecciona hasta seis archivos/24 MiB y envía un archivo binario por petición. Cada petición tiene un límite servidor de 8 MiB; el caso admite 64 MiB propios y 128 registros, comprobados en una transacción SQLite. Los registros heredados del caso padre no duplican bytes ni consumen cuota propia del hijo.
- Los adjuntos originales se leen sólo del CDN de Discord por HTTPS, sin redirects y con descarga acotada. No existe un endpoint que descargue URLs arbitrarias. Un enlace ya caducado o un archivo excesivo queda como fallo explícito de captura; una subida inválida devuelve 400/413 sin crear archivos ficticios.

Los bytes están en la tabla SQLite `case_evidence`, junto con SHA-256, procedencia, uploader, mensaje/canal origen, fecha, estado y motivo de fallo. Son apéndices inmutables. Las consecuencias automáticas de warns heredan la evidencia del caso padre de forma explícita, sin copiar BLOB. Los backups completos existentes de SQLite incluyen tanto metadatos como archivos reales; no hace falta respaldar otra carpeta. Restaurar sólo un export de configuración no equivale a un backup completo de SQLite. No se elimina evidencia automáticamente en esta versión; vigila crecimiento y conserva backups según la política del servidor.

## API

Todas las rutas requieren autorización actual por servidor y caso:

- `GET /api/moderation/{guild_id}/cases/{case_ref}/evidence`: `{items, limits, evidence_count, evidence_status, evidence_errors}`.
- `POST` misma ruta: cuerpo binario de un archivo; `X-Filename: encodeURIComponent(nombre)` y `Content-Type` multimedia u `application/octet-stream`. Devuelve el listado actualizado. El servidor consume el stream hasta 8 MiB y revalida autorización antes de persistir.
- `GET .../evidence/{evidence_id}`: bytes autenticados; IDs de otros casos/servidores devuelven 404. La ruta también permite descargar evidencia heredada verificada.

Cada item contiene `id`, `case_id` propietario, `kind` (`context`, `snapshot`, `attachment`), `status` (`available`, `failed`), `filename`, `content_type`, `size`, `sha256`, `source`, `source_message_id`, `source_channel_id`, `uploader_id`, `created_at`, `error`, `inherited` y `download_url` (sólo si está disponible). `limits` contiene `max_file_bytes`, `max_upload_bytes`, `max_files` y `max_case_bytes`. Los listados de casos incluyen `evidence_count`, `evidence_status` (`none`, `available`, `partial`, `failed`) y `evidence_errors`. No se publican URLs de archivos ni capturas en logs de Discord o DM.

## Validación local

`python -B -m unittest tests.test_moderation_evidence -q` usa SQLite en memoria y mocks de Discord/CDN. Incluye conservación real de bytes en backup, herencia, inmutabilidad, cuotas concurrentes, límites, aislamiento entre casos/servidores, permisos actuales y captura antes del borrado/sanción. El renderer necesita Google Chrome y Playwright ya instalados; `CATBOT_CHROME_EXECUTABLE` reutiliza la ruta opcional existente. Si Chrome falla, JSON/adjuntos disponibles se conservan y el PNG queda marcado como no disponible.
