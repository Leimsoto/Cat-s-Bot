import { useEffect, useState } from 'react';
import { apiGet, apiPost, apiDelete } from '../lib/api';

export default function Autoroles({ selectedGuild }) {
  const [roles, setRoles] = useState([]);
  const [availableRoles, setAvailableRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newRole, setNewRole] = useState('');
  const [adding, setAdding] = useState(false);

  const load = () => {
    if (!selectedGuild) return;
    setLoading(true);
    Promise.all([
      apiGet(`/api/guilds/${selectedGuild}/autoroles`),
      apiGet(`/api/guilds/${selectedGuild}/roles`).catch(() => ({ roles: [] })),
    ])
      .then(([arData, rolesData]) => {
        setRoles(arData?.autoroles || []);
        setAvailableRoles(rolesData.roles || []);
      })
      .catch(() => { setRoles([]); setAvailableRoles([]); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [selectedGuild]);

  const addRole = async () => {
    if (!newRole) return;
    setAdding(true);
    try {
      await apiPost(`/api/guilds/${selectedGuild}/autoroles`, { role_id: newRole });
      setNewRole('');
      load();
    } catch (e) {
      console.error('Error adding autorole:', e);
    } finally { setAdding(false); }
  };

  const removeRole = async (roleId) => {
    await apiDelete(`/api/guilds/${selectedGuild}/autoroles/${roleId}`);
    load();
  };

  if (loading) return <div className="loader">Cargando autoroles...</div>;

  return (
    <div className="automod-container animate-fade-in">
      <div className="automod-header">
        <div className="header-info">
          <h2 className="glow-text">Autoroles</h2>
          <p className="subtitle">Roles que se asignan automáticamente cuando un usuario se une al servidor.</p>
          <div className="runtime-note"><i className="fa-solid fa-circle-check" /> {roles.length} autoroles configurados</div>
        </div>
      </div>

      <div className="automod-grid">
        <div className="glass-panel mod-section full-width">
          <div className="section-title"><i className="fa-solid fa-plus" /><h3>Agregar Autorole</h3></div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <select value={newRole} onChange={e => setNewRole(e.target.value)} style={{ flex: 1 }}>
              <option value="">— Seleccionar rol —</option>
              {availableRoles
                .filter(r => !roles.some(ar => String(ar.role_id || ar) === String(r.id)))
                .map(r => <option key={r.id} value={r.id}>@{r.name}</option>)
              }
            </select>
            <button className="btn-save" onClick={addRole} disabled={adding || !newRole}>
              {adding ? 'Agregando...' : <><i className="fa-solid fa-plus" /> Agregar</>}
            </button>
          </div>
        </div>

        <div className="glass-panel mod-section full-width">
          <div className="section-title"><i className="fa-solid fa-list" /><h3>Roles Configurados</h3></div>
          {roles.length === 0 ? (
            <div className="empty-mini"><i className="fa-solid fa-user-plus" /><span>No hay autoroles configurados aún.</span></div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {roles.map(r => (
                <div key={r.role_id || r} className="action-row" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div className="ov-activity-badge" style={{ background: 'rgba(88,101,242,0.15)', color: '#5865f2', flexShrink: 0 }}>
                    <i className="fa-solid fa-shield-halved" />
                  </div>
                  <div style={{ flex: 1 }}>
                      {
                        (() => {
                          const roleName = availableRoles.find(r2 => String(r2.id) === String(r.role_id || r))?.name;
                          return <strong>@{roleName || (r.role_id || r)}</strong>;
                        })()
                      }
                      {r.created_at && <p className="ov-subtitle" style={{ margin: 0, fontSize: '0.78rem' }}>Agregado: {new Date(r.created_at).toLocaleDateString('es')}</p>}
                    </div>
                  <button onClick={() => removeRole(r.role_id || r)}
                    style={{ background: 'rgba(239,68,68,0.12)', border: 'none', color: '#ef4444', borderRadius: '8px', padding: '6px 12px', cursor: 'pointer', fontWeight: 600, fontSize: '0.8rem' }}>
                    <i className="fa-solid fa-trash" /> Eliminar
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
