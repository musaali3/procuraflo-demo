import { useEffect, useRef } from 'react';
import { REFRESH_EVENT } from '../api/client';

export default function useAutoRefresh(refresh, options = {}) {
  const refreshRef = useRef(refresh);
  const optionsRef = useRef(options);
  const timerRef = useRef();

  useEffect(() => {
    refreshRef.current = refresh;
    optionsRef.current = options;
  }, [refresh, options]);

  useEffect(() => {
    function handleDataChanged(event) {
      const { predicate, delay = 150 } = optionsRef.current || {};
      if (predicate && !predicate(event.detail || {})) return;
      window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => {
        Promise.resolve(refreshRef.current?.(event.detail)).catch(() => undefined);
      }, delay);
    }

    window.addEventListener(REFRESH_EVENT, handleDataChanged);
    return () => {
      window.clearTimeout(timerRef.current);
      window.removeEventListener(REFRESH_EVENT, handleDataChanged);
    };
  }, []);
}
