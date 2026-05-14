---
name: Cat's Bot
description: Bot de Discord multifunción con panel web, voz cálida y morado contenido.
colors:
  bg: "#0b0a10"
  surface: "#151821"
  panel: "#18141f"
  panel-hover: "#1f1a2a"
  text: "#f1f5f9"
  text-muted: "#94a3b8"
  text-dim: "#475569"
  border: "rgba(255,255,255,0.06)"
  border-accent: "rgba(168,85,247,0.22)"
  accent: "#a855f7"
  accent-hover: "#c084fc"
  accent-soft: "rgba(168,85,247,0.14)"
  success: "#10b981"
  warning: "#f59e0b"
  danger: "#f43f5e"
  info: "#06b6d4"
typography:
  display:
    fontFamily: "Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "clamp(2.25rem, 5vw, 3.5rem)"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.35
  body:
    fontFamily: "DM Sans, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "DM Sans, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: "0.01em"
rounded:
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  "2xl": "48px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "12px 20px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "24px"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "10px 14px"
---

# Design System: Cat's Bot

## 1. Overview

**Creative North Star: "El Café de Mods"**

Cat's Bot se siente como entrar al café donde los mods se juntan los sábados: superficies oscuras y cálidas con tinte morado tenue, suficiente luz para leer cómodo, sin neon. La marca tiene un único acento morado que aparece donde importa (la acción primaria, el estado activo, un slot de información clave) y nunca como textura de fondo. Todo lo demás es neutro tintado, espaciado generoso y tipografía que no grita.

El sistema rechaza explícitamente lo que un bot de Discord "se supone que parece": layouts MEE6/Dyno con cards repetidos, templates admin Bootstrap, gradientes morado+rosa eléctrico, glassmorphism decorativo, partículas de fondo, hero gigante con stat cards de "10M+ usuarios". También rechaza la otra trampa SaaS: el dashboard que parece Linear sin tener la densidad ni la ambición de Linear.

**Key Characteristics:**
- Dark por defecto, light disponible y auditado.
- Morado como acento ≤10% por pantalla. Nunca como gradiente decorativo.
- Tipografía: pareja DM Sans + Plus Jakarta Sans. Sin display extravagantes.
- Curvas suaves (radius 8–16 px). Sin bordes filo navaja, sin pill obligatoria.
- Sombras discretas, ambient. Sin neon glow alrededor del morado.

## 2. Colors

Paleta dark-first con base casi negra ligeramente tintada hacia el morado, neutros fríos sobre superficie, un único acento morado y cuatro colores semánticos.

### Primary
- **Café Morado** (`#a855f7`): acento único del sistema. Aparece en CTAs primarias, estado activo de navegación, foco visible, indicador de seleccionado. **Nunca como background grande, nunca en gradient.**
- **Café Morado claro** (`#c084fc`): solo hover de la acción primaria.
- **Café Morado tenue** (`rgba(168,85,247,0.14)`): tint para fondos de chips/badges activos. Mantiene legibilidad sin saturar.

### Neutral
- **Noche** (`#0b0a10`): background base. Negro tintado hacia el morado, no `#000`.
- **Mesa** (`#151821`): superficie de cards y contenedores principales.
- **Mantel** (`#18141f`): paneles internos, hover sutil, inputs.
- **Mantel hover** (`#1f1a2a`): estado hover de filas/items.
- **Tinta** (`#f1f5f9`): texto primario.
- **Café con leche** (`#94a3b8`): texto secundario, labels, metadata.
- **Café puro** (`#475569`): texto desactivado, placeholder.
- **Sombra de mantel** (`rgba(255,255,255,0.06)`): bordes y separadores.
- **Sombra de mantel + acento** (`rgba(168,85,247,0.22)`): bordes de elementos activos/seleccionados.

### Semantic
- **Éxito** (`#10b981`): confirmaciones, estados online.
- **Aviso** (`#f59e0b`): warnings, acciones que requieren atención.
- **Peligro** (`#f43f5e`): errores, acciones destructivas.
- **Info** (`#06b6d4`): tips, hints, mensajes informativos.

### Named Rules
**La Regla del Único Acento.** El morado se usa en ≤10% del píxel-area de cualquier pantalla. Si una pantalla tiene tres elementos morados grandes, dos sobran. Si un CTA y un badge ambos son morados, el badge baja a neutro o a `accent-soft`.

