import { NextApiRequest, NextApiResponse } from 'next';
import { Pool } from 'pg';
import jwt from 'jsonwebtoken';

const pool = new Pool({ connectionString: process.env.DATABASE_URL });
const JWT_SECRET = process.env.NEXTAUTH_SECRET || 'change-me';

function getEmailFromReq(req: NextApiRequest): string | null {
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
  const email = getEmailFromReq(req);
  if (!email) {
    return res.status(401).json({ message: 'Unauthenticated' });
  }
  const client = await pool.connect();
  try {
    if (req.method === 'GET') {
      const { rows } = await client.query('SELECT symbol FROM watchlists WHERE user_email = $1', [email]);
      const symbols = rows.map((r: any) => r.symbol);
      return res.status(200).json({ symbols });
    } else if (req.method === 'POST') {
      const { symbol } = req.body;
      if (!symbol || typeof symbol !== 'string') {
        return res.status(400).json({ message: 'Invalid symbol' });
      }
      await client.query(
        'INSERT INTO watchlists (user_email, symbol) VALUES ($1, $2) ON CONFLICT DO NOTHING',
        [email, symbol]
      );
      return res.status(200).json({ message: 'Added' });
    } else {
      return res.status(405).json({ message: 'Method not allowed' });
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: 'Internal error' });
  } finally {
    client.release();
  }
}