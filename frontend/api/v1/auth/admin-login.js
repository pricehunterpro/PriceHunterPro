const crypto = require('crypto');

function createJWT(payload, secret) {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const body   = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const sig    = crypto.createHmac('sha256', secret).update(`${header}.${body}`).digest('base64url');
  return `${header}.${body}.${sig}`;
}

function getUsers() {
  const users = [];

  if (process.env.ADMIN_USER && process.env.ADMIN_PASSWORD) {
    users.push({ username: process.env.ADMIN_USER, password: process.env.ADMIN_PASSWORD, role: 'superadmin' });
  }
  if (process.env.TEST_USER && process.env.TEST_PASSWORD) {
    users.push({ username: process.env.TEST_USER, password: process.env.TEST_PASSWORD, role: 'viewer' });
  }

  return users;
}

module.exports = (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ detail: 'Method not allowed' });

  const { username, password } = req.body || {};
  const match = getUsers().find(u => u.username === username && u.password === password);

  if (!match) {
    return res.status(401).json({ detail: 'Credenciales inválidas' });
  }

  const secret = process.env.JWT_SECRET_KEY || 'change-me';
  const now    = Math.floor(Date.now() / 1000);
  const token  = createJWT(
    { sub: match.username, role: match.role, iat: now, exp: now + 86400, type: 'access' },
    secret,
  );

  res.status(200).json({ access_token: token, token_type: 'bearer' });
};
