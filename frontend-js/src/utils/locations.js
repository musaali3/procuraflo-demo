export const FINAL_STORAGE_TYPES = new Set(["Bin", "Bay", "Yard Slot", "Ground Stack", "Open Area", "Staging", "Rack", "Zone"]);

export function isUsableStorageLocation(location) {
  if (!location || !FINAL_STORAGE_TYPES.has(String(location.type || ""))) return false;
  if (Number(location.active_yn ?? 1) === 0) return false;
  return !["Inactive", "Blocked", "Maintenance", "Full"].includes(String(location.status || ""));
}

export function locationLabel(location) {
  if (!location) return "Unknown location";
  return `${location.code || "Uncoded location"}${location.label ? ` — ${location.label}` : ""} (${location.type || "Storage"})`;
}
