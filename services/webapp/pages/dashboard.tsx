import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';

export default function Dashboard() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [symbols, setSymbols] = useState<string[]>([]);
  const [newSymbol, setNewSymbol] = useState('');
  const [thresholdSymbol, setThresholdSymbol] = useState('');
  const [above, setAbove] = useState('');
  const [below, setBelow] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    async function fetchMe() {
      const res = await fetch('/api/me');
      if (res.status === 401) {
        router.push('/');
        return;
      }
      const data = await res.json();
      setEmail(data.email);
      // fetch watchlist
      const wl = await fetch('/api/watchlist');
      const wlData = await wl.json();
      setSymbols(wlData.symbols || []);
    }
    fetchMe();
  }, [router]);

  const addSymbol = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage('');
    const res = await fetch('/api/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: newSymbol }),
    });
    const data = await res.json();
    if (res.ok) {
      setSymbols([...symbols, newSymbol]);
      setNewSymbol('');
    } else {
      setMessage(data.message || 'Error');
    }
  };
  const saveThreshold = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage('');
    const res = await fetch('/api/thresholds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: thresholdSymbol, above: above ? parseFloat(above) : null, below: below ? parseFloat(below) : null }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMessage(data.message || 'Error');
    } else {
      setThresholdSymbol('');
      setAbove('');
      setBelow('');
      setMessage('Threshold saved');
    }
  };
  return (
    <div style={{ maxWidth: '600px', margin: '2rem auto', fontFamily: 'sans-serif' }}>
      <h1>Dashboard</h1>
      <p>Welcome, {email}</p>
      <h2>Watchlist</h2>
      <ul>
        {symbols.map((sym) => (
          <li key={sym}>{sym}</li>
        ))}
      </ul>
      <form onSubmit={addSymbol}>
        <input type="text" value={newSymbol} onChange={(e) => setNewSymbol(e.target.value)} placeholder="symbol (e.g. bitcoin)" />
        <button type="submit">Add to watchlist</button>
      </form>
      <h2>Thresholds</h2>
      <form onSubmit={saveThreshold}>
        <input type="text" value={thresholdSymbol} onChange={(e) => setThresholdSymbol(e.target.value)} placeholder="symbol" />
        <input type="number" step="any" value={above} onChange={(e) => setAbove(e.target.value)} placeholder="above price" />
        <input type="number" step="any" value={below} onChange={(e) => setBelow(e.target.value)} placeholder="below price" />
        <button type="submit">Save</button>
      </form>
      <p><a href="/backtest">Go to Backtest</a></p>
      {message && <p style={{ color: 'green' }}>{message}</p>}
    </div>
  );
}