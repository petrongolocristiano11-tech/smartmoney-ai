export function formatLiveNumber(
  value,
  digits = 6
) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0";
  }

  return number.toLocaleString(
    "it-IT",
    {
      maximumFractionDigits: digits,
    }
  );
}


export function formatLiveDate(value) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);

  if (
    Number.isNaN(date.getTime())
  ) {
    return "-";
  }

  return date.toLocaleString(
    "it-IT"
  );
}


export function shortenLiveAddress(
  value,
  start = 7,
  end = 6
) {
  const text = String(value ?? "");

  if (
    text.length
    <= start + end + 3
  ) {
    return text || "-";
  }

  return `${text.slice(
    0,
    start
  )}...${text.slice(-end)}`;
}


export function parseLiveApiError(error) {
  const detail =
    error?.response?.data?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (
    detail
    && typeof detail === "object"
  ) {
    return (
      detail.message
      ?? detail.code
      ?? "Operazione non riuscita."
    );
  }

  return (
    error?.message
    ?? "Operazione non riuscita."
  );
} 