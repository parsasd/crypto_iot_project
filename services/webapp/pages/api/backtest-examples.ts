import { NextApiRequest, NextApiResponse } from 'next';
import fetch from 'isomorphic-unfetch';
import jwt from 'jsonwebtoken';

const INDICATOR_API_URL = process.env.INDICATOR_API_URL || 'http://localhost:8000';
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
  const body = req.body;
  try {
    const response = await fetch(`${INDICATOR_API_URL}/backtest/examples`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (response.ok && data.examples) {
      // rewrite chart_path to absolute URLs served by indicator_api
      const rewritten = data.examples.map((ex: any) => {
        const filename = ex.chart_path.split('/').pop();
        return {
          ...ex,
          chart_url: `${INDICATOR_API_URL}/examples/${filename}`,
        };
      });
      return res.status(200).json({ examples: rewritten });
    }
    return res.status(response.status).json(data);
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: 'Failed to contact indicator API' });
  }
}