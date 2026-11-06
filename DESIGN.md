---
name: Cat's Bot dashboard
colors:
  bg: "#141119"
  sidebar: "#100d15"
  surface: "#211b29"
  text: "#f4eefa"
  text-muted: "#b9aac8"
  border: "#3a2d47"
  accent: "#c69aef"
---

# Cat's Bot: panel de comunidad

La dirección aprobada es un centro de control expresivo y cálido: grafito con matiz violeta, lila legible, información abundante y el gato original como protagonista. La referencia visual es `catsbot-redesign.html` aprobada el 28 de octubre de 2026. El panel usa información y acciones reales; los valores ilustrativos de la composición no se trasladan al producto.

## Marca y composición

Conservar intactos `dashboard/public/logo.png` y `dashboard/src/assets/logo.svg`. DM Sans sirve controles y contenido; Plus Jakarta Sans da jerarquía a títulos. El Resumen combina una banda de marca, métricas reales, actividad y accesos a configuración. AutoMod, Mensajes y Tickets alternan configuración con contexto o preview de Discord. No convertir todas las secciones en tarjetas idénticas ni añadir estados de conexión sin evidencia del backend.

La sidebar agrupa los veinte destinos originales y permite desplegar sus grupos. El servidor y la cuenta permanecen identificables. La topbar compacta muestra el módulo, los cambios pendientes y acciones de guardado. Un único módulo se monta a la vez.

## Sistema compartido

`dashboard/src/dashboard.css` define tokens y controles del panel; `components/DashboardPanels.css` define las composiciones de las cuatro vistas principales. Los módulos nuevos deben usar `--bg`, `--surface`, `--panel`, `--text`, `--text-muted`, `--border`, `--accent` y colores semánticos. Inputs en superficie hundida, focus visible de 2px, radios 8px en controles y 12–16px en contenedores. Estados siempre identificados también con texto o icono.

Tema oscuro predeterminado y claro mediante tokens en `documentElement[data-dashboard-theme]`, presente solo durante el panel y heredable por portales. El tema claro usa fondo `#f7f5fa`, tinta `#30243d` y acento `#7540a8`. El selector de tema conserva la preferencia local. Las previews de Discord conservan su propia gramática visual y el borde lateral que representa el embed.

## Interacción y móvil

A 320 y 390px los grids se apilan; el formulario nunca exige desplazamiento horizontal. Controles táctiles de al menos 44px e inputs de 16px. La sidebar móvil tiene scrim, Escape y foco protegido; el guardado pendiente queda accesible abajo. Los selectores permiten buscar, navegar con flechas y Enter, cerrar con Escape y recuperar el foco.

Salir del módulo, cambiar servidor, abrir el selector, recargar o cerrar sesión con un borrador exige guardar, descartar o cancelar. Un retorno `undefined` del guardado no prueba éxito: el módulo debe registrar `dirty=false` y `saving=false` antes de navegar. Guardados fallidos conservan la edición y la ubicación. El cierre de pestaña usa la confirmación nativa del navegador.

## Movimiento y coste

Superficies sólidas, sin orbes animados, blurs de pantalla completa ni filtros de fondo. Transiciones breves de estado y drawer; respetar reduced-motion. No mantener veinte paneles montados, no pedir datos de pestañas que aún no se consultan y reutilizar la caché/deduplicación HTTP existente. Los mensajes de error deben ofrecer una recuperación real.
