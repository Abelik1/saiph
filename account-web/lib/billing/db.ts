import "server-only";
import { createNeonPool } from "./connection.mjs";
import { createBillingStore } from "./store.mjs";

export type BillingStore = ReturnType<typeof createBillingStore>;

/** Invoke within a Node request only. Missing configuration fails closed at use. */
export async function withBillingStore<T>(
  stripeAccountId: string,
  callback: (store: BillingStore) => Promise<T>,
): Promise<T> {
  const pool = createNeonPool(process.env.DATABASE_URL);
  try {
    return await callback(createBillingStore(pool, { stripeAccountId }));
  } finally {
    await pool.end();
  }
}
