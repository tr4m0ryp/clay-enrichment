// Barrel for the queries package. Each domain lives in its own file
// under web/src/lib/queries/ to keep individual modules small. Callers
// can keep doing `import { ... } from "@/lib/queries"`.

export * from "./queries/campaigns";
export * from "./queries/companies";
export * from "./queries/contacts";
export * from "./queries/emails";
export * from "./queries/leads";
export * from "./queries/settings";