**La Regla del Negro Tintado.** Nunca `#000`, nunca `#fff`. Los neutros siempre llevan una pizca del hue de marca (chroma 0.005–0.01 en OKLCH).

**La Regla del Color con Icono.** Color jamás como único portador de información. Éxito = check + verde. Error = ícono + rojo + texto. Estado activo = morado + label.

## 3. Typography

**Display Font:** Plus Jakarta Sans (fallback: system-ui, sans-serif)
**Body Font:** DM Sans (fallback: system-ui, sans-serif)

**Character:** Pareja sans-sans moderna. Plus Jakarta aporta personalidad geométrica con curvas suaves a los titulares; DM Sans (de Indian Type Foundry) da una lectura cómoda y neutra al cuerpo. El conjunto se siente cercano sin ser infantil, técnico sin ser frío. Ambas cargadas como subset latín, `font-display: swap`, autohosted (no Google Fonts CDN).

### Hierarchy
- **Display** (700, `clamp(2.25rem, 5vw, 3.5rem)`, line-height 1.05): solo hero de landing. Máximo una por pantalla.
- **Headline** (700, 1.5rem, line-height 1.2): títulos de sección dentro del panel.
- **Title** (600, 1.125rem, line-height 1.35): títulos de card, headers de tabla.
- **Body** (400, 1rem / 16 px, line-height 1.6): texto base. Límite 65–75 ch por línea de párrafo.
- **Label** (500, 0.8125rem, line-height 1.3, letter-spacing 0.01em): labels de form, metadata. **No uppercase forzado.**

### Named Rules
**La Regla del No-Display-en-Panel.** El estilo Display vive en la landing. Dentro de rutas privadas, el rango superior es Headline. Hero gigantes dentro del panel = anti-patrón.

**La Regla de los 16 px.** El body en mobile nunca baja de 16 px. iOS hace zoom forzado en inputs <16 px; lo evitamos como base, no como excepción.

## 4. Elevation

Sistema híbrido: superficies planas por defecto, con jerarquía dada por **capas tonales** (bg → surface → panel) y sombras solamente para estados elevados temporales (menú abierto, toast, modal). Glassmorphism prohibido como decoración.

### Shadow Vocabulary
- **`shadow-sm`** (`0 1px 2px rgba(0,0,0,0.3)`): hover sutil de cards, borde de input enfocado.
- **`shadow-md`** (`0 4px 12px rgba(0,0,0,0.35), 0 1px 3px rgba(0,0,0,0.2)`): elementos elevados temporalmente (dropdown, popover).
- **`shadow-lg`** (`0 10px 28px rgba(0,0,0,0.45), 0 2px 6px rgba(0,0,0,0.25)`): modal, toast crítico, sheet móvil.
- **`shadow-inset`** (`inset 0 2px 8px rgba(0,0,0,0.4)`): hundimiento sutil de inputs y campos read-only.

### Named Rules
**La Regla de la Sombra con Causa.** Cada sombra tiene una razón física: algo está más cerca del usuario que el resto. Si tres elementos tienen `shadow-md` simultáneos en la misma pantalla, la jerarquía está rota.

**La Regla del No-Glow.** Sombras con tint del acento morado (`shadow-accent`) están reservadas para foco visible cuando el outline solo no alcanza contraste. Nunca para decoración estética.

## 5. Components

