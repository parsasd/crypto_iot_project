import { useState } from 'react';
import { useRouter } from 'next/router';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [otpRequested, setOtpRequested] = useState(false);
  const [code, setCode] = useState('');
  const [message, setMessage] = useState('');
  const router = useRouter();

  const requestOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage('');
    const res = await fetch('/api/request-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const data = await res.json();
    if (res.ok) {
      setOtpRequested(true);
      setMessage('OTP sent. Check MailHog!');
    } else {
      setMessage(data.message || 'Error');
    }
  };
  const verifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage('');
    const res = await fetch('/api/verify-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, code }),
    });
    const data = await res.json();
    if (res.ok) {
      router.push('/dashboard');
    } else {
      setMessage(data.message || 'Error');
    }
  };
  return (
    <div style={{ maxWidth: '400px', margin: '2rem auto', fontFamily: 'sans-serif' }}>
      <h1>Crypto IoT Demo Login</h1>
      {!otpRequested ? (
        <form onSubmit={requestOtp}>
          <label>Email:<br />
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <br />
          <button type="submit">Send OTP</button>
        </form>
      ) : (
        <form onSubmit={verifyOtp}>
          <p>Enter the 6 digit code sent to {email}</p>
          <input type="text" value={code} onChange={(e) => setCode(e.target.value)} required />
          <br />
          <button type="submit">Verify &amp; Login</button>
        </form>
      )}
      {message && <p style={{ color: 'red' }}>{message}</p>}
    </div>
  );
}