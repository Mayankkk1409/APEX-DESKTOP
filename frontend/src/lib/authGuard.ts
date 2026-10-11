/** True when the desk may render. A missing memory token waits for the refresh cookie. */
export async function resolveAuthGuard(opts: {
  token: string | null;
  restore: () => Promise<boolean>;
}): Promise<boolean> {
  if (opts.token) return true;
  return opts.restore();
}
