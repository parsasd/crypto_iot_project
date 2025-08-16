import { NextApiRequest, NextApiResponse } from 'next';
import { Pool } from 'pg';
import jwt from 'jsonwebtoken';

const pool = new Pool({ connectionString: process.env.DATABASE_URL });
const JWT_SECRET = process.env.NEXTAUTH_SECRET || 'change-me';

function getEmail(req: NextApiRequest): string | null {
  const cookie = req.headers.cookie;
  if (!cookie) return null;
  const cookies = Object.fromEntries(cookie.split(';').map(c => c.trim().split('=')));
  const token = cookies['session'];
  if (!token) return null;
  try {
    const decoded: any = jwt.verify(token, JWT_SECRET);
    return decoded.email;
  } catch (err) {
    return null;
  }
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const email = getEmail(req);
  if (!email) {
    return res.status(401).json({ message: 'Unauthenticated' });
  }
  if (req.method !== 'POST') {
    return res.status(405).json({ message: 'Method not allowed' });
  }
  const { symbol, above, below } = req.body;
  if (typeof symbol !== 'string' || (!above && !below)) {
    return res.status(400).json({ message: 'Invalid parameters' });
  }
  const client = await pool.connect();
  try {
    await client.query(
      'INSERT INTO thresholds (user_email, symbol, above_price, below_price) VALUES ($1, $2, $3, $4)',
      [email, symbol, above || null, below || null]
    );
    return res.status(200).json({ message: 'Saved' });
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: 'Internal error' });
  } finally {
    client.release();
  }
}