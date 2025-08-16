import { NextApiRequest, NextApiResponse } from 'next';
import jwt from 'jsonwebtoken';

const JWT_SECRET = process.env.NEXTAUTH_SECRET || 'change-me';

function parseCookies(req: NextApiRequest) {
  const cookie = req.headers.cookie;
  const cookies: { [key: string]: string } = {};
  if (!cookie) return cookies;
  const items = cookie.split(';');
  items.forEach(item => {
    const [key, value] = item.trim().split('=');
    cookies[key] = decodeURIComponent(value);
  });
  return cookies;
}

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  const cookies = parseCookies(req);
  const token = cookies['session'];
  if (!token) {
    return res.status(401).json({ message: 'Unauthenticated' });
  }
  try {
    const decoded: any = jwt.verify(token, JWT_SECRET);
    return res.status(200).json({ email: decoded.email });
  } catch (err) {
    return res.status(401).json({ message: 'Invalid token' });
  }
}