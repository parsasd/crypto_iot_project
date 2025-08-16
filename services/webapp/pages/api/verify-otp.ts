import { NextApiRequest, NextApiResponse } from 'next';
import { Pool } from 'pg';
import jwt from 'jsonwebtoken';

const pool = new Pool({ connectionString: process.env.DATABASE_URL });
const JWT_SECRET = process.env.NEXTAUTH_SECRET || 'change-me';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ message: 'Method not allowed' });
  }
  const { email, code } = req.body;
  if (typeof email !== 'string' || typeof code !== 'string') {
    return res.status(400).json({ message: 'Invalid request' });
  }
  const client = await pool.connect();
  try {
    const { rows } = await client.query('SELECT * FROM otps WHERE email = $1', [email]);
    if (rows.length === 0) {
      return res.status(400).json({ message: 'No OTP requested' });
    }
    const otp = rows[0];
    const expiresAt = new Date(otp.expires_at);
    if (otp.failed_attempts >= 5 || new Date() > expiresAt) {
      await client.query('DELETE FROM otps WHERE email = $1', [email]);
      return res.status(400).json({ message: 'OTP expired' });
    }
    if (otp.code !== code) {
      await client.query('UPDATE otps SET failed_attempts = failed_attempts + 1 WHERE email = $1', [email]);
      return res.status(400).json({ message: 'Invalid code' });
    }
    // success: remove otp and create JWT
    await client.query('DELETE FROM otps WHERE email = $1', [email]);
    const token = jwt.sign({ email }, JWT_SECRET, { expiresIn: '24h' });
    // set cookie
    res.setHeader('Set-Cookie', `session=${token}; HttpOnly; Path=/; Max-Age=86400`);
    return res.status(200).json({ message: 'Authenticated' });
  } catch (err: any) {
    console.error(err);
    return res.status(500).json({ message: 'Internal error' });
  } finally {
    client.release();
  }
}