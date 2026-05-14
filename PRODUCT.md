# Product

## Register

brand

> Nota: el proyecto tiene split 50/50 entre landing pública (brand) y panel admin privado (product). Por convención impeccable, PRODUCT.md carga un valor por defecto; el panel admin se trata como `product` cuando se invoca `/impeccable <comando>` sobre rutas privadas (`/dashboard/*`, `/settings/*`). El registro brand aplica a la home, marketing y SEO.

## Users

Owner casual de un servidor de Discord, hispanohablante, edad 16–40, conecta desde móvil tan seguido como desde desktop. No es desarrollador. Quiere configurar moderación, niveles, tickets, música y bienvenidas sin leer documentación. Espera resultados visibles en menos de 5 minutos tras invitar al bot. Secundariamente: mods técnicos que ya conocen Discord a fondo y quieren control granular y atajos.

Objetivo del producto: bajar la curva de configuración de un bot multifunción al nivel "instalo y entiendo qué pasa". Cada pantalla debe responder "¿qué hace esto en mi servidor ahora mismo?".

## Product Purpose

Cat's Bot es un bot multifunción de Discord con panel web propio. La razón de existir no es "tener todas las features", es: dar a comunidades hispanas un control completo y comprensible de su servidor sin tener que aprender 14 comandos slash ni leer wikis. El éxito es medible: un owner sin experiencia entra al panel, activa moderación + bienvenidas + niveles, y entiende qué hizo, todo en una sesión.

## Brand Personality

Juguetón, cálido, cercano. En tres palabras: **amigable, claro, capaz**. Voz: tutea al usuario (tú, no usted), explica antes de pedir, celebra acciones pequeñas sin caer en confetti. Tono escrito: frases cortas, sin jerga técnica innecesaria, sin emojis decorativos en UI (sí en mensajes del bot dentro de Discord). El producto se siente como hablar con alguien que conoce Discord y te lo está explicando, no como una herramienta empresarial.

## Anti-references

NO debe parecerse a:

- **MEE6, Dyno, Carl-bot**: layout SaaS estándar con sidebar cargado, cards repetidos, gráficos de barras infantiles, "premium gating" agresivo, copy en inglés traducido a medias.
- **Templates admin Soft UI / Material / Bootstrap**: sidebar fijo + topbar + cards idénticos en grid, look "AdminLTE 2018".
- **Estética gamer / anime / neon**: emojis decorativos en headers, fuentes display gaming, neon glow, sparkles, gradientes morado+rosa eléctrico, partículas de fondo.
- **Landing SaaS genérica morado+rosa**: hero gigante con stat cards ("10M+ servers", "99.9% uptime"), glassmorphism decorativo, gradientes de marca aplicados como textura, screenshots flotantes con tilt.

Si alguien dice "esto se ve como un bot de Discord cualquiera" hemos fallado.

## Design Principles

1. **Mostrar el efecto antes que la opción.** Cada toggle / setting debe decir qué pasa en el servidor cuando lo activas, no solo el nombre técnico. Empty states explican el resultado, no la feature.
2. **Configurable pero amigable.** Defaults razonables siempre presentes; lo avanzado existe pero detrás de un disclosure ("Configuración avanzada"). Owner casual no choca con opciones que no entiende; mod técnico llega a ellas en un click.
3. **Hablamos como amigos, no como soporte corporativo.** Sin "Estimado usuario", sin "Por favor proceda". Tú, frases cortas, errores explican qué pasó y qué hacer.
4. **Marca con carácter, sin caer en el reflejo SaaS-morado.** El morado del proyecto se usa con intención, no como textura. Color principal acotado, neutros tintados, accentos por rol semántico (éxito / error / peligro), nunca como decoración.
5. **El panel sirve al servidor, no a la marca.** En rutas privadas el dato manda: legibilidad, densidad cómoda, jerarquía clara. Ornamentos de marca quedan reservados para landing y onboarding.

## Accessibility & Inclusion

- **WCAG 2.1 AA** como mínimo en todo el producto.
- Contraste de texto principal ≥ 4.5:1, texto grande ≥ 3:1, en ambos temas.
- Soporte completo `prefers-reduced-motion`: animaciones decorativas se desactivan; transiciones de estado quedan en ≤120ms con `ease-out`.
- Dark mode default + light mode disponible; ambos auditados independientemente (no asumir que los tokens light derivan automáticamente del dark).
- Tap targets ≥ 44×44 px en móvil; safe-area-insets respetadas (iOS notch / Android gesture bar).
- Foco visible en todos los elementos interactivos (outline 2 px con offset, sin removerlo).
- Labels visibles en todos los inputs (no solo placeholder).
- Color nunca como único portador de información: errores con icono + texto, estados con label además de color.
- Soporte Dynamic Type / zoom del navegador hasta 200% sin romper layout.
