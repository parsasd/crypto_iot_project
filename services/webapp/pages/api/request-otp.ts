import { NextApiRequest, NextApiResponse } from 'next';
import { Pool } from 'pg';
import nodemailer from 'nodemailer';

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ message: 'Method not allowed' });
  }
  const { email } = req.body;
  if (!email || typeof email !== 'string') {
    return res.status(400).json({ message: 'Invalid email' });
  }
  // Generate a 6‑digit code
  const code = Math.floor(100000 + Math.random() * 900000).toString();
  const expiresAt = new Date(Date.now() + 5 * 60 * 1000); // 5 minutes
  try {
    const client = await pool.connect();
    try {
      // ensure user exists
      await client.query(
        'INSERT INTO users (email, created_at) VALUES ($1, NOW()) ON CONFLICT (email) DO NOTHING',
        [email]
      );
      // insert OTP (delete previous)
      await client.query('DELETE FROM otps WHERE email = $1', [email]);
      await client.query(
        'INSERT INTO otps (email, code, expires_at, failed_attempts) VALUES ($1, $2, $3, 0)',
        [email, code, expiresAt.toISOString()]
      );
    } finally {
      client.release();
    }
    // Send email via nodemailer
    const transporter = nodemailer.createTransport({
      host: process.env.SMTP_HOST || 'mailhog',
      port: parseInt(process.env.SMTP_PORT || '1025', 10),
    });
    const mailOptions = {
      from: 'noreply@crypto.iot',
      to: email,
      subject: 'Your OTP code',
      text: `Your one‑time code is ${code}. It expires in 5 minutes.`,
    };
    await transporter.sendMail(mailOptions);
    return res.status(200).json({ message: 'OTP sent' });
  } catch (err: any) {
    console.error(err);
    return res.status(500).json({ message: 'Internal error' });
  }
}