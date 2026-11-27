import { JsonRecord } from "./api";

export function memberEmail(row: JsonRecord): string {
  const nested = row["member"] as JsonRecord | undefined;
  return String(row["email"] ?? nested?.["email"] ?? "");
}

export function memberId(row: JsonRecord): string {
  const nested = row["member"] as JsonRecord | undefined;
  return String(row["member_id"] ?? nested?.["id"] ?? row["id"] ?? "");
}

export function findMemberId(rows: JsonRecord[], email: string): string {
  const row = rows.find((candidate) => memberEmail(candidate).toLowerCase() === email.toLowerCase());
  if (!row) {
    throw new Error(`Workspace member ${email} was not found.`);
  }
  return memberId(row);
}
