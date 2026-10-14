"use client";

import { useEffect, useState } from "react";

import { ApiError } from "./api";

export interface ApiState<T> {
  /** The latest response; while a new request is in flight, the previous one (or undefined). */
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
}

interface Settled<T> {
  key: string;
  data?: T;
  error?: ApiError;
}

/**
 * Fetch on mount and whenever `deps` change. State only changes when a response arrives
 * (no setState in the effect body); responses for outdated deps are ignored.
 */
export function useApi<T>(load: () => Promise<T>, deps: readonly unknown[]): ApiState<T> {
  const key = JSON.stringify(deps);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  useEffect(() => {
    let current = true;
    load()
      .then((data) => current && setSettled({ key, data }))
      .catch((error: unknown) => {
        if (current) {
          setSettled({ key, error: error instanceof ApiError ? error : new ApiError(0, "Something went wrong.", "error") });
        }
      });
    return () => {
      current = false;
    };
    // `load` is a new function every render; `key` captures what it depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const fresh = settled?.key === key;
  return { data: settled?.data, error: fresh ? settled?.error : undefined, loading: !fresh };
}
