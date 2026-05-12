import { createContext, useContext, useState, useCallback, useEffect } from "react";

const SaveBarCtx = createContext({
  dirty: false,
  saving: false,
  register: () => {},
  clear: () => {},
});

/**
 * Provider — wrap Dashboard with this.
 * Exposes dirty/saving state + onSave/onRevert to the topbar.
 */
export function SaveBarProvider({ children, renderBar }) {
  const [state, setState] = useState({
    dirty: false,
    saving: false,
    onSave: null,
    onRevert: null,
  });

  const register = useCallback(({ dirty, saving, onSave, onRevert }) => {
    setState({ dirty, saving, onSave, onRevert });
  }, []);

  const clear = useCallback(() => {
    setState({ dirty: false, saving: false, onSave: null, onRevert: null });
  }, []);

  return (
    <SaveBarCtx.Provider value={{ ...state, register, clear }}>
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
