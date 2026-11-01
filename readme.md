<div align="center">

# Cat's Bot

<img src="./dashboard/public/logo.png" alt="Logo de Cat's Bot" width="150" />

![Cat's Bot: moderación, IA, radio y utilidades](https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=700&size=18&pause=1200&color=A855F7&center=true&vCenter=true&width=620&height=42&lines=Bot+para+Discord;Moderaci%C3%B3n+%E2%80%A2+IA+%E2%80%A2+Radio+%E2%80%A2+Utilidades;Las+Tortuguitas+de+Ezku)

[![Discord](https://img.shields.io/badge/Comunidad-Discord-5865F2?logo=discord&logoColor=white)](https://discord.com/invite/las-tortuguitas-de-ezku-1214414622111567892)
![Licencia GPL-3.0](https://img.shields.io/badge/Licencia-GPL--3.0-blue.svg)
![Python](https://img.shields.io/badge/Bot-Python-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/Panel-React-149ECA?logo=react&logoColor=white)

</div>

Cat's Bot reúne herramientas de moderación, conversación con IA, radio y gestión del servidor en un bot de Discord con panel web.

## Funciones

| Área | Qué incluye |
| --- | --- |
| 🛡️ Moderación | AutoMod, casos y configuración por servidor; moderación LLM opcional. |
| 💬 IA | Chat Strata con recuerdos por ámbito y recuerdos personales opcionales; Gemini se conserva como alternativa. |
| 🌐 Investigación | Búsqueda pública con DuckDuckGo/Brave y lectura mediante Chrome Headless. |
| 🎵 Radio | Reproducción de audio en canales de voz. |
| ⚙️ Panel | Configuración del bot y administración de funciones desde el navegador. |

## Arquitectura

| Componente | Tecnología | Responsabilidad |
| --- | --- | --- |
| Bot | Python, `discord.py` | Comandos, eventos y funciones de Discord. |
| API | FastAPI, Uvicorn | API REST y autenticación del panel. |
| Dashboard | React, Vite | Interfaz web de configuración. |
| Datos | SQLite | Configuración, casos y estado persistente del bot. |
| IA | Endpoint compatible con OpenAI; Gemini | Chat y moderación asistida según proveedor configurado. |
| Web opcional | DuckDuckGo, Playwright y Chrome Headless | Búsqueda pública y lectura de páginas. |

## Configuración y despliegue

1. Revisa [`.env.example`](./.env.example) para conocer las variables de entorno.
2. Para una instalación en WSL, sigue la [guía de despliegue](./deploy/wsl/README.md).
3. Para habilitar lectura web con Chrome, consulta la [guía del navegador](./deploy/wsl/WEB_BROWSER.md).

## IA y guías

| Función | Dónde se configura | Guía |
| --- | --- | --- |
| Moderación LLM | AutoMod y Endpoints; reglas y conexión por servidor. | [Protocolos, contexto y acciones](./docs/moderacion-ia.md) |
| Chat y recuerdos | IA y Endpoints; roles de acceso/restringidos y ámbitos de memoria. | [Respuestas, permisos y memoria](./docs/chat-y-memorias.md) |
| Investigación web | Internet, fuentes estándar (1–20; 3 por defecto), permiso Deep Think y cupo diario (3 por defecto). | [Flujo, evidencia y límites](./docs/investigacion-web.md) |

## Comunidad y contribuidores

Cat's Bot se desarrolla para la comunidad Las Tortuguitas de Ezku.

<div align="center">

**Leimsoto** &nbsp; · &nbsp; **DarkAnubis0100** &nbsp; · &nbsp; **Codex**

</div>

## Licencia

[GNU General Public License v3.0](./LICENSE)

<div align="center">

![Cat's Bot](https://capsule-render.vercel.app/api?type=waving&color=0d001a,7c3aed,ec4899&height=90&section=footer)

</div>
