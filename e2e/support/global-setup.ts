import { loadEnv } from "./env";

export default async function globalSetup(): Promise<void> {
  loadEnv();
}
