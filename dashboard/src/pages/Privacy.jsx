/**
 * pages/Privacy.jsx
 * ─────────────────
 * Política de Privacidad. Diseño sobrio, texto extenso.
 * Cumple los estándares mínimos de Discord (Terms of Service requeridos
 * para bots distribuidos) y RGPD para usuarios europeos.
 */

import { Link } from "react-router-dom";

export default function Privacy() {
  return (
    <div className="legal-page">
      <header className="legal-nav">
        <Link to="/" className="legal-back">← Cat's Bot</Link>
        <nav>
          <Link to="/privacy">Privacidad</Link>
          <Link to="/tos">Condiciones</Link>
        </nav>
      </header>

      <main className="legal-content">
        <h1>Política de Privacidad</h1>
        <p className="legal-meta">Última actualización: 14 de mayo de 2026</p>

        <section>
          <h2>1. Identidad del responsable</h2>
          <p>
            Esta política regula el tratamiento de datos personales por parte del
            bot de Discord "Cat's Bot" (en adelante, "el Bot") y su panel de
            administración web. El código fuente es público en{" "}
            <a href="https://github.com/Leimsoto/Cat-s-Bot" target="_blank" rel="noopener noreferrer">
              github.com/Leimsoto/Cat-s-Bot
            </a>.
          </p>
        </section>

        <section>
          <h2>2. Datos que recopilamos</h2>
          <p>
            El Bot recopila únicamente la información mínima necesaria para
            funcionar:
          </p>
          <ul>
            <li>
              <strong>Identificadores de Discord:</strong> ID numérico del
              servidor, ID de canales, ID de usuarios que interactúan con el Bot.
            </li>
            <li>
              <strong>Mensajes y contenido:</strong> mensajes recibidos por el
              Bot únicamente cuando son necesarios para activar reglas de
              automoderación, auto-respuestas, comandos personalizados, niveles
              o cualquier funcionalidad activada por el administrador del
              servidor. No se conservan mensajes completos salvo lo estrictamente
              necesario para fines de auditoría (modlog) o niveles (acumulación
              de XP).
            </li>
            <li>
              <strong>Configuración del servidor:</strong> ajustes guardados
              voluntariamente por los administradores desde el panel.
            </li>
            <li>
              <strong>Autenticación OAuth2:</strong> al iniciar sesión en el
              panel, Discord nos envía tu identificador, nombre de usuario,
              avatar y la lista de servidores donde tienes permisos de
              administrador.
            </li>
          </ul>
        </section>

        <section>
          <h2>3. Finalidad del tratamiento</h2>
          <ul>
            <li>Prestar las funcionalidades configuradas por el administrador del servidor.</li>
            <li>Permitir el acceso al panel web mediante OAuth2 de Discord.</li>
            <li>Auditoría y prevención de abusos (registros de moderación).</li>
            <li>Estadísticas agregadas anónimas para mejorar el servicio.</li>
          </ul>
        </section>

        <section>
          <h2>4. Base legal</h2>
          <p>
            Tratamos los datos amparados en:
          </p>
          <ul>
            <li>
              El consentimiento del usuario al añadir el Bot al servidor y al
              iniciar sesión con Discord.
            </li>
            <li>
              El interés legítimo del administrador del servidor en moderar y
              gestionar su comunidad.
            </li>
          </ul>
        </section>

        <section>
          <h2>5. Conservación de datos</h2>
          <p>
            Conservamos los datos mientras el Bot permanezca en el servidor.
            Cuando el Bot es expulsado del servidor, eliminamos en un plazo
            razonable la configuración asociada. Los datos personales de
            usuarios concretos pueden eliminarse a petición del titular
            escribiendo al canal de soporte del servidor o al mantenedor del
            proyecto.
          </p>
        </section>

        <section>
          <h2>6. Derechos del usuario (RGPD)</h2>
          <p>
            Si te encuentras en el Espacio Económico Europeo, tienes derecho a:
          </p>
          <ul>
            <li>Acceder a tus datos personales.</li>
            <li>Rectificar datos inexactos.</li>
            <li>Solicitar la supresión.</li>
            <li>Oponerte al tratamiento.</li>
            <li>Portabilidad de tus datos en formato legible.</li>
            <li>Presentar una reclamación ante la autoridad de protección de datos.</li>
          </ul>
        </section>

        <section>
          <h2>7. Terceros</h2>
          <p>
            El Bot interactúa con la API oficial de Discord. Los datos transitan
            por sus servidores conforme a sus propias políticas de privacidad.
            No vendemos ni cedemos datos a anunciantes ni a terceros con fines
            comerciales.
          </p>
        </section>

        <section>
          <h2>8. Seguridad</h2>
          <p>
            Aplicamos medidas razonables para proteger la información:
            credenciales en variables de entorno, autenticación OAuth2 oficial,
            comunicaciones cifradas TLS, y permisos granulares por servidor.
            Ningún sistema es absolutamente seguro, por lo que recomendamos no
            compartir información sensible a través del Bot.
          </p>
        </section>

        <section>
          <h2>9. Cambios en esta política</h2>
          <p>
            Podemos actualizar esta política de privacidad en cualquier momento.
            La fecha de la última revisión se publica al inicio del documento.
            Recomendamos revisarla periódicamente.
          </p>
        </section>

        <section>
          <h2>10. Contacto</h2>
          <p>
            Para cualquier consulta sobre privacidad, puedes abrir un issue en
            el repositorio público o contactar al mantenedor a través de los
            canales indicados en el README del proyecto.
          </p>
        </section>
      </main>

      <footer className="legal-footer">
        <Link to="/">← Volver a la página principal</Link>
      </footer>
    </div>
  );
}
