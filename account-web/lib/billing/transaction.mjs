/**
 * @typedef {{rows: Record<string, any>[], rowCount?: number | null}} QueryResult
 * @typedef {{query: (sql: string, values?: any[]) => Promise<QueryResult>, release: (destroy?: boolean) => void}} SqlClient
 * @typedef {{connect: () => Promise<SqlClient>}} SqlPool
 */

/** Every statement, including COMMIT/ROLLBACK, uses the same checked-out connection.
 * @template T
 * @param {SqlPool} pool
 * @param {(client: SqlClient) => Promise<T>} callback
 * @returns {Promise<T>}
 */
export async function transaction(pool, callback) {
  const client = await pool.connect();
  let broken = false;
  try {
    await client.query("BEGIN");
    await client.query("SET LOCAL lock_timeout = '5s'");
    await client.query("SET LOCAL statement_timeout = '15s'");
    await client.query("SET LOCAL idle_in_transaction_session_timeout = '60s'");
    const result = await callback(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    try {
      await client.query("ROLLBACK");
    } catch {
      broken = true;
    }
    throw error;
  } finally {
    client.release(broken);
  }
}
