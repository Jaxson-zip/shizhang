/** A late read is harmless; its result must not resume a timed-out write preparation. */
export async function readWithin<T>(read: () => Promise<T>, timeoutMs = 15_000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([read(), new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error('PREPARATION_TIMEOUT')), timeoutMs)
    })])
  } finally { if (timer !== undefined) clearTimeout(timer) }
}
