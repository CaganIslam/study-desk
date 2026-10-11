// JSON API helpers. Errors come back as {error: {code, message}} (ARCHITECTURE: API).
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = data.error ?? {};
    throw new ApiError(response.status, error.code ?? "generic", error.message ?? response.statusText);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  put: (path, body) => request("PUT", path, body),
  del: (path) => request("DELETE", path),
  /** multipart upload of one file under the field name "file" */
  upload: async (path, file) => {
    const form = new FormData();
    form.append("file", file, file.name);
    const response = await fetch(path, { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = data.error ?? {};
      throw new ApiError(response.status, error.code ?? "generic", error.message ?? response.statusText);
    }
    return data;
  },
};

export const enc = encodeURIComponent;
