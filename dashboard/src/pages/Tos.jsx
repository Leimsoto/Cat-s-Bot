/**
 * pages/Tos.jsx
 * ─────────────
 * Términos y Condiciones del Servicio. Cumple los requisitos de Discord
 * para bots distribuidos públicamente.
 */

import { Link } from "react-router-dom";

export default function Tos() {
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
        <h1>Condiciones del Servicio</h1>
        <p className="legal-meta">Última actualización: 14 de mayo de 2026</p>

        <section>
          <h2>1. Aceptación</h2>
          <p>
            Al añadir Cat's Bot a un servidor de Discord o al acceder a su panel
            de administración web, aceptas estas Condiciones del Servicio
            ("Condiciones"). Si no estás de acuerdo, no añadas el Bot ni accedas
            al panel.
          </p>
        </section>

        <section>
          <h2>2. Descripción del servicio</h2>
          <p>
            Cat's Bot es un bot de Discord gratuito que ofrece moderación,
            niveles, tickets, sorteos, mensajes programados, auto-respuestas y
            otros módulos configurables por servidor. El servicio se presta
            "tal cual" y puede modificarse, suspenderse o discontinuarse en
            cualquier momento sin previo aviso.
          </p>
        </section>

        <section>
          <h2>3. Uso aceptable</h2>
          <p>Al usar el Bot te comprometes a:</p>
          <ul>
            <li>Cumplir los <a href="https://discord.com/terms" target="_blank" rel="noopener noreferrer">Términos de Servicio de Discord</a> y las Pautas de la Comunidad.</li>
            <li>No usar el Bot para acoso, spam, distribución de malware o cualquier actividad ilegal.</li>
            <li>No intentar comprometer la seguridad del Bot, su infraestructura o sus usuarios.</li>
            <li>No revender el servicio ni cobrarlo como si fuera propio.</li>
            <li>Respetar los derechos de propiedad intelectual.</li>
          </ul>
        </section>

        <section>
          <h2>4. Cuentas y responsabilidad</h2>
          <p>
            La administración del Bot en cada servidor recae en los
            administradores con permisos de "Gestionar servidor" o
            "Administrador". Los moderadores configurados desde el panel actúan
            bajo la responsabilidad del propietario del servidor.
          </p>
        </section>

        <section>
          <h2>5. Contenido del usuario</h2>
          <p>
            Eres el único responsable del contenido que generes a través del
            Bot (mensajes, embeds, plantillas, comandos personalizados).
            Cat's Bot no monitoriza ni endorsa el contenido de los usuarios y
            puede eliminar o desactivar contenido que viole estas Condiciones.
          </p>
        </section>

        <section>
          <h2>6. Disponibilidad</h2>
          <p>
            El servicio se ofrece "tal cual" sin garantías de disponibilidad
            continua. Pueden producirse interrupciones planificadas o
            imprevistas, errores, pérdida de datos o degradaciones del
            rendimiento. No nos hacemos responsables de daños derivados de
            estas circunstancias.
          </p>
        </section>

        <section>
          <h2>7. Limitación de responsabilidad</h2>
          <p>
            En la medida máxima permitida por la ley, Cat's Bot y su mantenedor
            no serán responsables de daños indirectos, incidentales, punitivos
            o consecuenciales derivados del uso o la imposibilidad de uso del
            servicio.
          </p>
        </section>

        <section>
          <h2>8. Suspensión y terminación</h2>
          <p>
            Podemos suspender o terminar el acceso al servicio en cualquier
            momento si detectamos un uso abusivo, una violación de estas
            Condiciones, una solicitud legal válida o por motivos técnicos.
            El propietario del servidor puede expulsar al Bot en cualquier
            momento desde la configuración de Discord.
          </p>
        </section>

        <section>
          <h2>9. Privacidad</h2>
          <p>
            El tratamiento de datos personales se rige por la{" "}
            <Link to="/privacy">Política de Privacidad</Link>, que forma parte
            de estas Condiciones.
          </p>
        </section>

        <section>
          <h2>10. Código fuente y licencia</h2>
          <p>
            El código de Cat's Bot está disponible públicamente en{" "}
            <a href="https://github.com/Leimsoto/Cat-s-Bot" target="_blank" rel="noopener noreferrer">
              github.com/Leimsoto/Cat-s-Bot
            </a>{" "}
            bajo la licencia indicada en el repositorio. El uso del código está
            sujeto a esa licencia; estas Condiciones cubren el uso del servicio
            alojado (el Bot que opera en Discord).
          </p>
        </section>

        <section>
          <h2>11. Modificaciones</h2>
          <p>
            Podemos modificar estas Condiciones en cualquier momento. La fecha
            de la última revisión se publica al inicio del documento. El uso
            continuado del servicio tras los cambios implica la aceptación de
            la versión vigente.
          </p>
        </section>

        <section>
          <h2>12. Ley aplicable</h2>
          <p>
            Estas Condiciones se rigen por la legislación del país de
            residencia del mantenedor del proyecto, sin perjuicio de los
            derechos imperativos que asistan al usuario en su jurisdicción.
          </p>
        </section>

        <section>
          <h2>13. Contacto</h2>
          <p>
            Para preguntas sobre estas Condiciones puedes abrir un issue en el
            repositorio público o contactar al mantenedor por los canales
            indicados en el README.
          </p>
        </section>
      </main>

      <footer className="legal-footer">
        <Link to="/">← Volver a la página principal</Link>
      </footer>
    </div>
  );
}
