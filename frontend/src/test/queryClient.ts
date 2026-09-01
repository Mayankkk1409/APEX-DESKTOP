import { QueryClient } from "@tanstack/react-query";

/** SSR-friendly query client for vitest — avoids refetch-on-mount wiping seeded cache. */
export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: Number.POSITIVE_INFINITY,
        gcTime: Number.POSITIVE_INFINITY,
      },
    },
  });
}
