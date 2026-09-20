/* Thin fetch wrappers. Every call returns parsed JSON or throws an Error whose
   message is the server's own wording, so the UI never has to invent one. */

const api = {
  async get(path) {
    const response = await fetch(path);
    return api._unwrap(response);
  },

  async post(path, body) {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return api._unwrap(response);
  },

  async put(path, body) {
    const response = await fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return api._unwrap(response);
  },

  async del(path) {
    return api._unwrap(await fetch(path, { method: 'DELETE' }));
  },

  async patch(path, body) {
    const response = await fetch(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return api._unwrap(response);
  },

  async _unwrap(response) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      throw new Error(`Server returned ${response.status} with no readable body`);
    }
    if (!response.ok) {
      const error = new Error(payload.error || `Request failed (${response.status})`);
      error.details = payload.details || [];
      throw error;
    }
    return payload;
  },
};
