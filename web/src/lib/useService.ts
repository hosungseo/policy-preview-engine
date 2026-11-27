"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/reviewApi";

const KEY = "pp:service";

/**
 * Whether the asking service answers at this address. Static public hosting has no service, so links into
 * /review/ are shown only where it does. Starts as "yes" (the submission runs with the service) and is corrected
 * after one request; the answer is kept for the tab so later pages do not flicker.
 */
export function useService(): boolean {
  const [on, setOn] = useState(true);
  useEffect(() => {
    try {
      const known = sessionStorage.getItem(KEY);
      if (known) { setOn(known === "1"); return; }
    } catch { /* storage may be blocked */ }
    let live = true;
    api("/api/config")
      .then(() => true)
      .catch((e) => e instanceof ApiError)
      .then((ok) => {
        if (!live) return;
        setOn(ok);
        try { sessionStorage.setItem(KEY, ok ? "1" : "0"); } catch { /* storage may be blocked */ }
      });
    return () => { live = false; };
  }, []);
  return on;
}
