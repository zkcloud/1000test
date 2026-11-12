let csrf = "";
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...(method !== "GET" ? { "X-CSRF-Token": csrf } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("网络连接中断，请检查网络后重试。", 0);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(
      typeof payload.detail === "string"
        ? payload.detail
        : `请求失败（${response.status}）`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}
export async function identify() {
  csrf = (await api<{ csrf: string }>("/visitor")).csrf;
}
