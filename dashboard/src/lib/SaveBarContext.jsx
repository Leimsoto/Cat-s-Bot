import { createContext, useContext, useState, useCallback, useEffect, useId, useMemo, useRef } from "react";
import { retireDrafts, saveBeforeLeaving, summarizeDrafts } from "./navigationGuard";

const SaveBarCtx = createContext({ dirty: false, saving: false, register: () => {}, clear: () => {}, requestNavigation: (action) => action() });

export function SaveBarProvider({ children }) {
  const draftsRef = useRef(new Map());
  const retiredIdsRef = useRef(new Set());
  const statusRef = useRef({ dirty: false, saving: false, canSave: true });
  const pendingAction = useRef(null);
  const allowUnloadRef = useRef(false);
  const dialogRef = useRef(null);
  const [status, setStatus] = useState({ dirty: false, saving: false, canSave: true });
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmSaving, setConfirmSaving] = useState(false);
  const [error, setError] = useState("");

  const updateStatus = useCallback(() => {
    const next = summarizeDrafts(draftsRef.current.values());
    statusRef.current = next;
    setStatus((prev) => prev.dirty === next.dirty && prev.saving === next.saving && prev.canSave === next.canSave ? prev : next);
  }, []);

  const register = useCallback(({ id, dirty, saving, onSave, onRevert }) => {
    if (retiredIdsRef.current.has(id)) return;
    draftsRef.current.set(id, { dirty: Boolean(dirty), saving: Boolean(saving), onSave, onRevert });
    updateStatus();
  }, [updateStatus]);

  const clear = useCallback((id) => {
    draftsRef.current.delete(id);
    retiredIdsRef.current.delete(id);
    allowUnloadRef.current = false;
    updateStatus();
  }, [updateStatus]);

  const onSave = useCallback(async (event) => {
    if (statusRef.current.saving || !statusRef.current.canSave) return;
    const source = event?.type === "click" ? "button" : "navigation";
    const clickCount = event?.detail || 0;
    for (const draft of [...draftsRef.current.values()].filter((entry) => entry.dirty)) await draft.onSave?.({ source, clickCount });
  }, []);
  const onRevert = useCallback(() => {
    for (const draft of [...draftsRef.current.values()].filter((entry) => entry.dirty)) draft.onRevert?.();
  }, []);
  const requestNavigation = useCallback((action) => {
    if (statusRef.current.saving) return;
    if (!statusRef.current.dirty) return action();
    pendingAction.current = action;
    setError("");
    setConfirmOpen(true);
  }, []);

  const cancelNavigation = useCallback(() => {
    pendingAction.current = null;
    setConfirmOpen(false);
    setError("");
  }, []);

  const finishNavigation = () => {
    const action = pendingAction.current;
    pendingAction.current = null;
    setConfirmOpen(false);
    retireDrafts(draftsRef.current, retiredIdsRef.current);
    updateStatus();
    allowUnloadRef.current = true;
    action?.();
  };

  const saveAndLeave = async () => {
    if (confirmSaving || statusRef.current.saving) return;
    setConfirmSaving(true);
    setError("");
    const clean = await saveBeforeLeaving(onSave, () => statusRef.current);
    setConfirmSaving(false);
    if (clean) finishNavigation();
    else setError("No se pudo confirmar el guardado. Tus cambios siguen aquí; revisa el formulario y vuelve a intentarlo.");
  };

  useEffect(() => {
    const dialog = dialogRef.current;
    if (confirmOpen && !dialog.open) dialog.showModal();
    if (!confirmOpen && dialog.open) dialog.close();
  }, [confirmOpen]);

  useEffect(() => {
    const protectDraft = (event) => {
      if (allowUnloadRef.current || (!statusRef.current.dirty && !statusRef.current.saving)) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", protectDraft);
    return () => window.removeEventListener("beforeunload", protectDraft);
  }, []);

  const value = useMemo(() => ({ ...status, onSave, onRevert, register, clear, requestNavigation }), [status, onSave, onRevert, register, clear, requestNavigation]);

  return (
    <SaveBarCtx.Provider value={value}>
      {children}
      <dialog ref={dialogRef} className="draft-dialog" aria-labelledby="draft-title" aria-describedby="draft-description"
        onCancel={(event) => { event.preventDefault(); if (!confirmSaving) cancelNavigation(); }}>
        <div className="draft-dialog-symbol"><i className="fa-solid fa-floppy-disk" aria-hidden="true" /></div>
        <h2 id="draft-title">Tienes cambios pendientes</h2>
        <p id="draft-description">{status.canSave ? "Guárdalos antes de salir para conservar tu configuración." : "Este borrador solo se conserva en esta pantalla. Puedes seguir editándolo o descartarlo antes de salir."}</p>
        {error && <p className="draft-dialog-error" role="alert">{error}</p>}
        <div className="draft-dialog-actions">
          <button className="btn-secondary" autoFocus disabled={confirmSaving} onClick={cancelNavigation}>Seguir editando</button>
          <button className="btn-secondary" disabled={confirmSaving || status.saving} onClick={finishNavigation}>Descartar y salir</button>
          {status.canSave && <button className="btn-primary" disabled={confirmSaving || status.saving} onClick={saveAndLeave}>{confirmSaving ? "Guardando…" : "Guardar y continuar"}</button>}
        </div>
      </dialog>
    </SaveBarCtx.Provider>
  );
}

/** Existing modules keep this save/revert contract. */
export function useSaveBar({ dirty, saving, onSave, onRevert }) {
  const id = useId();
  const { register, clear } = useContext(SaveBarCtx);
  useEffect(() => { register({ id, dirty, saving, onSave, onRevert }); }, [id, dirty, saving, onSave, onRevert, register]);
  useEffect(() => () => clear(id), [id, clear]);
}

export function useSaveBarState() { return useContext(SaveBarCtx); }
