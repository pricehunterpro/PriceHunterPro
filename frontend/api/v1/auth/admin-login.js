const crypto = require('crypto');

function createJWT(payload, secret) {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const body   = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const sig    = crypto.createHmac('sha256', secret).update(`${header}.${body}`).digest('base64url');
  return `${header}.${body}.${sig}`;
}

/** Comparacion en tiempo constante: '===' filtra el largo del prefijo correcto. */
function safeEqual(a, b) {
  const bufA = Buffer.from(String(a ?? ''), 'utf8');
  const bufB = Buffer.from(String(b ?? ''), 'utf8');
  if (bufA.length !== bufB.length) return false;
  return crypto.timingSafeEqual(bufA, bufB);
}

function getUsers() {
  const users = [];

  if (process.env.ADMIN_USER && process.env.ADMIN_PASSWORD) {
    users.push({ username: process.env.ADMIN_USER, password: process.env.ADMIN_PASSWORD, role: 'superadmin' });
  }
  if (process.env.TEST_USER && process.env.TEST_PASSWORD) {
    users.push({ username: process.env.TEST_USER, password: process.env.TEST_PASSWORD, role: 'viewer' });
  }
  if (process.env.TEST2_USER && process.env.TEST2_PASSWORD) {
    users.push({ username: process.env.TEST2_USER, password: process.env.TEST2_PASSWORD, role: 'viewer' });
  }

  return users;
}

// Backend (usuarios creados en el modulo de Administracion). Configurable por
// entorno para no dejar el host clavado en el codigo.
const BACKEND = process.env.BACKEND_URL || 'https://pricehunterpro-production.up.railway.app';

// Limitador de fuerza bruta por IP. Vive en la memoria del contenedor: no es
// infalible con varias instancias, pero corta el goteo barato desde una IP.
const MAX_ATTEMPTS  = 8;
const WINDOW_MS     = 10 * 60 * 1000;
const attempts      = new Map();

function tooManyAttempts(ip) {
  const now  = Date.now();
  const slot = attempts.get(ip);
  if (!slot || now - slot.first > WINDOW_MS) return false;
  return slot.count >= MAX_ATTEMPTS;
}

function registerFailure(ip) {
  const now  = Date.now();
  const slot = attempts.get(ip);
  if (!slot || now - slot.first > WINDOW_MS) attempts.set(ip, { first: now, count: 1 });
  else slot.count += 1;
  if (attempts.size > 1000) attempts.clear();
}

module.exports = async (req, res) => {
  // Same-origin: el frontend se sirve desde este mismo dominio, no hace falta
  // abrir CORS a todo internet.
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');

  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'POST') return res.status(405).json({ detail: 'Method not allowed' });

  const secret = process.env.JWT_SECRET_KEY;
  if (!secret || secret === 'change-me') {
    // Sin secreto real cualquiera podria firmar un token con role=superadmin.
    console.error('JWT_SECRET_KEY no configurado en el entorno de Vercel');
    return res.status(500).json({ detail: 'Servicio de autenticacion mal configurado' });
  }

  const ip = (req.headers['x-forwarded-for'] || '').split(',')[0].trim() || 'unknown';
  if (tooManyAttempts(ip)) {
    return res.status(429).json({ detail: 'Demasiados intentos, espera unos minutos' });
  }

  const { username, password } = req.body || {};
  const match = getUsers().find(u => safeEqual(u.username, username) && safeEqual(u.password, password));

  if (match) {
    const now   = Math.floor(Date.now() / 1000);
    const token = createJWT(
      { sub: match.username, role: match.role, iat: now, exp: now + 86400, type: 'access' },
      secret,
    );
    return res.status(200).json({ access_token: token, token_type: 'bearer' });
  }

  // Fallback: usuarios del registro (Redis) validados por el backend
  try {
    const r = await fetch(`${BACKEND}/api/v1/auth/admin-login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await r.json();
    if (r.status >= 400) registerFailure(ip);
    return res.status(r.status).json(data);
  } catch (e) {
    registerFailure(ip);
    return res.status(401).json({ detail: 'Credenciales invalidas' });
  }
};
