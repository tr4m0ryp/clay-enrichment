import postgres from "postgres";

const connectionString = process.env.DATABASE_URL!;

export const sql = postgres(connectionString, {
  max: 5,
  idle_timeout: 20,
  connect_timeout: 10,
});
