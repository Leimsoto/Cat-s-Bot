import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";

const SaveBarCtx = createContext({
  dirty: false,
  saving: false,
  register: () => {},
  clear: () => {}});

/**
 * Provider — wrap Dashboard with this.
 * Exposes dirty/saving state + onSave/onRevert to the topbar.
 */
export function SaveBarProvider({ children }) {
  const handlersRef = useRef({ onSave: null, onRevert: null });
  const [status, setStatus] = useState({ dirty: false, saving: false });

  const register = useCallback(({ dirty, saving, onSave, onRevert }) => {
    handlersRef.current = { onSave, onRevert };
    setStatus((prev) => {
      const next = { dirty: Boolean(dirty), saving: Boolean(saving) };
      return prev.dirty === next.dirty && prev.saving === next.saving
        ? prev
        : next;
    });
  }, []);

  const clear = useCallback(() => {
    handlersRef.current = { onSave: null, onRevert: null };
    setStatus((prev) =>
      prev.dirty || prev.saving ? { dirty: false, saving: false } : prev,
    );
  }, []);

  const onSave = useCallback(() => handlersRef.current.onSave?.(), []);
  const onRevert = useCallback(() => handlersRef.current.onRevert?.(), []);

  const value = useMemo(
    () => ({ ...status, onSave, onRevert, register, clear }),
    [status, onSave, onRevert, register, clear],
  );

  return (
    <SaveBarCtx.Provider value={value}>
      {children}
    </SaveBarCtx.Provider>
  );
}

/**
 * Hook — call from any module to register its save/revert state.
 *
 * Usage:
 *   useSaveBar({ dirty, saving, onSave: save, onRevert: load });
 */
export function useSaveBar({ dirty, saving, onSave, onRevert }) {
  const { register, clear } = useContext(SaveBarCtx);

  useEffect(() => {
    register({ dirty, saving, onSave, onRevert });
  }, [dirty, saving, onSave, onRevert, register]);

  // Clear when component unmounts (page change)
  useEffect(() => clear, [clear]);
}

/**
 * Hook — read the save bar state from the topbar.
 */
export function useSaveBarState() {
  return useContext(SaveBarCtx);
}