### Buttons
- **Shape:** radius 12 px (`rounded-md`). Sin pill obligatoria.
- **Primary:** background `accent` (#a855f7), texto blanco-roto (#f1f5f9), padding `12px 20px`, peso 600. Hover sube a `accent-hover`. Active baja 1 px (`translateY(1px)`).
- **Secondary / Ghost:** transparente, texto `text-muted`, border 1 px `border`. Hover: background `panel-hover`, texto `text`.
- **Danger:** background `danger`, texto blanco. Reservado a acciones destructivas confirmadas.
- **Focus:** outline 2 px `accent` con offset 2 px, **nunca removido.** Disabled: opacidad 0.5 + `cursor: not-allowed`.

### Cards / Containers
- **Corner Style:** radius 16 px (`rounded-lg`).
- **Background:** `surface` (`#151821`).
- **Shadow Strategy:** plano por defecto, sin sombra. Hover opcional con `shadow-sm`.
- **Border:** 1 px `border` (`rgba(255,255,255,0.06)`), **nunca side-stripe.**
- **Internal Padding:** 24 px (`spacing.lg`).
- **Nested cards prohibidos.** Si un card contiene "secciones", se usan separadores (border-top 1 px) o espaciado, no más cards.

### Inputs / Fields
- **Style:** background `panel` (`#18141f`), border 1 px `border`, radius 12 px, padding `10px 14px`, altura mínima 44 px en móvil.
- **Label:** visible siempre, encima del input. Placeholder NO sustituye label.
- **Focus:** border `accent`, sombra `shadow-sm` con tint morado tenue. Transición 150 ms ease-out.
- **Error:** border `danger`, ícono + mensaje debajo del campo (no en toast).
- **Helper text:** debajo del input, `text-muted`, `0.8125rem`.

### Navigation
- **Sidebar (desktop, ≥1024 px):** 256 px de ancho, fijo, `bg` background, items con padding `12px 16px`, ícono + label, activo con tint `accent-soft` + label `accent`.
- **Bottom nav (mobile, <1024 px):** máx 5 items, safe-area-inset-bottom respetado.
- **Topbar:** 64 px de alto, contiene avatar + selector de servidor + acciones globales. Backdrop solid `bg`, **no blur decorativo.**

### Toast / Notifications
- **Style:** card flotante esquina inferior derecha en desktop, sheet inferior en móvil. Auto-dismiss 4 s para éxito/info, manual para error.
- **Color por rol:** background `surface`, accent lateral 3 px del color semántico (excepción permitida a la regla de side-stripe porque marca rol semántico crítico).

### Signature Component — SaveBar
- Barra inferior persistente cuando hay cambios sin guardar. Background `surface` con `shadow-lg` superior. Botones "Descartar" (ghost) + "Guardar cambios" (primary). Siempre visible sobre safe-area-inset-bottom.

## 6. Do's and Don'ts

### Do:
- **Do** usar morado solo en la acción primaria, estado activo, y foco visible. ≤10% del área visible.
- **Do** tintar todos los neutros con un toque del hue morado (chroma 0.005–0.01). Nunca `#000` ni `#fff`.
- **Do** autohostear DM Sans y Plus Jakarta Sans (subset latin, `font-display: swap`). Cero CDN de fuentes.
- **Do** mantener body en 16 px mínimo en móvil para evitar zoom forzado iOS.
- **Do** respetar `prefers-reduced-motion`: animaciones decorativas off, transiciones de estado ≤120 ms.
- **Do** usar safe-area-inset en topbar, sidebar móvil, SaveBar.
- **Do** dar labels visibles a todos los inputs.
- **Do** poner foco visible en todos los interactivos (2 px outline, nunca removido).

### Don't:
- **Don't** usar gradientes morado→rosa (`#7c3aed`→`#ec4899`). Es la firma SaaS-morado que el producto rechaza explícitamente.
- **Don't** usar `background-clip: text` con gradient (gradient text). Banned por shared design laws.
- **Don't** usar glassmorphism / `backdrop-filter: blur` como decoración. El filtro SVG `liquid-glass-filter` debe eliminarse.
- **Don't** usar `border-left` o `border-right` >1 px como side-stripe coloreado en cards o list items. Única excepción: toast por rol semántico (justificada como afordancia crítica de estado).
- **Don't** apilar cards dentro de cards. Si un contenedor necesita subdivisiones, usa separadores o espaciado.
- **Don't** usar emojis como íconos estructurales (UI/navegación). Reservados para mensajes del bot dentro de Discord.
- **Don't** copiar el layout MEE6/Dyno/Carl-bot (sidebar cargado + topbar + grid de stat cards). Es la primera anti-referencia de PRODUCT.md.
- **Don't** usar Font Awesome vía CDN externo. Carga lenta + cache externo + slop. Migrar a SVG inline o set local.
- **Don't** crear un hero de panel con "10M+ servers / 99.9% uptime / 4.8★". Anti-patrón documentado.
- **Don't** poner `aggregateRating` falso en JSON-LD si no hay reviews reales. Riesgo SEO + legal.
- **Don't** usar em-dashes (—) en copy. Comas, dos puntos, paréntesis, punto y aparte.
- **Don't** usar palabras como "todo-en-uno", "potente", "intuitivo", "moderno", "increíble" en copy. Es ruido de marketing IA-slop.
